"""Azure OpenAI Responses API GPT-image provider."""
import base64
import logging
import time
from io import BytesIO
from typing import List, Optional
from urllib.parse import urlparse

import requests
from PIL import Image

from .base import ImageProvider
from config import get_config

logger = logging.getLogger(__name__)


class AzureOpenAIImageProvider(ImageProvider):
    """Image generation/editing using Azure OpenAI Responses API."""

    supports_conversation_contents = True
    # Azure restyle should use structured multi-turn request input. Do not
    # silently fall back to flattened context on schema errors; fail loudly.
    allow_conversation_fallback = False

    def __init__(
        self,
        api_key: str,
        responses_url: str = None,
        endpoint: str = None,
        responses_model: str = "gpt-5.4",
        image_deployment: str = "gpt-image-2",
        api_version: str = "2025-04-01-preview",
        quality: str = "high",
        output_format: str = "png",
        max_retries: int = None,
        timeout: float = None,
    ):
        self.api_key = (api_key or "").strip()
        self.endpoint = (endpoint or "").strip().rstrip('/')
        self.api_version = api_version
        self.responses_url = (responses_url or self._build_responses_url()).strip()
        self.responses_model = responses_model or "gpt-5.4"
        self.image_deployment = image_deployment or "gpt-image-2"
        # Existing debug artifacts read `model` from providers.
        self.model = self.image_deployment
        self.quality = quality
        self.output_format = output_format
        config = get_config()
        self.timeout = timeout if timeout is not None else config.OPENAI_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else config.OPENAI_MAX_RETRIES

        if not self.api_key:
            raise ValueError("AZURE_OPENAI_API_KEY is required for Azure OpenAI Responses image generation")
        if not self.responses_url:
            raise ValueError("AZURE_OPENAI_RESPONSES_URL or AZURE_OPENAI_ENDPOINT is required")

    def _build_responses_url(self) -> str:
        if not self.endpoint:
            return ""
        return f"{self.endpoint}/openai/responses?api-version={self.api_version}"

    @staticmethod
    def _image_to_data_url(image: Image.Image) -> str:
        buffer = BytesIO()
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA')
        image.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def _decode_response_image(payload: dict) -> Image.Image:
        for output in payload.get('output') or []:
            if output.get('type') == 'image_generation_call' and output.get('result'):
                image_data = base64.b64decode(output['result'])
                image = Image.open(BytesIO(image_data))
                image.load()
                return image

        output_summary = [
            {
                'type': output.get('type'),
                'status': output.get('status'),
                'action': output.get('action'),
                'has_result': bool(output.get('result')),
            }
            for output in (payload.get('output') or [])
        ]
        raise ValueError(
            "Azure OpenAI Responses image response did not contain "
            f"output[].result: status={payload.get('status')}, "
            f"error={payload.get('error')}, output={output_summary}"
        )

    @staticmethod
    def _resolve_size(aspect_ratio: str, resolution: str) -> str:
        """Map project aspect/resolution knobs to Azure Responses-supported sizes."""
        ratio = (aspect_ratio or '16:9').strip()
        if ratio == '1:1':
            return '1024x1024'
        if ratio in {'9:16', '3:4'}:
            return '1024x1536'
        return '1536x1024'

    def _request_headers(self) -> dict:
        headers = {
            'Content-Type': 'application/json',
            'x-ms-oai-image-generation-deployment': self.image_deployment,
        }
        if self._uses_azure_api_key_header():
            headers['api-key'] = self.api_key
        else:
            headers['Authorization'] = f"Bearer {self.api_key}"
        return headers

    def _uses_azure_api_key_header(self) -> bool:
        path = f"{urlparse(self.responses_url).path.rstrip('/')}/".lower()
        return '/openai/' in path

    def _image_tool(self, action: str, aspect_ratio: str, resolution: str) -> dict:
        tool = {
            'type': 'image_generation',
            'action': action,
            'quality': self.quality,
            'size': self._resolve_size(aspect_ratio, resolution),
        }
        if self.output_format:
            tool['output_format'] = self.output_format
        return tool

    def _build_payload(self, prompt: str, ref_images: Optional[List[Image.Image]], aspect_ratio: str, resolution: str) -> dict:
        if ref_images:
            content = [{'type': 'input_text', 'text': prompt}]
            content.extend({'type': 'input_image', 'image_url': self._image_to_data_url(image)} for image in ref_images)
            input_payload = [{'role': 'user', 'content': content}]
            action = 'edit'
        else:
            input_payload = prompt
            action = 'generate'

        return {
            'model': self.responses_model,
            'input': input_payload,
            'tools': [self._image_tool(action, aspect_ratio, resolution)],
        }

    def _conversation_part_to_responses_content(self, part) -> dict:
        if isinstance(part, str):
            return {'type': 'input_text', 'text': part}
        if isinstance(part, Image.Image):
            return {'type': 'input_image', 'image_url': self._image_to_data_url(part)}
        if isinstance(part, dict):
            if 'text' in part:
                return {'type': 'input_text', 'text': part['text']}
            if 'image' in part and isinstance(part['image'], Image.Image):
                return {'type': 'input_image', 'image_url': self._image_to_data_url(part['image'])}
            if 'image_url' in part:
                return {'type': 'input_image', 'image_url': part['image_url']}

        raise ValueError(f"Unsupported conversation part type for Azure Responses: {type(part)}")

    def _conversation_turn_to_responses_message(self, turn: dict) -> dict:
        role = turn.get('role', 'user')
        if role == 'model':
            role = 'assistant'
        if role not in {'user', 'assistant', 'system', 'developer'}:
            role = 'user'
        return {
            'role': role,
            'content': [
                self._conversation_part_to_responses_content(part)
                for part in turn.get('parts', [])
            ],
        }

    def _build_conversation_payload(self, contents: list, aspect_ratio: str, resolution: str) -> dict:
        return {
            'model': self.responses_model,
            'input': [self._conversation_turn_to_responses_message(turn) for turn in contents],
            'tools': [self._image_tool('edit', aspect_ratio, resolution)],
        }

    @staticmethod
    def _response_error_message(response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        error = payload.get('error') if isinstance(payload, dict) else None
        if isinstance(error, dict):
            return str(error.get('message') or error)
        return str(error or payload)[:500]

    def _is_retryable_response(self, response) -> bool:
        if response.status_code in {429, 500, 502, 503, 504}:
            return True
        if response.status_code == 400:
            message = self._response_error_message(response).lower()
            return 'engine is overloaded' in message or 'overloaded' in message
        return False

    def _post_responses(self, payload: dict) -> dict:
        headers = self._request_headers()
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    self.responses_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    if attempt < self.max_retries and self._is_retryable_response(response):
                        wait_seconds = min(2 ** attempt, 8)
                        logger.warning(
                            "Azure OpenAI Responses image request retryable failure "
                            "(attempt %s/%s): status=%s, error=%s",
                            attempt + 1,
                            self.max_retries + 1,
                            response.status_code,
                            self._response_error_message(response),
                        )
                        time.sleep(wait_seconds)
                        continue
                    try:
                        response.raise_for_status()
                    except requests.HTTPError as exc:
                        message = self._response_error_message(response)
                        raise requests.HTTPError(f"{exc}; Azure error: {message}", response=response) from exc
                return response.json()
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    wait_seconds = min(2 ** attempt, 8)
                    logger.warning(
                        "Azure OpenAI Responses image request transport failure "
                        "(attempt %s/%s): %s",
                        attempt + 1,
                        self.max_retries + 1,
                        exc,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise

        raise RuntimeError("Azure OpenAI Responses image request retry loop exhausted")

    def generate_image(
        self,
        prompt: str,
        ref_images: Optional[List[Image.Image]] = None,
        aspect_ratio: str = "16:9",
        resolution: str = "2K",
        thinking_level: str = "none",
    ) -> Optional[Image.Image]:
        """Generate or edit an image through Azure OpenAI Responses API."""
        try:
            ref_count = len(ref_images) if ref_images else 0
            logger.info(
                "🌐 Azure OpenAI Responses image request: responses_model=%s, image_deployment=%s, refs=%s, aspect_ratio=%s, resolution=%s",
                self.responses_model,
                self.image_deployment,
                ref_count,
                aspect_ratio,
                resolution,
            )

            payload = self._build_payload(prompt, ref_images, aspect_ratio, resolution)
            response_payload = self._post_responses(payload)
            return self._decode_response_image(response_payload)

        except Exception as e:
            error_detail = (
                "Error generating image with Azure OpenAI Responses "
                f"(responses_model={self.responses_model}, image_deployment={self.image_deployment}): "
                f"{type(e).__name__}: {str(e)}"
            )
            logger.error(error_detail, exc_info=True)
            raise Exception(error_detail) from e

    def generate_image_from_conversation(
        self,
        contents: list,
        aspect_ratio: str = "16:9",
        resolution: str = "2K",
        thinking_level: str = "none",
    ) -> Optional[Image.Image]:
        """Generate/edit using a structured multi-turn Responses request."""
        try:
            logger.info(
                "🌐 Azure OpenAI Responses conversation image request: responses_model=%s, image_deployment=%s, turns=%s, aspect_ratio=%s, resolution=%s",
                self.responses_model,
                self.image_deployment,
                len(contents),
                aspect_ratio,
                resolution,
            )

            payload = self._build_conversation_payload(contents, aspect_ratio, resolution)
            response_payload = self._post_responses(payload)
            return self._decode_response_image(response_payload)

        except Exception as e:
            error_detail = (
                "Error generating image with Azure OpenAI Responses conversation "
                f"(responses_model={self.responses_model}, image_deployment={self.image_deployment}): "
                f"{type(e).__name__}: {str(e)}"
            )
            logger.error(error_detail, exc_info=True)
            raise Exception(error_detail) from e
