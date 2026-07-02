"""Unit tests for role-aware image generation provider inputs."""

import os

from PIL import Image

from services.ai_service import AIService


class _ConversationProvider:
    supports_conversation_contents = True

    def __init__(self):
        self.contents = None
        self.generate_image_calls = 0

    def generate_image_from_conversation(self, contents, **_kwargs):
        self.contents = contents
        return Image.new("RGB", (16, 9), color="blue")

    def generate_image(self, *_args, **_kwargs):
        self.generate_image_calls += 1
        return Image.new("RGB", (16, 9), color="red")


class _LegacyProvider:
    supports_conversation_contents = False

    def __init__(self):
        self.kwargs = None

    def generate_image(self, **kwargs):
        self.kwargs = kwargs
        return Image.new("RGB", (16, 9), color="green")


def test_role_aware_generation_uses_grouped_conversation_provider_input():
    provider = _ConversationProvider()
    service = AIService(text_provider=object(), image_provider=provider)
    style_img = Image.new("RGB", (10, 10), color="black")
    content_img = Image.new("RGB", (12, 12), color="white")

    result = service.generate_image(
        prompt="PURE PRESET PROMPT\n\n页面标题：A",
        style_ref_images=[style_img],
        content_ref_images=[content_img],
    )

    assert result.size == (16, 9)
    assert provider.generate_image_calls == 0
    assert provider.contents == [
        {
            "role": "user",
            "parts": [
                {"text": "PURE PRESET PROMPT\n\n页面标题：A"},
                {"text": "STYLE_REFERENCE_IMAGES_BEGIN"},
                {"text": "STYLE_REFERENCE image 1"},
                {"image": style_img},
                {"text": "STYLE_REFERENCE_IMAGES_END"},
                {"text": "CONTENT_REFERENCE_IMAGES_BEGIN"},
                {"text": "CONTENT_REFERENCE image 1"},
                {"image": content_img},
                {"text": "CONTENT_REFERENCE_IMAGES_END"},
            ],
        }
    ]


def test_legacy_generation_callers_still_use_flat_provider_input():
    provider = _LegacyProvider()
    service = AIService(text_provider=object(), image_provider=provider)
    ref_img = Image.new("RGB", (10, 10), color="black")
    extra_img = Image.new("RGB", (12, 12), color="white")

    result = service.generate_image(
        prompt="legacy prompt",
        ref_image_path=None,
        additional_ref_images=[ref_img, extra_img],
    )

    assert result.size == (16, 9)
    assert provider.kwargs["prompt"] == "legacy prompt"
    assert provider.kwargs["ref_images"] == [ref_img, extra_img]


def test_files_materials_refs_resolve_from_flask_upload_folder(app):
    provider = _ConversationProvider()
    service = AIService(text_provider=object(), image_provider=provider)
    materials_dir = os.path.join(app.config["UPLOAD_FOLDER"], "materials")
    os.makedirs(materials_dir, exist_ok=True)
    content_path = os.path.join(materials_dir, "content.png")
    Image.new("RGB", (12, 12), color="white").save(content_path)

    with app.app_context():
        result = service.generate_image(
            prompt="PURE PRESET PROMPT\n\n页面标题：A",
            content_ref_images=["/files/materials/content.png"],
        )

    assert result.size == (16, 9)
    parts = provider.contents[0]["parts"]
    assert {"text": "CONTENT_REFERENCE_IMAGES_BEGIN"} in parts
    assert any("image" in part for part in parts)
