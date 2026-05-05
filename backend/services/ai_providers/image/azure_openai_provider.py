"""Azure OpenAI GPT-image provider."""
import base64
import logging
from io import BytesIO
from typing import List, Optional

import requests
from PIL import Image

from .base import ImageProvider
from config import get_config

logger = logging.getLogger(__name__)


class AzureOpenAIImageProvider(ImageProvider):
    """Image generation/editing using Azure OpenAI Images APIs."""

    supports_conversation_contents = False

    def __init__(
        self,
        api_key: str,
        endpoint: str = None,
        deployment: str = "gpt-image-2",
        api_version: str = "preview",
        image_generation_url: str = None,
        image_edit_url: str = None,
        quality: str = "high",
        output_format: str = "png",
    ):
        self.api_key = api_key
        self.endpoint = (endpoint or "").rstrip('/')
        self.model = deployment
        self.api_version = api_version
        self.image_generation_url = image_generation_url
        self.image_edit_url = image_edit_url
        self.quality = quality
        self.output_format = output_format
        self.timeout = get_config().OPENAI_TIMEOUT

        if not self.api_key:
            raise ValueError("AZURE_OPENAI_API_KEY is required for Azure OpenAI image generation")
        if not self.endpoint and not self.image_generation_url:
            raise ValueError("AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_IMAGE_GENERATION_URL is required")

    def _generation_url(self) -> str:
        if self.image_generation_url:
            return self.image_generation_url
        return f"{self.endpoint}/openai/v1/images/generations?api-version={self.api_version}"

    def _edit_url(self) -> str:
        if self.image_edit_url:
            return self.image_edit_url
        generation_url = self._generation_url()
        if '/images/generations' in generation_url:
            return generation_url.replace('/images/generations', '/images/edits')
        return f"{self.endpoint}/openai/v1/images/edits?api-version={self.api_version}"

    @staticmethod
    def _image_to_png_file(image: Image.Image, name: str):
        buffer = BytesIO()
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA')
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return ('image[]', (name, buffer.getvalue(), 'image/png'))

    @staticmethod
    def _decode_response_image(payload: dict) -> Image.Image:
        try:
            image_base64 = payload['data'][0]['b64_json']
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Azure OpenAI image response did not contain data[0].b64_json: {payload}") from exc

        image_data = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_data))
        image.load()
        return image

    @staticmethod
    def _resolve_size(aspect_ratio: str, resolution: str) -> str:
        """Map project aspect/resolution knobs to GPT-image-2-compatible sizes."""
        ratio = (aspect_ratio or '16:9').strip()
        res = (resolution or '2K').strip().upper()

        sizes = {
            '16:9': {'1K': '1280x720', '2K': '1920x1088', '4K': '3840x2160'},
            '9:16': {'1K': '720x1280', '2K': '1088x1920', '4K': '2160x3840'},
            '4:3': {'1K': '1024x768', '2K': '1600x1200', '4K': '3200x2400'},
            '3:4': {'1K': '768x1024', '2K': '1200x1600', '4K': '2400x3200'},
            '1:1': {'1K': '1024x1024', '2K': '2048x2048', '4K': '2880x2880'},
        }

        return sizes.get(ratio, sizes['16:9']).get(res, sizes.get(ratio, sizes['16:9'])['2K'])

    def _request_headers(self) -> dict:
        return {'api-key': self.api_key}

    def _base_payload(self, prompt: str, aspect_ratio: str, resolution: str) -> dict:
        return {
            'model': self.model,
            'prompt': prompt,
            'n': 1,
            'size': self._resolve_size(aspect_ratio, resolution),
            'quality': self.quality,
            'output_format': self.output_format,
        }

    def generate_image(
        self,
        prompt: str,
        ref_images: Optional[List[Image.Image]] = None,
        aspect_ratio: str = "16:9",
        resolution: str = "2K",
        thinking_level: str = "none",
    ) -> Optional[Image.Image]:
        """Generate or edit an image through Azure OpenAI GPT-image APIs."""
        try:
            ref_count = len(ref_images) if ref_images else 0
            logger.info(
                "🌐 Azure OpenAI image request: deployment=%s, refs=%s, aspect_ratio=%s, resolution=%s",
                self.model,
                ref_count,
                aspect_ratio,
                resolution,
            )

            payload = self._base_payload(prompt, aspect_ratio, resolution)
            headers = self._request_headers()

            if ref_images:
                target_url = self._edit_url()
                if '/deployments/' in target_url:
                    payload.pop('model', None)
                files = [self._image_to_png_file(image, f'reference_{idx}.png') for idx, image in enumerate(ref_images, start=1)]
                response = requests.post(
                    target_url,
                    headers=headers,
                    data={key: str(value) for key, value in payload.items()},
                    files=files,
                    timeout=self.timeout,
                )
            else:
                target_url = self._generation_url()
                if '/deployments/' in target_url:
                    payload.pop('model', None)
                headers = {**headers, 'Content-Type': 'application/json'}
                response = requests.post(
                    target_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )

            response.raise_for_status()
            return self._decode_response_image(response.json())

        except Exception as e:
            error_detail = f"Error generating image with Azure OpenAI (deployment={self.model}): {type(e).__name__}: {str(e)}"
            logger.error(error_detail, exc_info=True)
            raise Exception(error_detail) from e
