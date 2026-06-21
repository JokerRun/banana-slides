"""OpenAI SDK implementation for image generation backends."""
import base64
import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, List, Optional

import requests
from openai import OpenAI
from PIL import Image

from .base import ImageProvider
from config import get_config

logger = logging.getLogger(__name__)

ClientFactory = Callable[..., Any]

_CHATGPT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


def _normalize_azure_base_url(value: str) -> str:
    base_url = (value or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("OPENAI_API_BASE is required when OPENAI_IMAGE_BACKEND=azure")
    if base_url.endswith("/openai/v1"):
        return base_url
    return f"{base_url}/openai/v1"


def _load_chatgpt_auth(path: str) -> tuple[str, Optional[str]]:
    auth_path = Path(path).expanduser()
    data = json.loads(auth_path.read_text(encoding="utf-8"))
    tokens = data.get("tokens") or {}
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("auth.json does not contain tokens.access_token")
    return access_token, account_id if isinstance(account_id, str) else None


def _walk_image_generation_items(value: Any) -> list[dict]:
    """Recursively find Responses API image_generation_call outputs."""
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump()
        except Exception:
            pass

    items = []
    if isinstance(value, dict):
        if value.get("type") == "image_generation_call" and isinstance(value.get("result"), str):
            items.append({"type": "image_generation_call", "result": value["result"]})
        for child in value.values():
            items.extend(_walk_image_generation_items(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(_walk_image_generation_items(child))
    else:
        kind = getattr(value, "type", None)
        result = getattr(value, "result", None)
        if kind == "image_generation_call" and isinstance(result, str):
            items.append({"type": "image_generation_call", "result": result})
    return items


class OpenAIImageProvider(ImageProvider):
    """Image generation using the OpenAI SDK.

    Backends:
    - proxy: OpenAI-compatible Responses API image path by default.
    - azure: OpenAI SDK Responses API with Azure headers/query.
    - chatgpt: OpenAI SDK Responses API using local Codex auth.json.
    """

    supports_conversation_contents = False
    allow_conversation_fallback = True

    def __init__(
        self,
        api_key: str,
        api_base: str = None,
        model: str = "gemini-3-pro-image-preview",
        backend: str = "proxy",
        responses_model: str = None,
        image_model: str = None,
        image_deployment: str = None,
        api_version: str = "preview",
        quality: str = "high",
        output_format: str = "png",
        auth_json: str = None,
        mode: str = None,
        openai_client_factory: ClientFactory = None,
    ):
        config = get_config()
        self.api_key = (api_key or "").strip()
        self.api_base = (api_base or "").strip()
        self.backend = (backend or "proxy").strip().lower()
        self.responses_model = responses_model
        self.image_model = image_model or model
        self.image_deployment = image_deployment or self.image_model
        self.api_version = api_version or "preview"
        self.quality = quality or "high"
        self.output_format = output_format or "png"
        self.auth_json = auth_json
        self.timeout = config.OPENAI_TIMEOUT
        self.max_retries = config.OPENAI_MAX_RETRIES
        self.mode = (mode or "responses").strip().lower()
        if self.backend not in {"proxy", "azure", "chatgpt"}:
            raise ValueError("OPENAI_IMAGE_BACKEND must be proxy, azure, or chatgpt")
        if self.mode not in {"responses", "chat"}:
            raise ValueError("OPENAI_IMAGE_MODE must be responses or chat")
        if self.mode == "chat" and self.backend != "proxy":
            raise ValueError("OPENAI_IMAGE_MODE=chat is only supported when OPENAI_IMAGE_BACKEND=proxy")
        if self.mode == "responses" and not self.responses_model:
            raise ValueError("OPENAI_RESPONSES_MODEL is required for Responses image generation")
        self.supports_conversation_contents = self.mode == "responses"
        self.allow_conversation_fallback = self.backend != "azure"
        # Existing debug artifacts read `model` from providers.
        self.model = self.image_deployment if self.mode == "responses" else model
        self._openai_client_factory = openai_client_factory
        self.client = self._build_client()

    def _build_client(self):
        kwargs = self._client_kwargs()
        if self._openai_client_factory is not None:
            return self._openai_client_factory(**kwargs)
        return OpenAI(**kwargs)

    def _client_kwargs(self) -> dict:
        common = {
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }
        if self.backend == "azure":
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY is required when OPENAI_IMAGE_BACKEND=azure")
            headers = {"api_version": self.api_version}
            if self.image_deployment:
                headers["x-ms-oai-image-generation-deployment"] = self.image_deployment
            return {
                **common,
                "api_key": self.api_key,
                "base_url": _normalize_azure_base_url(self.api_base),
                "default_headers": headers,
            }
        if self.backend == "chatgpt":
            access_token = self.api_key
            account_id = None
            if not access_token and self.auth_json:
                access_token, account_id = _load_chatgpt_auth(self.auth_json)
            if not access_token:
                raise ValueError("OPENAI_API_KEY or OPENAI_AUTH_JSON is required when OPENAI_IMAGE_BACKEND=chatgpt")
            kwargs = {
                **common,
                "api_key": access_token,
                "base_url": _CHATGPT_CODEX_BASE_URL,
            }
            if account_id:
                kwargs["default_headers"] = {"ChatGPT-Account-ID": account_id}
            return kwargs

        return {
            **common,
            "api_key": self.api_key,
            "base_url": self.api_base or None,
        }

    @staticmethod
    def _image_to_data_url(image: Image.Image) -> str:
        buffer = BytesIO()
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA')
        image.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def _encode_image_to_base64(image: Image.Image) -> str:
        buffered = BytesIO()
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        image.save(buffered, format="JPEG", quality=95)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

    @staticmethod
    def _resolve_size(aspect_ratio: str, resolution: str) -> str:
        ratio = (aspect_ratio or '16:9').strip()
        if ratio == '1:1':
            return '1024x1024'
        if ratio in {'9:16', '3:4'}:
            return '1024x1536'
        return 'auto'

    def _build_extra_body(self, aspect_ratio: str, resolution: str) -> dict:
        resolution_upper = resolution.upper()
        return {
            "aspect_ratio": aspect_ratio,
            "resolution": resolution_upper,
            "generationConfig": {
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": resolution_upper,
                }
            }
        }

    def _image_tool(self, aspect_ratio: str, resolution: str) -> dict:
        tool = {
            "type": "image_generation",
            "model": self.image_model,
            "quality": self.quality,
            "size": self._resolve_size(aspect_ratio, resolution),
        }
        if self.output_format:
            tool["output_format"] = self.output_format
        return tool

    def _responses_kwargs(self, input_payload, aspect_ratio: str, resolution: str) -> dict:
        kwargs = {
            "model": self.responses_model,
            "input": input_payload,
            "tools": [self._image_tool(aspect_ratio, resolution)],
            "tool_choice": {"type": "image_generation"},
            "parallel_tool_calls": True,
            "store": False,
        }
        return kwargs

    def _decode_response_image(self, response) -> Image.Image:
        output = getattr(response, "output", None)
        if output is None and isinstance(response, dict):
            output = response.get("output")
        image_items = _walk_image_generation_items(output or response)
        if image_items:
            image_data = base64.b64decode(image_items[0]["result"])
            image = Image.open(BytesIO(image_data))
            image.load()
            return image
        raise ValueError("OpenAI Responses image response did not contain image_generation_call.result")

    def _build_responses_input(self, prompt: str, ref_images: Optional[List[Image.Image]]):
        if not ref_images:
            return prompt
        content = [{'type': 'input_text', 'text': prompt}]
        content.extend({'type': 'input_image', 'image_url': self._image_to_data_url(image)} for image in ref_images)
        return [{'role': 'user', 'content': content}]

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
        raise ValueError(f"Unsupported conversation part type for OpenAI Responses: {type(part)}")

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

    def generate_image(
        self,
        prompt: str,
        ref_images: Optional[List[Image.Image]] = None,
        aspect_ratio: str = "16:9",
        resolution: str = "2K",
        thinking_level: str = "none"
    ) -> Optional[Image.Image]:
        if self.mode == "responses":
            return self._generate_image_responses(prompt, ref_images, aspect_ratio, resolution)
        return self._generate_image_chat(prompt, ref_images, aspect_ratio, resolution)

    def _generate_image_responses(
        self,
        prompt: str,
        ref_images: Optional[List[Image.Image]],
        aspect_ratio: str,
        resolution: str,
    ) -> Optional[Image.Image]:
        try:
            logger.info(
                "🌐 OpenAI Responses image request: backend=%s, responses_model=%s, image_model=%s, refs=%s, aspect_ratio=%s, resolution=%s",
                self.backend,
                self.responses_model,
                self.image_model,
                len(ref_images) if ref_images else 0,
                aspect_ratio,
                resolution,
            )
            input_payload = self._build_responses_input(prompt, ref_images)
            response = self.client.responses.create(**self._responses_kwargs(input_payload, aspect_ratio, resolution))
            return self._decode_response_image(response)
        except Exception as e:
            error_detail = (
                f"Error generating image with OpenAI Responses (backend={self.backend}, "
                f"model={self.responses_model}, image_model={self.image_model}): "
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
        if self.mode != "responses":
            raise NotImplementedError("Conversation contents not supported by this OpenAI backend")
        try:
            input_payload = [self._conversation_turn_to_responses_message(turn) for turn in contents]
            response = self.client.responses.create(**self._responses_kwargs(input_payload, aspect_ratio, resolution))
            return self._decode_response_image(response)
        except Exception as e:
            error_detail = (
                f"Error generating image with OpenAI Responses conversation (backend={self.backend}, "
                f"model={self.responses_model}, image_model={self.image_model}): "
                f"{type(e).__name__}: {str(e)}"
            )
            logger.error(error_detail, exc_info=True)
            raise Exception(error_detail) from e

    def _generate_image_chat(
        self,
        prompt: str,
        ref_images: Optional[List[Image.Image]],
        aspect_ratio: str,
        resolution: str,
    ) -> Optional[Image.Image]:
        """Existing proxy-compatible chat-completions image path."""
        try:
            content = []
            if ref_images:
                for ref_img in ref_images:
                    base64_image = self._encode_image_to_base64(ref_img)
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    })
            content.append({"type": "text", "text": prompt})

            extra_body = self._build_extra_body(aspect_ratio, resolution)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"aspect_ratio={aspect_ratio}, resolution={resolution}"},
                    {"role": "user", "content": content},
                ],
                modalities=["text", "image"],
                extra_body=extra_body
            )

            message = response.choices[0].message

            if hasattr(message, 'multi_mod_content') and message.multi_mod_content:
                parts = message.multi_mod_content
                for part in parts:
                    if "inline_data" in part:
                        image_data = base64.b64decode(part["inline_data"]["data"])
                        image = Image.open(BytesIO(image_data))
                        image.load()
                        return image

            if hasattr(message, 'content') and message.content:
                if isinstance(message.content, list):
                    for part in message.content:
                        if isinstance(part, dict):
                            if part.get('type') == 'image_url':
                                image_url = part.get('image_url', {}).get('url', '')
                                if image_url.startswith('data:image'):
                                    image_data = base64.b64decode(image_url.split(',', 1)[1])
                                    image = Image.open(BytesIO(image_data))
                                    image.load()
                                    return image
                        elif getattr(part, 'type', None) == 'image_url':
                            image_url = getattr(part, 'image_url', {})
                            url = image_url.get('url', '') if isinstance(image_url, dict) else getattr(image_url, 'url', '')
                            if url.startswith('data:image'):
                                image_data = base64.b64decode(url.split(',', 1)[1])
                                image = Image.open(BytesIO(image_data))
                                image.load()
                                return image
                elif isinstance(message.content, str):
                    content_str = message.content
                    markdown_pattern = r'!\[.*?\]\((https?://[^\s\)]+)\)'
                    markdown_matches = re.findall(markdown_pattern, content_str)
                    if markdown_matches:
                        image = self._download_image(markdown_matches[0])
                        if image:
                            return image

                    url_pattern = r'(https?://[^\s\)\]]+\.(?:png|jpg|jpeg|gif|webp|bmp)(?:\?[^\s\)\]]*)?)'
                    url_matches = re.findall(url_pattern, content_str, re.IGNORECASE)
                    if url_matches:
                        image = self._download_image(url_matches[0])
                        if image:
                            return image

                    base64_pattern = r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)'
                    base64_matches = re.findall(base64_pattern, content_str)
                    if base64_matches:
                        image_data = base64.b64decode(base64_matches[0])
                        image = Image.open(BytesIO(image_data))
                        image.load()
                        return image

            raise ValueError("No valid multimodal response received from OpenAI API")
        except Exception as e:
            error_detail = f"Error generating image with OpenAI (model={self.model}): {type(e).__name__}: {str(e)}"
            logger.error(error_detail, exc_info=True)
            raise Exception(error_detail) from e

    @staticmethod
    def _download_image(image_url: str) -> Optional[Image.Image]:
        try:
            response = requests.get(image_url, timeout=30, stream=True)
            response.raise_for_status()
            image = Image.open(BytesIO(response.content))
            image.load()
            return image
        except Exception as download_error:
            logger.warning("Failed to download image from URL: %s", download_error)
            return None
