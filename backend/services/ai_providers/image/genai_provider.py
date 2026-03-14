"""
Google GenAI SDK implementation for image generation

Supports two modes:
- Google AI Studio: Uses API key authentication
- Vertex AI: Uses GCP service account authentication
"""
import logging
from typing import Optional, List
from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import ImageProvider
from config import get_config

logger = logging.getLogger(__name__)


class GenAIImageProvider(ImageProvider):
    """Image generation using Google GenAI SDK (supports both AI Studio and Vertex AI)"""

    def __init__(
        self,
        api_key: str = None,
        api_base: str = None,
        model: str = "gemini-3-pro-image-preview",
        vertexai: bool = False,
        project_id: str = None,
        location: str = None
    ):
        """
        Initialize GenAI image provider

        Args:
            api_key: Google API key (for AI Studio mode)
            api_base: API base URL (for proxies like aihubmix, AI Studio mode only)
            model: Model name to use
            vertexai: If True, use Vertex AI instead of AI Studio
            project_id: GCP project ID (required for Vertex AI mode)
            location: GCP region (for Vertex AI mode, default: us-central1)
        """
        timeout_ms = int(get_config().GENAI_TIMEOUT * 1000)

        if vertexai:
            # Vertex AI mode - uses service account credentials from GOOGLE_APPLICATION_CREDENTIALS
            logger.info(f"Initializing GenAI image provider in Vertex AI mode, project: {project_id}, location: {location}")
            self.client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location or 'us-central1',
                http_options=types.HttpOptions(timeout=timeout_ms)
            )
        else:
            # AI Studio mode - uses API key
            http_options = types.HttpOptions(
                base_url=api_base,
                timeout=timeout_ms
            ) if api_base else types.HttpOptions(timeout=timeout_ms)

            self.client = genai.Client(
                http_options=http_options,
                api_key=api_key
            )

        self.model = model

    @retry(
        stop=stop_after_attempt(get_config().GENAI_MAX_RETRIES + 1),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def generate_image(
        self,
        prompt: str,
        ref_images: Optional[List[Image.Image]] = None,
        aspect_ratio: str = "16:9",
        resolution: str = "2K",
        thinking_level: str = "none"
    ) -> Optional[Image.Image]:
        """
        Generate image using Google GenAI SDK
        
        Args:
            prompt: The image generation prompt
            ref_images: Optional list of reference images
            aspect_ratio: Image aspect ratio
            resolution: Image resolution (supports "1K", "2K", "4K")
            thinking_level: Thinking level for Gemini 3 ("none", "minimal", "high")
            
        Returns:
            Generated PIL Image object, or None if failed
        """
        try:
            # Build contents list: prompt FIRST, then reference images
            # This order significantly improves instruction-following for Gemini
            # (validated against compose_images.py pattern from gemini-imagegen skill)
            contents = [prompt]
            
            # Add reference images after prompt
            if ref_images:
                for ref_img in ref_images:
                    contents.append(ref_img)
            
            ref_count = len(ref_images) if ref_images else 0
            ref_details = ", ".join(f"{img.size[0]}x{img.size[1]}" for img in ref_images) if ref_images else "none"
            prompt_preview = prompt[:200] + "..." if len(prompt) > 200 else prompt
            logger.info(f"🌐 GenAI image request: model={self.model}, "
                        f"ref_images={ref_count} [{ref_details}], "
                        f"aspect_ratio={aspect_ratio}, resolution={resolution}, thinking_level={thinking_level}")
            logger.info(f"📝 Prompt ({len(prompt)} chars): {prompt_preview}")
            
            # Build config
            config_params = {
                'response_modalities': ['TEXT', 'IMAGE'],
                'image_config': types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                    image_size=resolution
                )
            }
            
            # Add thinking config if a valid level is specified
            # Gemini 3.1 Flash Image only supports "minimal" (default) and "high"
            # See: https://ai.google.dev/gemini-api/docs/image-generation#thinking-process
            level_map = {
                'minimal': 'MINIMAL',
                'high': 'HIGH',
            }
            if thinking_level.lower() in level_map:
                config_params['thinking_config'] = types.ThinkingConfig(
                    thinking_level=level_map[thinking_level.lower()],
                    include_thoughts=True
                )
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config_params)
            )
            
            total_parts = len(response.parts) if response.parts else 0
            logger.info(f"📨 GenAI response: {total_parts} parts")
            
            # Extract the final image from the response.
            # Earlier images are usually low resolution drafts 
            # Therefore, always use the last image found.
            last_image = None
            image_count = 0
            
            for i, part in enumerate(response.parts):
                if part.text is not None:
                    text_preview = part.text[:150] + "..." if len(part.text) > 150 else part.text
                    part_label = "💭 Thought" if getattr(part, 'thought', False) else "💬 Text"
                    logger.info(f"  Part {i}: {part_label} - {text_preview}")
                else:
                    try:
                        image = part.as_image()
                        if image:
                            # as_image() should return PIL Image directly (official SDK)
                            # But proxy may return custom Image object, so we need fallbacks
                            if isinstance(image, Image.Image):
                                last_image = image
                            elif hasattr(image, 'image_bytes') and image.image_bytes:
                                last_image = Image.open(BytesIO(image.image_bytes))
                            elif hasattr(image, '_pil_image') and image._pil_image:
                                last_image = image._pil_image
                            else:
                                logger.warning(f"  Part {i}: ⚠️ Image object type {type(image)} has no usable conversion method")
                                continue
                            image_count += 1
                            logger.info(f"  Part {i}: 🖼️ Image {image_count} extracted ({last_image.size[0]}x{last_image.size[1]})")
                    except Exception as e:
                        logger.warning(f"  Part {i}: ⚠️ Failed to extract image - {type(e).__name__}: {str(e)}")
            
            # Return the last image found (highest quality in thinking chain scenarios)
            if last_image:
                logger.info(f"✅ Final image selected: image {image_count}/{image_count} ({last_image.size[0]}x{last_image.size[1]})")
                return last_image
            
            # No image found in response
            error_msg = "No image found in API response. "
            if response.parts:
                error_msg += f"Response had {len(response.parts)} parts but none contained valid images."
            else:
                error_msg += "Response had no parts."
            
            raise ValueError(error_msg)
            
        except Exception as e:
            error_detail = f"Error generating image with GenAI: {type(e).__name__}: {str(e)}"
            logger.error(error_detail, exc_info=True)
            raise Exception(error_detail) from e
