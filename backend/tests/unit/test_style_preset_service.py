"""
Style preset service unit tests.
"""

import hashlib
from pathlib import Path

import pytest

from services.style_preset_service import (
    clear_style_preset_cache,
    get_style_preset,
    get_style_preset_prompt_text,
    list_style_presets,
    resolve_generate_style_requirements,
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
    assert "DDI Restyle Prompt" in text


def test_resolve_generate_style_requirements_uses_preset_when_no_template_style():
    class Project:
        extra_requirements = None
        template_style = None
        style_preset_id = "ddi-standard"

    combined = resolve_generate_style_requirements(Project())
    assert combined is not None
    assert "DDI Generate Prompt" in combined