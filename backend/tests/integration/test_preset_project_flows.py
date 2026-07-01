"""
Preset-backed project creation flows.
"""

import io
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from conftest import assert_success_response


def _png_bytes(color: str = "blue") -> bytes:
    image = Image.new("RGB", (16, 16), color=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_create_restyle_project_accepts_ddi_preset_without_uploaded_style_refs(
    client, tmp_path
):
    original = tmp_path / "slide.png"
    original.write_bytes(_png_bytes("white"))

    with patch(
        "services.restyle_service.RestyleService.convert_to_images",
        return_value=[str(original)],
    ):
        response = client.post(
            "/api/projects/restyle",
            data={
                "source_file": (io.BytesIO(b"pptx"), "slides.pptx"),
                "style_preset_id": "ddi-restyle-v2",
            },
            content_type="multipart/form-data",
        )

    result = assert_success_response(response, 201)
    project_id = result["data"]["project_id"]
    project = assert_success_response(client.get(f"/api/projects/{project_id}"))["data"]

    assert project["style_preset_id"] == "ddi-standard"
    assert project["style_ref_image_paths"] == [
        f"{project_id}/style_refs/style_ref_preset_ddi-standard.png"
    ]


def test_create_translate_restyle_project_accepts_ddi_preset_without_uploaded_style_refs(
    client, tmp_path
):
    original = tmp_path / "slide.png"
    original.write_bytes(_png_bytes("white"))

    with patch(
        "services.restyle_service.RestyleService.convert_to_images",
        return_value=[str(original)],
    ):
        response = client.post(
            "/api/projects/translate",
            data={
                "source_file": (io.BytesIO(b"pptx"), "slides.pptx"),
                "target_language": "English",
                "translate_mode": "restyle",
                "style_preset_id": "ddi-standard",
            },
            content_type="multipart/form-data",
        )

    result = assert_success_response(response, 201)
    project_id = result["data"]["project_id"]
    project = assert_success_response(client.get(f"/api/projects/{project_id}"))["data"]

    assert project["style_preset_id"] == "ddi-standard"
    assert project["style_ref_image_paths"] == [
        f"{project_id}/style_refs/style_ref_preset_ddi-standard.png"
    ]


def test_create_translate_pure_rejects_style_preset_id(client, tmp_path):
    original = tmp_path / "slide.png"
    original.write_bytes(_png_bytes("white"))

    with patch(
        "services.restyle_service.RestyleService.convert_to_images",
        return_value=[str(original)],
    ):
        response = client.post(
            "/api/projects/translate",
            data={
                "source_file": (io.BytesIO(b"pptx"), "slides.pptx"),
                "target_language": "English",
                "translate_mode": "pure",
                "style_preset_id": "ddi-standard",
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 400
    body = response.get_json()
    assert "pure" in body["error"]["message"].lower()


def test_create_restyle_project_still_accepts_custom_style_refs(client, tmp_path):
    original = tmp_path / "slide.png"
    original.write_bytes(_png_bytes("white"))

    with patch(
        "services.restyle_service.RestyleService.convert_to_images",
        return_value=[str(original)],
    ):
        response = client.post(
            "/api/projects/restyle",
            data={
                "source_file": (io.BytesIO(b"pptx"), "slides.pptx"),
                "style_refs": (io.BytesIO(_png_bytes("green")), "custom.png"),
            },
            content_type="multipart/form-data",
        )

    result = assert_success_response(response, 201)
    project_id = result["data"]["project_id"]
    project = assert_success_response(client.get(f"/api/projects/{project_id}"))["data"]

    assert project["style_preset_id"] is None
    assert project["style_ref_image_paths"] == [
        f"{project_id}/style_refs/style_ref_1.png"
    ]
