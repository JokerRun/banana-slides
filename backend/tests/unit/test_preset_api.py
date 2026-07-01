"""
Canonical preset API tests.
"""

import hashlib
from pathlib import Path

from conftest import assert_success_response


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
