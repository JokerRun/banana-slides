"""
Style preset service unit tests.
"""

import hashlib
from pathlib import Path

import pytest

from services.style_preset_service import (
    StylePresetError,
    clear_style_preset_cache,
    get_style_preset,
    get_style_preset_prompt_text,
    list_style_presets,
    resolve_generate_style_requirements,
    resolve_preset_prompt_body_for_flow,
)


@pytest.fixture(autouse=True)
def _clear_preset_cache():
    clear_style_preset_cache()
    yield
    clear_style_preset_cache()


def test_list_style_presets_uses_cache_without_rescanning_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.style_preset_service._presets_root",
        lambda: tmp_path,
    )
    preset_dir = tmp_path / "ddi"
    preset_dir.mkdir()
    base = preset_dir / "base.png"
    base.write_bytes(b"png-bytes")
    sha = hashlib.sha256(base.read_bytes()).hexdigest()
    (preset_dir / "preset.json").write_text(
        f"""{{
  "id": "ddi-standard",
  "legacyIds": ["ddi"],
  "version": "test",
  "name": "DDI",
  "baseImage": "base.png",
  "sha256": "{sha}",
  "prompts": {{
    "generate": "prompt-generate.md",
    "restyle": "prompt-restyle.md",
    "translateRestyle": "prompt-translate-restyle.md"
  }}
}}""",
        encoding="utf-8",
    )
    (preset_dir / "prompt-generate.md").write_text("generate body", encoding="utf-8")
    (preset_dir / "prompt-restyle.md").write_text("restyle body", encoding="utf-8")
    (preset_dir / "prompt-translate-restyle.md").write_text(
        "translate body", encoding="utf-8"
    )

    monkeypatch.setattr(
        "services.style_preset_service._presets_root_mtime",
        lambda: 1.0,
    )

    first = list_style_presets()
    base.write_bytes(b"changed")
    second = list_style_presets()

    assert len(first) == 1
    assert first[0].sha256 == sha
    assert second[0].sha256 == sha
    assert first[0] is second[0] or first[0].id == second[0].id


def test_get_style_preset_prompt_text_loads_canonical_file():
    text = get_style_preset_prompt_text("ddi-standard", "restyle")
    assert "资深商业咨询级 PPT 排版与视觉架构师" in text
    assert "零重写内容原则" in text


def test_resolve_generate_style_requirements_uses_preset_when_no_template_style():
    class Project:
        extra_requirements = None
        template_style = None
        style_preset_id = "ddi-standard"

    combined = resolve_generate_style_requirements(Project())
    assert combined is not None
    assert "资深商业咨询级 PPT 排版与视觉架构师" in combined


def test_resolve_preset_prompt_body_uses_canonical_when_ui_prefill_matches():
    canonical = get_style_preset_prompt_text("ddi-standard", "restyle")
    preset_body, user = resolve_preset_prompt_body_for_flow(
        "ddi-standard", "restyle", canonical
    )
    assert preset_body == canonical
    assert user == ""


def test_resolve_preset_prompt_body_keeps_custom_when_user_edits():
    canonical = get_style_preset_prompt_text("ddi-standard", "restyle")
    custom = "my unique restyle instructions"
    preset_body, user = resolve_preset_prompt_body_for_flow(
        "ddi-standard", "restyle", custom
    )
    assert preset_body is None
    assert user == custom


def test_resolve_generate_style_requirements_raises_on_bad_preset():
    class Project:
        extra_requirements = None
        template_style = None
        style_preset_id = "nonexistent-preset-id"

    with pytest.raises(StylePresetError):
        resolve_generate_style_requirements(Project())