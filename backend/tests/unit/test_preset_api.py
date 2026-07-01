"""
Canonical preset API tests.
"""

import hashlib
import io
from pathlib import Path

from PIL import Image

from conftest import assert_success_response


def _png_bytes(color: str = "blue") -> bytes:
    image = Image.new("RGB", (16, 16), color=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_presets_api_returns_canonical_ddi_manifest(client):
    response = client.get("/api/presets")

    result = assert_success_response(response)
    presets = result["data"]["presets"]
    ddi = next(preset for preset in presets if preset["id"] == "ddi-standard")

    canonical_base = (
        Path(__file__).resolve().parents[2]
        / ".."
        / "assets"
        / "presets"
        / "ddi"
        / "base.png"
    ).resolve()
    expected_sha = hashlib.sha256(canonical_base.read_bytes()).hexdigest()

    assert ddi["version"] == "2026-07-01"
    assert ddi["sha256"] == expected_sha
    assert ddi["legacyIds"] == ["ddi", "ddi-standard", "ddi-restyle-v2"]
    assert ddi["imageUrl"] == "/api/presets/ddi-standard/image"
    assert "资深商业咨询级 PPT 排版与视觉架构师" in ddi["prompts"]["generate"]
    assert "零重写内容原则" in ddi["prompts"]["restyle"]
    assert "专业PPT翻译与视觉重构专家" in ddi["prompts"]["translateRestyle"]


def test_legacy_ddi_style_preset_copies_canonical_base_and_records_metadata(client):
    create_response = client.post(
        "/api/projects",
        json={"creation_type": "idea", "idea_prompt": "DDI deck"},
    )
    project_id = assert_success_response(create_response, 201)["data"]["project_id"]

    upload_response = client.post(
        f"/api/projects/{project_id}/style-refs",
        data={"style_preset_id": "ddi"},
        content_type="multipart/form-data",
    )

    result = assert_success_response(upload_response)
    saved_path = result["data"]["style_ref_image_paths"][0]
    assert saved_path.endswith("style_refs/style_ref_preset_ddi-standard.png")

    project_response = client.get(f"/api/projects/{project_id}")
    project = assert_success_response(project_response)["data"]

    canonical_base = (
        Path(__file__).resolve().parents[2]
        / ".."
        / "assets"
        / "presets"
        / "ddi"
        / "base.png"
    ).resolve()
    saved_base = Path(client.application.config["UPLOAD_FOLDER"]) / saved_path
    expected_sha = hashlib.sha256(canonical_base.read_bytes()).hexdigest()

    assert hashlib.sha256(saved_base.read_bytes()).hexdigest() == expected_sha
    assert project["style_preset_id"] == "ddi-standard"
    assert project["style_preset_version"] == "2026-07-01"
    assert project["style_preset_sha256"] == expected_sha


def test_upload_style_refs_replace_custom_only_clears_preset_metadata(client):
    create_response = client.post(
        "/api/projects",
        json={"creation_type": "idea", "idea_prompt": "DDI deck"},
    )
    project_id = assert_success_response(create_response, 201)["data"]["project_id"]

    bind_response = client.post(
        f"/api/projects/{project_id}/style-refs",
        data={"style_preset_id": "ddi-standard"},
        content_type="multipart/form-data",
    )
    assert_success_response(bind_response)

    project_response = client.get(f"/api/projects/{project_id}")
    assert (
        assert_success_response(project_response)["data"]["style_preset_id"]
        == "ddi-standard"
    )

    replace_response = client.post(
        f"/api/projects/{project_id}/style-refs",
        data={
            "replace": "true",
            "style_refs": [(io.BytesIO(_png_bytes("green")), "custom.png")],
        },
        content_type="multipart/form-data",
    )
    assert_success_response(replace_response)

    project_response = client.get(f"/api/projects/{project_id}")
    project = assert_success_response(project_response)["data"]
    assert project["style_preset_id"] is None
    assert project["style_preset_version"] is None
    assert project["style_preset_sha256"] is None
    assert len(project["style_ref_image_paths"]) == 1


def test_upload_style_refs_rejects_preset_plus_too_many_uploads(client):
    create_response = client.post(
        "/api/projects",
        json={"creation_type": "idea", "idea_prompt": "DDI deck"},
    )
    project_id = assert_success_response(create_response, 201)["data"]["project_id"]

    refs = [(io.BytesIO(_png_bytes("red")), f"ref{i}.png") for i in range(5)]
    upload_response = client.post(
        f"/api/projects/{project_id}/style-refs",
        data={
            "style_preset_id": "ddi-standard",
            "style_refs": refs,
        },
        content_type="multipart/form-data",
    )

    assert upload_response.status_code == 400
    body = upload_response.get_json()
    assert "Maximum 5" in body["error"]["message"]


def test_batch_generate_images_returns_bad_request_for_invalid_style_preset(client):
    create_response = client.post(
        "/api/projects",
        json={"creation_type": "idea", "idea_prompt": "test"},
    )
    project_id = assert_success_response(create_response, 201)["data"]["project_id"]

    bind_response = client.post(
        f"/api/projects/{project_id}/style-refs",
        data={"style_preset_id": "ddi"},
        content_type="multipart/form-data",
    )
    assert_success_response(bind_response)

    from models import db, Project

    with client.application.app_context():
        project = Project.query.filter_by(id=project_id).first()
        project.style_preset_id = "nonexistent-preset-id"
        db.session.commit()

    gen_response = client.post(
        f"/api/projects/{project_id}/generate/images",
        json={},
    )

    assert gen_response.status_code == 400
