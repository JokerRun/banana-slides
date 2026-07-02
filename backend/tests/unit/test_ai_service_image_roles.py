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
    snapshot = {}

    result = service.generate_image(
        prompt="PURE PRESET PROMPT\n\n页面标题：A",
        style_ref_images=[style_img],
        content_ref_images=[content_img],
        provider_input_snapshot_out=snapshot,
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
    assert snapshot["mode"] == "conversation"
    assert snapshot["provider"] == "_ConversationProvider"
    assert snapshot["parts"][0]["type"] == "text"
    assert snapshot["parts"][0]["role"] == "main_prompt"
    assert any(
        part["type"] == "image"
        and part["role"] == "style_reference"
        and part["loaded"] is True
        for part in snapshot["parts"]
    )
    assert any(
        part["type"] == "image"
        and part["role"] == "content_reference"
        and part["loaded"] is True
        for part in snapshot["parts"]
    )


def test_legacy_generation_callers_still_use_flat_provider_input():
    provider = _LegacyProvider()
    service = AIService(text_provider=object(), image_provider=provider)
    ref_img = Image.new("RGB", (10, 10), color="black")
    extra_img = Image.new("RGB", (12, 12), color="white")
    snapshot = {}

    result = service.generate_image(
        prompt="legacy prompt",
        ref_image_path=None,
        additional_ref_images=[ref_img, extra_img],
        provider_input_snapshot_out=snapshot,
    )

    assert result.size == (16, 9)
    assert provider.kwargs["prompt"] == "legacy prompt"
    assert provider.kwargs["ref_images"] == [ref_img, extra_img]
    assert snapshot["mode"] == "flat"
    assert [part["type"] for part in snapshot["parts"]] == [
        "text",
        "image",
        "image",
    ]


def test_files_materials_refs_resolve_from_flask_upload_folder(app):
    provider = _ConversationProvider()
    service = AIService(text_provider=object(), image_provider=provider)
    materials_dir = os.path.join(app.config["UPLOAD_FOLDER"], "materials")
    os.makedirs(materials_dir, exist_ok=True)
    content_path = os.path.join(materials_dir, "content.png")
    Image.new("RGB", (12, 12), color="white").save(content_path)
    snapshot = {}

    with app.app_context():
        result = service.generate_image(
            prompt="PURE PRESET PROMPT\n\n页面标题：A",
            content_ref_images=["/files/materials/content.png"],
            provider_input_snapshot_out=snapshot,
        )

    assert result.size == (16, 9)
    parts = provider.contents[0]["parts"]
    assert {"text": "CONTENT_REFERENCE_IMAGES_BEGIN"} in parts
    assert any("image" in part for part in parts)
    image_parts = [part for part in snapshot["parts"] if part["type"] == "image"]
    assert image_parts[0]["source"] == "/files/materials/content.png"
    assert image_parts[0]["resolved_path"] == content_path
    assert image_parts[0]["loaded"] is True
    assert image_parts[0]["width"] == 12
    assert "data" not in image_parts[0]


def test_missing_files_ref_is_recorded_as_unloaded(app):
    provider = _ConversationProvider()
    service = AIService(text_provider=object(), image_provider=provider)
    snapshot = {}

    with app.app_context():
        result = service.generate_image(
            prompt="PURE PRESET PROMPT\n\n页面标题：A",
            content_ref_images=["/files/materials/missing.png"],
            provider_input_snapshot_out=snapshot,
        )

    assert result.size == (16, 9)
    image_parts = [part for part in snapshot["parts"] if part["type"] == "image"]
    assert image_parts[0]["source"] == "/files/materials/missing.png"
    assert image_parts[0]["loaded"] is False
    assert image_parts[0]["error"] == "not_loaded"
