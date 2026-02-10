"""
Restyle Service - PPT/PDF → slide images → restyle → new PPTX
"""
import os
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)


class RestyleService:
    """PPT/PDF → slide images → restyle → new PPTX"""

    def convert_to_images(self, file_path: str, output_dir: str, dpi: int = 300) -> list[str]:
        """
        将PPT/PDF转为逐页PNG图片

        Args:
            file_path: 源文件路径 (.pptx/.ppt/.pdf)
            output_dir: 输出目录
            dpi: 输出分辨率 (default 300)

        Returns:
            PNG图片路径列表, 按页码排序
        """
        ext = Path(file_path).suffix.lower()
        os.makedirs(output_dir, exist_ok=True)

        if ext in ('.ppt', '.pptx'):
            return self._pptx_to_images(file_path, output_dir, dpi)
        elif ext == '.pdf':
            return self._pdf_to_images(file_path, output_dir, dpi)
        else:
            raise ValueError(f"Unsupported file format: {ext}. Supported: .pptx, .ppt, .pdf")

    def _pptx_to_images(self, file_path: str, output_dir: str, dpi: int = 300) -> list[str]:
        """
        PPT/PPTX → PDF (via LibreOffice) → PNG[]

        Pipeline:
            PPT/PPTX --LibreOffice headless--> PDF --PyMuPDF--> PNG[]
        """
        # Step 1: LibreOffice headless → PDF
        with tempfile.TemporaryDirectory() as tmp_dir:
            logger.info(f"Converting PPT to PDF via LibreOffice: {file_path}")

            # Try different LibreOffice paths
            libreoffice_cmd = self._find_libreoffice()

            result = subprocess.run(
                [
                    libreoffice_cmd,
                    '--headless',
                    '--convert-to', 'pdf',
                    '--outdir', tmp_dir,
                    file_path
                ],
                capture_output=True, text=True, timeout=120
            )

            if result.returncode != 0:
                logger.error(f"LibreOffice conversion failed: {result.stderr}")
                raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")

            # Find the generated PDF
            pdf_files = list(Path(tmp_dir).glob('*.pdf'))
            if not pdf_files:
                raise RuntimeError("LibreOffice did not generate PDF output")

            pdf_path = str(pdf_files[0])
            logger.info(f"PDF generated: {pdf_path}")

            # Step 2: PDF → PNG
            return self._pdf_to_images(pdf_path, output_dir, dpi)

    def _pdf_to_images(self, file_path: str, output_dir: str, dpi: int = 300) -> list[str]:
        """
        PDF → PNG[] via PyMuPDF (fitz)
        """
        import fitz  # PyMuPDF

        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Converting PDF to images: {file_path} (dpi={dpi})")
        doc = fitz.open(file_path)
        image_paths = []

        zoom = dpi / 72  # PDF base resolution is 72 dpi
        matrix = fitz.Matrix(zoom, zoom)

        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)

            output_path = os.path.join(output_dir, f"slide_{page_num + 1:03d}.png")
            pix.save(output_path)
            image_paths.append(output_path)

            logger.debug(f"Page {page_num + 1}/{len(doc)} → {output_path} ({pix.width}x{pix.height})")

        doc.close()
        logger.info(f"Converted {len(image_paths)} pages to PNG images")
        return image_paths

    @staticmethod
    def _find_libreoffice() -> str:
        """Find LibreOffice executable path"""
        candidates = [
            'libreoffice',
            'soffice',
            '/usr/bin/libreoffice',
            '/usr/bin/soffice',
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',  # macOS
        ]
        for cmd in candidates:
            try:
                result = subprocess.run(
                    [cmd, '--version'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    logger.debug(f"Found LibreOffice: {cmd} ({result.stdout.strip()})")
                    return cmd
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        raise RuntimeError(
            "LibreOffice not found. Install via: "
            "macOS: brew install --cask libreoffice | "
            "Ubuntu: apt-get install libreoffice-impress"
        )
