"""
AI Service - handles all AI model interactions
Based on demo.py and gemini_genai.py
TODO: use structured output API
"""
import os
import json
import re
import logging
import requests
from dataclasses import dataclass
from typing import List, Dict, Optional, Union
from textwrap import dedent
from PIL import Image
from tenacity import retry, stop_after_attempt, retry_if_exception_type
from .prompts import (
    get_outline_generation_prompt,
    get_outline_parsing_prompt,
    get_page_description_prompt,
    get_image_generation_prompt,
    get_image_edit_prompt,
    get_description_to_outline_prompt,
    get_description_split_prompt,
    get_outline_refinement_prompt,
    get_descriptions_refinement_prompt
)
from .ai_providers import get_text_provider, get_image_provider, TextProvider, ImageProvider
from config import get_config


@dataclass
class ImageRef:
    """Image reference metadata for markdown image normalization"""
    id: str
    alt: str
    url: str
    source_index: int

logger = logging.getLogger(__name__)


class ProjectContext:
    """项目上下文数据类，统一管理 AI 需要的所有项目信息"""
    
    def __init__(self, project_or_dict, reference_files_content: Optional[List[Dict[str, str]]] = None):
        """
        Args:
            project_or_dict: 项目对象（Project model）或项目字典（project.to_dict()）
            reference_files_content: 参考文件内容列表
        """
        # 支持直接传入 Project 对象，避免 to_dict() 调用，提升性能
        if hasattr(project_or_dict, 'idea_prompt'):
            # 是 Project 对象
            self.idea_prompt = project_or_dict.idea_prompt
            self.outline_text = project_or_dict.outline_text
            self.description_text = project_or_dict.description_text
            self.creation_type = project_or_dict.creation_type or 'idea'
        else:
            # 是字典
            self.idea_prompt = project_or_dict.get('idea_prompt')
            self.outline_text = project_or_dict.get('outline_text')
            self.description_text = project_or_dict.get('description_text')
            self.creation_type = project_or_dict.get('creation_type', 'idea')
        
        self.reference_files_content = reference_files_content or []
    
    def to_dict(self) -> Dict:
        """转换为字典，方便传递"""
        return {
            'idea_prompt': self.idea_prompt,
            'outline_text': self.outline_text,
            'description_text': self.description_text,
            'creation_type': self.creation_type,
            'reference_files_content': self.reference_files_content
        }


