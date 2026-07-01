"""
Canonical runtime style preset loading and application.

Presets are defined under ``assets/presets/<preset-id>/`` (``preset.json``, base image,
``prompt-*.md``). This module validates SHA-256, caches manifests, serves prompt text to
``prompts.py`` / task flows, and copies base images when controllers apply ``style_preset_id``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class StylePresetError(ValueError):
    """Raised when a style preset cannot be loaded or applied."""


_PROMPT_KEYS = ("generate", "restyle", "translateRestyle")

_manifest_cache: list["StylePreset"] | None = None
_manifest_cache_mtime: float | None = None


def clear_style_preset_cache() -> None:
    """Clear in-process preset manifest cache (tests/dev)."""
    global _manifest_cache, _manifest_cache_mtime
    _manifest_cache = None
    _manifest_cache_mtime = None


@dataclass(frozen=True)
class StylePreset:
    id: str
    legacy_ids: list[str]
    version: str
    name: str
    base_image: str
    sha256: str
    prompts: dict[str, str]
    prompt_texts: dict[str, str] = field(default_factory=dict)
    directory: Path = field(default_factory=Path)

    @property
    def base_image_path(self) -> Path:
        return self.directory / self.base_image

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "legacyIds": self.legacy_ids,
            "version": self.version,
            "name": self.name,
            "baseImage": self.base_image,
            "sha256": self.sha256,
            "imageUrl": f"/api/presets/{self.id}/image",
            "prompts": {
                key: self.prompt_texts.get(key, self.prompts.get(key, ""))
                for key in _PROMPT_KEYS
                if key in self.prompts or key in self.prompt_texts
            },
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _presets_root() -> Path:
    return _repo_root() / "assets" / "presets"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_prompt_texts(directory: Path, prompt_files: dict[str, str]) -> dict[str, str]:
    loaded: dict[str, str] = {}
    for key, filename in prompt_files.items():
        path = directory / filename
        if not path.is_file():
            raise StylePresetError(
                f"Style preset prompt file missing: {path}"
            )
        loaded[key] = path.read_text(encoding="utf-8").strip()
    return loaded


def _load_manifest(path: Path) -> StylePreset:
    data = json.loads(path.read_text(encoding="utf-8"))
    directory = path.parent
    prompt_files = data.get("prompts", {})
    preset = StylePreset(
        id=data["id"],
        legacy_ids=data.get("legacyIds", []),
        version=data["version"],
        name=data["name"],
        base_image=data["baseImage"],
        sha256=data["sha256"],
        prompts=prompt_files,
        prompt_texts=_load_prompt_texts(directory, prompt_files),
        directory=directory,
    )
    actual_sha = _sha256(preset.base_image_path)
    if actual_sha != preset.sha256:
        raise StylePresetError(
            f"Style preset {preset.id} base image sha256 mismatch: "
            f"manifest={preset.sha256}, actual={actual_sha}"
        )
    return preset


def _presets_root_mtime() -> float:
    root = _presets_root()
    if not root.is_dir():
        return 0.0
    mtimes = [root.stat().st_mtime]
    for path in root.rglob("*"):
        if path.is_file():
            mtimes.append(path.stat().st_mtime)
    return max(mtimes)


def _load_all_presets() -> list[StylePreset]:
    return [
        _load_manifest(manifest)
        for manifest in sorted(_presets_root().glob("*/preset.json"))
    ]


def list_style_presets() -> list[StylePreset]:
    global _manifest_cache, _manifest_cache_mtime
    mtime = _presets_root_mtime()
    if _manifest_cache is not None and _manifest_cache_mtime == mtime:
        return list(_manifest_cache)
    presets = _load_all_presets()
    _manifest_cache = presets
    _manifest_cache_mtime = mtime
    return list(presets)


def get_style_preset(preset_id: str) -> StylePreset:
    requested_id = (preset_id or "").strip()
    for preset in list_style_presets():
        if requested_id == preset.id or requested_id in preset.legacy_ids:
            return preset
    raise StylePresetError(f"Unsupported style_preset_id: {preset_id}")


def resolve_preset_prompt_body_for_flow(
    style_preset_id: str | None,
    prompt_key: str,
    user_prompt: str,
) -> tuple[str | None, str]:
    """
    When a style preset is active, use canonical prompt files unless the user
    provided materially different text.
    """
    user = (user_prompt or "").strip()
    if not style_preset_id:
        return None, user
    canonical = get_style_preset_prompt_text(style_preset_id, prompt_key)
    if not user or user == canonical:
        return canonical, ""
    return None, user


def resolve_generate_style_requirements(project) -> str | None:
    """Merge extra_requirements, explicit template_style, or canonical generate prompt."""
    combined = project.extra_requirements or ""
    template_style = (getattr(project, "template_style", None) or "").strip()
    style_preset_id = getattr(project, "style_preset_id", None)
    if style_preset_id:
        canonical = get_style_preset_prompt_text(style_preset_id, "generate")
        if template_style and template_style != canonical:
            combined += f"\n\nppt页面风格描述：\n\n{template_style}"
        else:
            combined += "\n\n" + canonical
    elif template_style:
        combined += f"\n\nppt页面风格描述：\n\n{template_style}"
    text = combined.strip()
    return text or None


def get_style_preset_prompt_text(preset_id: str, prompt_key: str) -> str:
    preset = get_style_preset(preset_id)
    text = preset.prompt_texts.get(prompt_key, "").strip()
    if not text:
        raise StylePresetError(
            f"Style preset {preset.id} has no prompt text for key: {prompt_key}"
        )
    return text


def apply_style_preset_to_project(
    *,
    project,
    file_service,
    style_preset_id: str,
    existing_paths: list[str] | None = None,
) -> str:
    """
    Copy a canonical preset base image into a project's style_refs directory.

    Returns the saved relative upload path.
    """
    preset = get_style_preset(style_preset_id)
    project_dir = file_service._get_project_dir(project.id)
    style_ref_dir = project_dir / "style_refs"
    style_ref_dir.mkdir(exist_ok=True, parents=True)

    target = style_ref_dir / f"style_ref_preset_{preset.id}.png"
    shutil.copyfile(preset.base_image_path, target)
    rel_path = target.relative_to(file_service.upload_folder).as_posix()

    paths = existing_paths if existing_paths is not None else project.get_style_ref_image_paths()
    if rel_path not in paths:
        paths.append(rel_path)

    project.style_preset_id = preset.id
    project.style_preset_version = preset.version
    project.style_preset_sha256 = preset.sha256
    return rel_path