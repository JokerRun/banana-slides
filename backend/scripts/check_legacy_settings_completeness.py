"""Pre-cutover checker for legacy settings completeness.

Compares non-empty values in the legacy DB `settings` row against env vars.
Reports optional items that still exist in DB but are missing in env.
"""

import argparse
from pathlib import Path
import sys
from typing import List, Tuple


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from models.settings import Settings


OPTIONAL_FIELD_ENV_MAP = {
    "api_base_url": ("GOOGLE_API_BASE", "OPENAI_API_BASE"),
    "text_model": ("TEXT_MODEL",),
    "image_model": ("IMAGE_MODEL",),
    "mineru_api_base": ("MINERU_API_BASE",),
    "mineru_token": ("MINERU_TOKEN",),
    "image_caption_model": ("IMAGE_CAPTION_MODEL",),
    "output_language": ("OUTPUT_LANGUAGE",),
    "baidu_ocr_api_key": ("BAIDU_OCR_API_KEY",),
}


def _is_non_empty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _is_env_missing(app, env_keys: Tuple[str, ...]) -> bool:
    for key in env_keys:
        env_value = app.config.get(key)
        if _is_non_empty(env_value):
            return False
    return True


def _scan_missing_optional_env(app) -> List[Tuple[str, Tuple[str, ...], str]]:
    settings = Settings.query.first()
    if not settings:
        return []

    mismatches: List[Tuple[str, Tuple[str, ...], str]] = []
    for field, env_keys in OPTIONAL_FIELD_ENV_MAP.items():
        db_value = getattr(settings, field, None)
        if not _is_non_empty(db_value):
            continue
        if _is_env_missing(app, env_keys):
            preview = "***" if "token" in field or "key" in field else str(db_value)
            mismatches.append((field, env_keys, preview))
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check optional env completeness before env-only settings cutover"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit with code 2 when mismatches are found",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        mismatches = _scan_missing_optional_env(app)

    if not mismatches:
        print("clean: no optional env mismatches found")
        return 0

    print("missing optional env for non-empty legacy settings:")
    for field, env_keys, preview in mismatches:
        print(f"- {field}: db_has_value={preview}, env_expected_any_of={','.join(env_keys)}")

    return 2 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
