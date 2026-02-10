"""
RestyleService 单元测试

覆盖:
- PDF → Images 转换
- PPT → Images 转换 (mock LibreOffice)
- 文件格式校验
- 边界条件
"""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from services.restyle_service import RestyleService


class TestConvertToImages:
    """convert_to_images 方法测试"""

    def test_unsupported_format_raises(self):
        """不支持的格式应抛出 ValueError"""
        service = RestyleService()
        with pytest.raises(ValueError, match="Unsupported file format"):
            service.convert_to_images("/tmp/test.docx", "/tmp/out")

    def test_unsupported_format_txt(self):
        """txt 格式不支持"""
        service = RestyleService()
        with pytest.raises(ValueError, match="Unsupported file format"):
            service.convert_to_images("/tmp/test.txt", "/tmp/out")

    def test_routes_pdf_to_pdf_handler(self):
        """PDF 文件应走 _pdf_to_images 路径"""
        service = RestyleService()
        with patch.object(service, '_pdf_to_images', return_value=['/tmp/slide_001.png']) as mock:
            result = service.convert_to_images("/tmp/test.pdf", "/tmp/out", dpi=150)
            mock.assert_called_once_with("/tmp/test.pdf", "/tmp/out", 150)
            assert result == ['/tmp/slide_001.png']

    def test_routes_pptx_to_pptx_handler(self):
        """PPTX 文件应走 _pptx_to_images 路径"""
        service = RestyleService()
        with patch.object(service, '_pptx_to_images', return_value=['/tmp/slide_001.png']) as mock:
            result = service.convert_to_images("/tmp/test.pptx", "/tmp/out")
            mock.assert_called_once()

    def test_routes_ppt_to_pptx_handler(self):
        """PPT 文件也应走 _pptx_to_images 路径"""
        service = RestyleService()
        with patch.object(service, '_pptx_to_images', return_value=[]) as mock:
            service.convert_to_images("/tmp/test.ppt", "/tmp/out")
            mock.assert_called_once()

    def test_creates_output_dir(self):
        """应自动创建输出目录"""
        service = RestyleService()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "subdir", "output")
            with patch.object(service, '_pdf_to_images', return_value=[]):
                service.convert_to_images("/tmp/test.pdf", output_dir)
            assert os.path.isdir(output_dir)


class TestPdfToImages:
    """_pdf_to_images 方法测试"""

    def test_pdf_to_images_basic(self):
        """基础 PDF → Images 转换 (使用真实 PyMuPDF)"""
        service = RestyleService()

        # 用 PyMuPDF 创建一个简单的 test PDF
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF (fitz) not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 2 页 test PDF
            pdf_path = os.path.join(tmpdir, "test.pdf")
            doc = fitz.open()
            for i in range(2):
                page = doc.new_page(width=1920, height=1080)
                page.insert_text((100, 100), f"Test Page {i+1}", fontsize=48)
            doc.save(pdf_path)
            doc.close()

            # 转换
            output_dir = os.path.join(tmpdir, "output")
            result = service._pdf_to_images(pdf_path, output_dir, dpi=72)

            assert len(result) == 2
            for path in result:
                assert os.path.exists(path)
                assert path.endswith('.png')

    def test_pdf_to_images_naming(self):
        """输出文件命名应为 slide_001.png, slide_002.png ..."""
        service = RestyleService()

        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF (fitz) not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            doc = fitz.open()
            for _ in range(3):
                doc.new_page()
            doc.save(pdf_path)
            doc.close()

            output_dir = os.path.join(tmpdir, "output")
            result = service._pdf_to_images(pdf_path, output_dir, dpi=72)

            assert len(result) == 3
            assert result[0].endswith("slide_001.png")
            assert result[1].endswith("slide_002.png")
            assert result[2].endswith("slide_003.png")

    def test_pdf_to_images_dpi(self):
        """高 DPI 应产生更大的图片"""
        service = RestyleService()

        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF (fitz) not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            doc = fitz.open()
            doc.new_page(width=100, height=100)
            doc.save(pdf_path)
            doc.close()

            # 72 dpi (1:1)
            out_72 = os.path.join(tmpdir, "out72")
            service._pdf_to_images(pdf_path, out_72, dpi=72)

            # 144 dpi (2x)
            out_144 = os.path.join(tmpdir, "out144")
            service._pdf_to_images(pdf_path, out_144, dpi=144)

            from PIL import Image
            img72 = Image.open(os.path.join(out_72, "slide_001.png"))
            img144 = Image.open(os.path.join(out_144, "slide_001.png"))

            # 144 dpi 应该是 72 dpi 的 2 倍尺寸
            assert img144.width > img72.width