class AIService:
    """Service for AI model interactions using pluggable providers"""
    
    def __init__(self, text_provider: TextProvider = None, image_provider: ImageProvider = None):
        """
        Initialize AI service with providers
        
        Args:
            text_provider: Optional pre-configured TextProvider. If None, created from factory.
            image_provider: Optional pre-configured ImageProvider. If None, created from factory.
        """
        config = get_config()

        # 优先使用 Flask app.config（可由 Settings 覆盖），否则回退到 Config 默认值
        try:
            from flask import current_app, has_app_context
        except ImportError:
            current_app = None  # type: ignore
            has_app_context = lambda: False  # type: ignore

        if has_app_context() and current_app and hasattr(current_app, "config"):
            self.text_model = current_app.config.get("TEXT_MODEL", config.TEXT_MODEL)
            self.image_model = current_app.config.get("IMAGE_MODEL", config.IMAGE_MODEL)
            # 分离的文本和图像推理配置
            self.enable_text_reasoning = current_app.config.get("ENABLE_TEXT_REASONING", False)
            self.text_thinking_budget = current_app.config.get("TEXT_THINKING_BUDGET", 1024)
            self.image_thinking_level = current_app.config.get("IMAGE_THINKING_LEVEL", "none")
        else:
            self.text_model = config.TEXT_MODEL
            self.image_model = config.IMAGE_MODEL
            self.enable_text_reasoning = False
            self.text_thinking_budget = 1024
            self.image_thinking_level = "none"
        
        # Use provided providers or create from factory based on AI_PROVIDER_FORMAT (from Flask config or env var)
        self.text_provider = text_provider or get_text_provider(model=self.text_model)
        self.image_provider = image_provider or get_image_provider(model=self.image_model)
    
    def _get_text_thinking_budget(self) -> int:
        """
        获取文本生成的思考负载
        
        Returns:
            如果启用文本推理则返回配置的 budget，否则返回 0
        """
        return self.text_thinking_budget if self.enable_text_reasoning else 0
    
    def _get_image_thinking_level(self) -> str:
        """
        获取图像生成的思考级别
        
        Returns:
            Thinking level string: "none", "minimal", "high"
        """
        return self.image_thinking_level
    
    @staticmethod
    def extract_image_urls_from_markdown(text: str) -> List[str]:
        """
        从 markdown 文本中提取图片 URL
        
        Args:
            text: Markdown 文本，可能包含 ![](url) 格式的图片
            
        Returns:
            图片 URL 列表（包括 http/https URL 和 /files/ 开头的本地路径）
        """
        if not text:
            return []
        
        # 匹配 markdown 图片语法: ![](url) 或 ![alt](url)
        pattern = r'!\[.*?\]\((.*?)\)'
        matches = re.findall(pattern, text)
        
        # 过滤掉空字符串，支持 http/https URL 和 /files/ 开头的本地路径（包括 mineru、materials 等）
        urls = []
        for url in matches:
            url = url.strip()
            if url and (url.startswith('http://') or url.startswith('https://') or url.startswith('/files/')):
                urls.append(url)
        
        return urls
    
    @staticmethod
    def _is_supported_image_url(url: str) -> bool:
        """
        检查 URL 是否为支持的图片 URL

        Args:
            url: 要检查的 URL

        Returns:
            如果 URL 是受支持的图片 URL 则返回 True
        """
        if not url:
            return False
        url = url.strip()
        return (
            url.startswith('http://')
            or url.startswith('https://')
            or url.startswith('/files/')
        )

    @staticmethod
    def normalize_markdown_image_references(text: str) -> tuple[str, List[ImageRef]]:
        """
        将 Markdown 图片语法转换为结构化图片引用标记

        将 ![alt](url) 转换为 [IMAGE_REF:image_N alt="alt"] 格式，
        同时返回图片引用元数据列表。

        Args:
            text: 包含 Markdown 图片语法的文本

        Returns:
            元组 (normalized_text, image_refs)
            - normalized_text: 替换后的文本，包含 IMAGE_REF 标记
            - image_refs: ImageRef 对象列表，包含 id, alt, url, source_index
        """
        if not text:
            return text, []

        refs: List[ImageRef] = []
        MARKDOWN_IMAGE_RE = re.compile(r'!\[(.*?)\]\(([^\)]+)\)')

        def repl(match):
            alt = match.group(1).strip()
            url = match.group(2).strip()

            # 只处理受支持的图片 URL
            if not AIService._is_supported_image_url(url):
                return match.group(0)

            ref = ImageRef(
                id=f"image_{len(refs) + 1}",
                alt=alt or "user provided image",
                url=url,
                source_index=len(refs) + 1,
            )
            refs.append(ref)
            # 返回结构化标记，保留语义位置
            return f'[IMAGE_REF:{ref.id} alt="{ref.alt}"]'

        normalized_text = MARKDOWN_IMAGE_RE.sub(repl, text)
        return normalized_text, refs

    @retry(
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((json.JSONDecodeError, ValueError)),
        reraise=True
    )
    def generate_json(self, prompt: str, thinking_budget: int = 1000) -> Union[Dict, List]:
        """
        生成并解析JSON，如果解析失败则重新生成
        
        Args:
            prompt: 生成提示词
            thinking_budget: 思考预算（会根据 enable_text_reasoning 配置自动调整）
            
        Returns:
            解析后的JSON对象（字典或列表）
            
        Raises:
            json.JSONDecodeError: JSON解析失败（重试3次后仍失败）
        """
        # 调用AI生成文本（根据 enable_text_reasoning 配置调整 thinking_budget）
        actual_budget = self._get_text_thinking_budget()
        response_text = self.text_provider.generate_text(prompt, thinking_budget=actual_budget)
        
        # 清理响应文本：移除markdown代码块标记和多余空白
        cleaned_text = response_text.strip().strip("```json").strip("```").strip()
        
        try:
            return json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败，将重新生成。原始文本: {cleaned_text[:200]}... 错误: {str(e)}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((json.JSONDecodeError, ValueError)),
        reraise=True
    )
    def generate_json_with_image(self, prompt: str, image_path: str, thinking_budget: int = 1000) -> Union[Dict, List]:
        """
        带图片输入的JSON生成，如果解析失败则重新生成（最多重试3次）
        
        Args:
            prompt: 生成提示词
            image_path: 图片文件路径
            thinking_budget: 思考预算（会根据 enable_text_reasoning 配置自动调整）
            
        Returns:
            解析后的JSON对象（字典或列表）
            
        Raises:
            json.JSONDecodeError: JSON解析失败（重试3次后仍失败）
            ValueError: text_provider 不支持图片输入
        """
        # 调用AI生成文本（带图片），根据 enable_text_reasoning 配置调整 thinking_budget
        actual_budget = self._get_text_thinking_budget()
        if hasattr(self.text_provider, 'generate_with_image'):
            response_text = self.text_provider.generate_with_image(
                prompt=prompt,
                image_path=image_path,
                thinking_budget=actual_budget
            )
        elif hasattr(self.text_provider, 'generate_text_with_images'):
            response_text = self.text_provider.generate_text_with_images(
                prompt=prompt,
                images=[image_path],
                thinking_budget=actual_budget
            )
        else:
            raise ValueError("text_provider 不支持图片输入")
        
        # 清理响应文本：移除markdown代码块标记和多余空白
        cleaned_text = response_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        
        try:
            return json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败（带图片），将重新生成。原始文本: {cleaned_text[:200]}... 错误: {str(e)}")
            raise
    
    @staticmethod
    def _convert_mineru_path_to_local(mineru_path: str) -> Optional[str]:
        """
        将 /files/mineru/{extract_id}/{rel_path} 格式的路径转换为本地文件系统路径（支持前缀匹配）
        
        Args:
            mineru_path: MinerU URL 路径，格式为 /files/mineru/{extract_id}/{rel_path}
            
        Returns:
            本地文件系统路径，如果转换失败则返回 None
        """
        from utils.path_utils import find_mineru_file_with_prefix
        
        matched_path = find_mineru_file_with_prefix(mineru_path)
        return str(matched_path) if matched_path else None
    
    @staticmethod
    def download_image_from_url(url: str) -> Optional[Image.Image]:
        """
        从 URL 下载图片并返回 PIL Image 对象
        
        Args:
            url: 图片 URL
            
        Returns:
            PIL Image 对象，如果下载失败则返回 None
        """
        try:
            logger.debug(f"Downloading image from URL: {url}")
            response = requests.get(url, timeout=30, stream=True)
            response.raise_for_status()
            
            # 从响应内容创建 PIL Image
            image = Image.open(response.raw)
            # 确保图片被加载
            image.load()
            logger.debug(f"Successfully downloaded image: {image.size}, {image.mode}")
            return image
        except Exception as e:
            logger.error(f"Failed to download image from {url}: {str(e)}")
            return None
    
    def generate_outline(self, project_context: ProjectContext, language: str = None) -> List[Dict]:
        """
        Generate PPT outline from idea prompt
        Based on demo.py gen_outline()
        
        Args:
            project_context: 项目上下文对象，包含所有原始信息
            
        Returns:
            List of outline items (may contain parts with pages or direct pages)
        """
        outline_prompt = get_outline_generation_prompt(project_context, language)
        outline = self.generate_json(outline_prompt, thinking_budget=1000)
        return outline
    
    def parse_outline_text(self, project_context: ProjectContext, language: str = None) -> List[Dict]:
        """
        Parse user-provided outline text into structured outline format
        This method analyzes the text and splits it into pages without modifying the original text
        
        Args:
            project_context: 项目上下文对象，包含所有原始信息
        
        Returns:
            List of outline items (may contain parts with pages or direct pages)
        """
        parse_prompt = get_outline_parsing_prompt(project_context, language)
        outline = self.generate_json(parse_prompt, thinking_budget=1000)
        return outline
    
    def flatten_outline(self, outline: List[Dict]) -> List[Dict]:
        """
        Flatten outline structure to page list
        Based on demo.py flatten_outline()
        """
        pages = []
        for item in outline:
            if "part" in item and "pages" in item:
                # This is a part, expand its pages
                for page in item["pages"]:
                    page_with_part = page.copy()
                    page_with_part["part"] = item["part"]
                    pages.append(page_with_part)
            else:
                # This is a direct page
                pages.append(item)
        return pages
    
    def generate_page_description(self, project_context: ProjectContext, outline: List[Dict], 
                                 page_outline: Dict, page_index: int, language='zh') -> str:
        """
        Generate description for a single page
        Based on demo.py gen_desc() logic
        
        Args:
            project_context: 项目上下文对象，包含所有原始信息
            outline: Complete outline
            page_outline: Outline for this specific page
            page_index: Page number (1-indexed)
        
        Returns:
            Text description for the page
        """
        part_info = f"\nThis page belongs to: {page_outline['part']}" if 'part' in page_outline else ""
        
        desc_prompt = get_page_description_prompt(
            project_context=project_context,
            outline=outline,
            page_outline=page_outline,
            page_index=page_index,
            part_info=part_info,
            language=language
        )
        
        # 根据 enable_text_reasoning 配置调整 thinking_budget
        actual_budget = self._get_text_thinking_budget()
        response_text = self.text_provider.generate_text(desc_prompt, thinking_budget=actual_budget)
        
        return dedent(response_text)
    
    def generate_outline_text(self, outline: List[Dict]) -> str:
        """
        Convert outline to text format for prompts
        Based on demo.py gen_outline_text()
        """
        text_parts = []
        for i, item in enumerate(outline, 1):
            if "part" in item and "pages" in item:
                text_parts.append(f"{i}. {item['part']}")
            else:
                text_parts.append(f"{i}. {item.get('title', 'Untitled')}")
        result = "\n".join(text_parts)
        return dedent(result)
    
    def generate_image_prompt(self, outline: List[Dict], page: Dict,
                            page_desc: str, page_index: int,
                            has_material_images: bool = False,
                            extra_requirements: Optional[str] = None,
                            language='zh',
                            has_template: bool = True) -> str:
        """
        Generate image generation prompt for a page
        Based on demo.py gen_prompts()

        Args:
            outline: Complete outline
            page: Page outline data
            page_desc: Page description text
            page_index: Page number (1-indexed)
            has_material_images: 是否有素材图片（从项目描述中提取的图片）
            extra_requirements: Optional extra requirements to apply to all pages
            language: Output language
            has_template: 是否有模板图片（False表示无模板图模式）

        Returns:
            Image generation prompt
        """
        outline_text = self.generate_outline_text(outline)

        # Determine current section
        if 'part' in page:
            current_section = page['part']
        else:
            current_section = f"{page.get('title', 'Untitled')}"

        # 将 Markdown 图片语法转换为结构化引用标记
        # 保留语义位置信息，同时获取图片引用元数据用于生成图片清单
        normalized_page_desc, image_refs = self.normalize_markdown_image_references(page_desc)

        # 将 ImageRef 对象转换为字典列表
        image_refs_dict = [
            {"id": ref.id, "alt": ref.alt, "url": ref.url, "source_index": ref.source_index}
            for ref in image_refs
        ]

        prompt = get_image_generation_prompt(
            page_desc=normalized_page_desc,
            outline_text=outline_text,
            current_section=current_section,
            has_material_images=has_material_images,
            extra_requirements=extra_requirements,
            language=language,
            has_template=has_template,
            page_index=page_index,
            image_refs=image_refs_dict
        )

        return prompt
    
    def generate_image(self, prompt: str, ref_image_path: Optional[str] = None, 
                      aspect_ratio: str = "16:9", resolution: str = "2K",
                      additional_ref_images: Optional[List[Union[str, Image.Image]]] = None) -> Optional[Image.Image]:
        """
        Generate image using configured image provider
        Based on gemini_genai.py gen_image()
        
        Args:
            prompt: Image generation prompt
            ref_image_path: Path to reference image (optional). If None, will generate based on prompt only.
            aspect_ratio: Image aspect ratio
            resolution: Image resolution (note: OpenAI format only supports 1K)
            additional_ref_images: 额外的参考图片列表，可以是本地路径、URL 或 PIL Image 对象
        
        Returns:
            PIL Image object or None if failed
        
        Raises:
            Exception with detailed error message if generation fails
        """
        try:
            logger.debug(f"Reference image: {ref_image_path}")
            if additional_ref_images:
                logger.debug(f"Additional reference images: {len(additional_ref_images)}")
            logger.debug(f"Config - aspect_ratio: {aspect_ratio}, resolution: {resolution}")

            # 构建参考图片列表
            ref_images = []
            
            # 添加主参考图片（如果提供了路径）
            if ref_image_path:
                if not os.path.exists(ref_image_path):
                    raise FileNotFoundError(f"Reference image not found: {ref_image_path}")
                main_ref_image = Image.open(ref_image_path)
                ref_images.append(main_ref_image)
            
            # 添加额外的参考图片
            if additional_ref_images:
                for ref_img in additional_ref_images:
                    if isinstance(ref_img, Image.Image):
                        # 已经是 PIL Image 对象
                        ref_images.append(ref_img)
                    elif isinstance(ref_img, str):
                        # 可能是本地路径或 URL
                        if os.path.exists(ref_img):
                            # 本地路径
                            ref_images.append(Image.open(ref_img))
                        elif ref_img.startswith('http://') or ref_img.startswith('https://'):
                            # URL，需要下载
                            downloaded_img = self.download_image_from_url(ref_img)
                            if downloaded_img:
                                ref_images.append(downloaded_img)
                            else:
                                logger.warning(f"Failed to download image from URL: {ref_img}, skipping...")
                        elif ref_img.startswith('/files/mineru/'):
                            # MinerU 本地文件路径，需要转换为文件系统路径（支持前缀匹配）
                            local_path = self._convert_mineru_path_to_local(ref_img)
                            if local_path and os.path.exists(local_path):
                                ref_images.append(Image.open(local_path))
                                logger.debug(f"Loaded MinerU image from local path: {local_path}")
                            else:
                                logger.warning(f"MinerU image file not found (with prefix matching): {ref_img}, skipping...")
                        elif ref_img.startswith('/files/'):
                            # 通用 /files/ 路径（materials、项目文件等），转换为文件系统路径
                            upload_folder = os.environ.get('UPLOAD_FOLDER', '')
                            relative_path = ref_img[len('/files/'):].lstrip('/')
                            local_path = os.path.abspath(os.path.join(upload_folder, relative_path))
                            if not local_path.startswith(os.path.abspath(upload_folder)):
                                logger.warning(f"Path traversal attempt blocked: {ref_img}, skipping...")
                            elif os.path.exists(local_path):
                                ref_images.append(Image.open(local_path))
                                logger.debug(f"Loaded image from local path: {local_path}")
                            else:
                                logger.warning(f"Local file not found: {local_path} (from {ref_img}), skipping...")
                        else:
                            logger.warning(f"Invalid image reference: {ref_img}, skipping...")
            
            logger.debug(f"Calling image provider for generation with {len(ref_images)} reference images...")
            logger.debug(f"Image thinking level: {self._get_image_thinking_level()}")
            
            # 使用 image_provider 生成图片
            return self.image_provider.generate_image(
                prompt=prompt,
                ref_images=ref_images if ref_images else None,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                thinking_level=self._get_image_thinking_level()
            )
            
        except Exception as e:
            error_detail = f"Error generating image: {type(e).__name__}: {str(e)}"
            logger.error(error_detail, exc_info=True)
            raise Exception(error_detail) from e
    
    def edit_image(self, prompt: str, current_image_path: str,
                  aspect_ratio: str = "16:9", resolution: str = "2K",
                  original_description: str = None,
                  additional_ref_images: Optional[List[Union[str, Image.Image]]] = None) -> Optional[Image.Image]:
        """
        Edit existing image with natural language instruction
        Uses current image as reference
        
        Args:
            prompt: Edit instruction
            current_image_path: Path to current page image
            aspect_ratio: Image aspect ratio
            resolution: Image resolution
            original_description: Original page description to include in prompt
            additional_ref_images: 额外的参考图片列表，可以是本地路径、URL 或 PIL Image 对象
        
        Returns:
            PIL Image object or None if failed
        """
        # Build edit instruction with original description if available
        edit_instruction = get_image_edit_prompt(
            edit_instruction=prompt,
            original_description=original_description
        )
        return self.generate_image(edit_instruction, current_image_path, aspect_ratio, resolution, additional_ref_images)
    
    def edit_restyle_image_with_context(self, context, aspect_ratio='16:9', resolution='2K', trace_context=None):
        """
        Edit restyle image using conversation context with single fallback.
        
        Args:
            context: RestyleEditContext from build_restyle_edit_context()
            aspect_ratio: Image aspect ratio
            resolution: Image resolution
        
        Returns:
            PIL Image or raises
        """
        from config import get_config
        from .restyle_edit_context import is_retryable_conversation_error
        from .restyle_edit_debug import (
            enrich_image_manifest,
            log_restyle_edit_event,
            maybe_write_debug_artifact,
            serialize_conversation_contents,
        )

        config = get_config()
        trace = trace_context or {}
        conversation_attempted = False
        provider_fallback = False
        conversation_supported = getattr(self.image_provider, 'supports_conversation_contents', False)
        conversation_fallback_allowed = getattr(self.image_provider, 'allow_conversation_fallback', True)
        snapshot_present = context.snapshot_source == 'persisted'
        provider_name = type(self.image_provider).__name__
        provider_model = getattr(self.image_provider, 'model', None)
        decision_event = {
            'conversation_supported': conversation_supported,
            'conversation_fallback_allowed': conversation_fallback_allowed,
            'snapshot_present': snapshot_present,
            'degraded_context': context.degraded_context,
            'provider': provider_name,
            'model': provider_model,
        }
        log_restyle_edit_event('restyle_edit_provider_decision', trace, decision_event)
        maybe_write_debug_artifact(
            config,
            event_name='provider_decision',
            trace=trace,
            payload=decision_event,
            degraded_context=context.degraded_context,
        )
        
        if conversation_supported:
            conversation_attempted = True
            conversation_request_event = {
                'context_mode': 'restyle_conversation',
                'turns_summary': context.turns_summary,
                'snapshot_source': context.snapshot_source,
                'image_manifest': enrich_image_manifest(context.image_manifest),
                'conversation_contents': serialize_conversation_contents(context.conversation_contents),
            }
            log_restyle_edit_event('restyle_edit_provider_request', trace, {
                'context_mode': 'restyle_conversation',
                'turns_summary': context.turns_summary,
                'snapshot_source': context.snapshot_source,
            })
            maybe_write_debug_artifact(
                config,
                event_name='provider_request',
                trace=trace,
                payload=conversation_request_event,
                degraded_context=context.degraded_context,
            )
            try:
                resolved_contents = self._resolve_conversation_images(context.conversation_contents)
                result = self.image_provider.generate_image_from_conversation(
                    contents=resolved_contents,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    thinking_level=self._get_image_thinking_level()
                )
                if result:
                    result_event = {
                        'context_mode': 'restyle_conversation',
                        'conversation_attempted': True,
                        'provider_fallback': False,
                        'degraded_context': context.degraded_context,
                        'baseline_images_count': context.baseline_images_count,
                        'current_images_count': context.current_images_count,
                        'snapshot_present': snapshot_present,
                        'provider': provider_name,
                        'model': provider_model,
                    }
                    log_restyle_edit_event('restyle_edit_provider_result', trace, result_event)
                    maybe_write_debug_artifact(
                        config,
                        event_name='provider_result',
                        trace=trace,
                        payload=result_event,
                        degraded_context=context.degraded_context,
                    )
                    return result
            except Exception as e:
                classified_retryable = is_retryable_conversation_error(e)
                if classified_retryable and conversation_fallback_allowed:
                    logger.warning(f"Conversation mode failed with retryable error, falling back to legacy: {e}")
                    provider_fallback = True
                    fallback_event = {
                        'from_mode': 'restyle_conversation',
                        'to_mode': 'legacy_flattened',
                        'provider_fallback': True,
                        'classified_retryable': classified_retryable,
                        'conversation_fallback_allowed': conversation_fallback_allowed,
                        'error_message': str(e),
                        'provider': provider_name,
                        'model': provider_model,
                    }
                    log_restyle_edit_event('restyle_edit_provider_fallback', trace, fallback_event)
                    maybe_write_debug_artifact(
                        config,
                        event_name='provider_fallback',
                        trace=trace,
                        payload=fallback_event,
                        provider_fallback=True,
                        error=True,
                    )
                else:
                    error_event = {
                        'context_mode': 'restyle_conversation',
                        'provider_fallback': False,
                        'classified_retryable': classified_retryable,
                        'conversation_fallback_allowed': conversation_fallback_allowed,
                        'error_message': str(e),
                        'provider': provider_name,
                        'model': provider_model,
                    }
                    log_restyle_edit_event('restyle_edit_provider_result', trace, error_event)
                    maybe_write_debug_artifact(
                        config,
                        event_name='provider_result',
                        trace=trace,
                        payload=error_event,
                        error=True,
                    )
                    raise
        
        # Legacy fallback path
        legacy_request_event = {
            'context_mode': 'legacy_flattened',
            'conversation_attempted': conversation_attempted,
            'provider_fallback': provider_fallback,
            'snapshot_source': context.snapshot_source,
            'prompt': context.legacy_prompt,
            'prompt_len': len(context.legacy_prompt),
            'legacy_ref_images': context.legacy_ref_images,
            'image_manifest': enrich_image_manifest(context.image_manifest),
        }
        log_restyle_edit_event('restyle_edit_provider_request', trace, {
            'context_mode': 'legacy_flattened',
            'conversation_attempted': conversation_attempted,
            'provider_fallback': provider_fallback,
            'prompt_len': len(context.legacy_prompt),
            'ref_image_count': len(context.legacy_ref_images),
        })
        maybe_write_debug_artifact(
            config,
            event_name='provider_request',
            trace=trace,
            payload=legacy_request_event,
            degraded_context=context.degraded_context,
            provider_fallback=provider_fallback,
        )
        ref_images = self._resolve_ref_image_paths(context.legacy_ref_images)
        result = self.image_provider.generate_image(
            prompt=context.legacy_prompt,
            ref_images=ref_images if ref_images else None,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            thinking_level=self._get_image_thinking_level()
        )

        result_event = {
            'context_mode': 'legacy_flattened',
            'conversation_attempted': conversation_attempted,
            'provider_fallback': provider_fallback,
            'degraded_context': context.degraded_context,
            'baseline_images_count': context.baseline_images_count,
            'current_images_count': context.current_images_count,
            'snapshot_present': snapshot_present,
            'provider': provider_name,
            'model': provider_model,
        }
        log_restyle_edit_event('restyle_edit_provider_result', trace, result_event)
        maybe_write_debug_artifact(
            config,
            event_name='provider_result',
            trace=trace,
            payload=result_event,
            degraded_context=context.degraded_context,
            provider_fallback=provider_fallback,
        )
        
        return result
    
    def _resolve_conversation_images(self, contents):
        """Resolve image_path entries in conversation contents to PIL Images for Gemini."""
        resolved = []
        for turn in contents:
            new_parts = []
            for part in turn['parts']:
                if 'image_path' in part:
                    path = part['image_path']
                    if os.path.exists(path):
                        img = Image.open(path)
                        img.load()
                        new_parts.append(img)
                    else:
                        logger.warning(f"Image not found, skipping: {path}")
                elif 'text' in part:
                    new_parts.append(part['text'])
                else:
                    new_parts.append(part)
            resolved.append({'role': turn['role'], 'parts': new_parts})
        return resolved
    
    def _resolve_ref_image_paths(self, image_paths):
        """Resolve image path strings to PIL Image objects for legacy mode."""
        images = []
        for path in image_paths:
            if os.path.exists(path):
                img = Image.open(path)
                img.load()
                images.append(img)
            else:
                logger.warning(f"Legacy ref image not found, skipping: {path}")
        return images
    
    def parse_description_to_outline(self, project_context: ProjectContext, language='zh') -> List[Dict]:
        """
        从描述文本解析出大纲结构
        
        Args:
            project_context: 项目上下文对象，包含所有原始信息
        
        Returns:
            List of outline items (may contain parts with pages or direct pages)
        """
        parse_prompt = get_description_to_outline_prompt(project_context, language)
        outline = self.generate_json(parse_prompt, thinking_budget=1000)
        return outline
    
    def parse_description_to_page_descriptions(self, project_context: ProjectContext, 
                                               outline: List[Dict],
                                               language='zh') -> List[str]:
        """
        从描述文本切分出每页描述
        
        Args:
            project_context: 项目上下文对象，包含所有原始信息
            outline: 已解析出的大纲结构
        
        Returns:
            List of page descriptions (strings), one for each page in the outline
        """
        split_prompt = get_description_split_prompt(project_context, outline, language)
        descriptions = self.generate_json(split_prompt, thinking_budget=1000)
        
        # 确保返回的是字符串列表
        if isinstance(descriptions, list):
            return [str(desc) for desc in descriptions]
        else:
            raise ValueError("Expected a list of page descriptions, but got: " + str(type(descriptions)))
    
    def refine_outline(self, current_outline: List[Dict], user_requirement: str,
                      project_context: ProjectContext,
                      previous_requirements: Optional[List[str]] = None,
                      language='zh') -> List[Dict]:
        """
        根据用户要求修改已有大纲
        
        Args:
            current_outline: 当前的大纲结构
            user_requirement: 用户的新要求
            project_context: 项目上下文对象，包含所有原始信息
            previous_requirements: 之前的修改要求列表（可选）
        
        Returns:
            修改后的大纲结构
        """
        refinement_prompt = get_outline_refinement_prompt(
            current_outline=current_outline,
            user_requirement=user_requirement,
            project_context=project_context,
            previous_requirements=previous_requirements,
            language=language
        )
        outline = self.generate_json(refinement_prompt, thinking_budget=1000)
        return outline
    
    def refine_descriptions(self, current_descriptions: List[Dict], user_requirement: str,
                           project_context: ProjectContext,
                           outline: List[Dict] = None,
                           previous_requirements: Optional[List[str]] = None,
                           language='zh') -> List[str]:
        """
        根据用户要求修改已有页面描述
        
        Args:
            current_descriptions: 当前的页面描述列表，每个元素包含 {index, title, description_content}
            user_requirement: 用户的新要求
            project_context: 项目上下文对象，包含所有原始信息
            outline: 完整的大纲结构（可选）
            previous_requirements: 之前的修改要求列表（可选）
        
        Returns:
            修改后的页面描述列表（字符串列表）
        """
        refinement_prompt = get_descriptions_refinement_prompt(
            current_descriptions=current_descriptions,
            user_requirement=user_requirement,
            project_context=project_context,
            outline=outline,
            previous_requirements=previous_requirements,
            language=language
        )
        descriptions = self.generate_json(refinement_prompt, thinking_budget=1000)
        
        # 确保返回的是字符串列表
        if isinstance(descriptions, list):
            return [str(desc) for desc in descriptions]
        else:
            raise ValueError("Expected a list of page descriptions, but got: " + str(type(descriptions)))
