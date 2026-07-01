"""
Canonical runtime style preset loading and application.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class StylePresetError(ValueError):
    """Raised when a style preset cannot be loaded or applied."""


@dataclass(frozen=True)
class StylePreset:
    id: str
    legacy_ids: list[str]
    version: str
    name: str
    base_image: str
    sha256: str
    prompts: dict[str, str]
    directory: Path

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
            "prompts": self.prompts,
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


def _load_manifest(path: Path) -> StylePreset:
    data = json.loads(path.read_text(encoding="utf-8"))
    directory = path.parent
    preset = StylePreset(
        id=data["id"],
        legacy_ids=data.get("legacyIds", []),
        version=data["version"],
        name=data["name"],
        base_image=data["baseImage"],
        sha256=data["sha256"],
        prompts=data.get("prompts", {}),
        directory=directory,
    )
    actual_sha = _sha256(preset.base_image_path)
    if actual_sha != preset.sha256:
        raise StylePresetError(
            f"Style preset {preset.id} base image sha256 mismatch: "
            f"manifest={preset.sha256}, actual={actual_sha}"
        )
    return preset


def list_style_presets() -> list[StylePreset]:
    presets = []
    for manifest in sorted(_presets_root().glob("*/preset.json")):
        presets.append(_load_manifest(manifest))
    return presets


def get_style_preset(preset_id: str) -> StylePreset:
    requested_id = (preset_id or "").strip()
    for preset in list_style_presets():
        if requested_id == preset.id or requested_id in preset.legacy_ids:
            return preset
    raise StylePresetError(f"Unsupported style_preset_id: {preset_id}")


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