class TestPptxToImages:
    """_pptx_to_images 方法测试 (Mock LibreOffice)"""

    def test_libreoffice_not_found(self):
        """LibreOffice 未安装时应抛出 RuntimeError"""
        service = RestyleService()
        with patch.object(RestyleService, '_find_libreoffice', side_effect=RuntimeError("LibreOffice not found")):
            with pytest.raises(RuntimeError, match="LibreOffice not found"):
                service._pptx_to_images("/tmp/test.pptx", "/tmp/out")

    def test_libreoffice_conversion_failure(self):
        """LibreOffice 转换失败应抛出 RuntimeError"""
        service = RestyleService()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "conversion error"

        with patch.object(RestyleService, '_find_libreoffice', return_value='soffice'):
            with patch('subprocess.run', return_value=mock_result):
                with pytest.raises(RuntimeError, match="LibreOffice conversion failed"):
                    service._pptx_to_images("/tmp/test.pptx", "/tmp/out")


class TestFindLibreoffice:
    """_find_libreoffice 静态方法测试"""

    def test_find_libreoffice_success(self):
        """至少一个候选路径能找到 LibreOffice"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "LibreOffice 7.6"

        with patch('subprocess.run', return_value=mock_result):
            result = RestyleService._find_libreoffice()
            assert result in ['libreoffice', 'soffice', '/usr/bin/libreoffice',
                              '/usr/bin/soffice',
                              '/Applications/LibreOffice.app/Contents/MacOS/soffice']

    def test_find_libreoffice_not_found(self):
        """所有候选路径都找不到时应抛出 RuntimeError"""
        with patch('subprocess.run', side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="LibreOffice not found"):
                RestyleService._find_libreoffice()


class TestRestylePrompt:
    """get_restyle_prompt 函数测试"""

    def test_basic_prompt(self):
        """基础 prompt 生成"""
        from services.prompts import get_restyle_prompt
        prompt = get_restyle_prompt("使用蓝色主题", page_index=1, total_pages=5)

        assert "风格参考" in prompt
        assert "原始PPT页面" in prompt
        assert "1/5" in prompt
        assert "品牌规范" in prompt
        assert "蓝色主题" in prompt
        # 新增：验证关键结构部分
        assert "内容100%保留" in prompt
        assert "风格100%转换" in prompt
        assert "风格转换要素" in prompt
        assert "内容保留规则" in prompt

    def test_prompt_without_brand(self):
        """无品牌规范时不应包含品牌部分"""
        from services.prompts import get_restyle_prompt
        prompt = get_restyle_prompt("", page_index=2, total_pages=5)

        assert "品牌规范" not in prompt
        assert "2/5" in prompt

    def test_cover_page_prompt(self):
        """封面页应有特殊提示"""
        from services.prompts import get_restyle_prompt
        prompt = get_restyle_prompt("", page_index=1, total_pages=5)

        assert "封面" in prompt

    def test_last_page_prompt(self):
        """尾页应有特殊提示"""
        from services.prompts import get_restyle_prompt
        prompt = get_restyle_prompt("", page_index=5, total_pages=5)

        assert "尾页" in prompt

    def test_middle_page_no_special_hint(self):
        """中间页无特殊提示"""
        from services.prompts import get_restyle_prompt
        prompt = get_restyle_prompt("", page_index=3, total_pages=5)

        assert "封面" not in prompt
        assert "尾页" not in prompt

    def test_content_preservation_rules(self):
        """验证内容保留规则覆盖各类型"""
        from services.prompts import get_restyle_prompt
        prompt = get_restyle_prompt("", page_index=2, total_pages=5)

        assert "标题文字" in prompt
        assert "图表" in prompt
        assert "表格" in prompt
        assert "数据" in prompt
