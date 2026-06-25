#!/usr/bin/env python3
"""Render an environment file from a canonical example file.

The example file owns ordering, comments, and defaults. Existing environment
files own sensitive values. This makes production env updates reviewable with a
plain diff whenever .env.example changes.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ASSIGNMENT_RE = re.compile(r"^(?P<prefix>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
COMMENTED_ASSIGNMENT_RE = re.compile(
    r"^(?P<prefix>\s*)#\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$"
)

# Old production files used AZURE_OPENAI_* names. The app now uses OPENAI_*
# names for both proxy and Azure OpenAI image backends.
ALIASES: dict[str, tuple[str, ...]] = {
    "OPENAI_API_KEY": ("AZURE_OPENAI_API_KEY",),
    "OPENAI_API_VERSION": ("AZURE_OPENAI_API_VERSION",),
    "OPENAI_RESPONSES_MODEL": ("AZURE_OPENAI_RESPONSES_MODEL",),
    "OPENAI_IMAGE_DEPLOYMENT": ("AZURE_OPENAI_IMAGE_DEPLOYMENT",),
    "OPENAI_IMAGE_QUALITY": ("AZURE_OPENAI_IMAGE_QUALITY",),
    "OPENAI_IMAGE_OUTPUT_FORMAT": ("AZURE_OPENAI_IMAGE_OUTPUT_FORMAT",),
}


@dataclass(frozen=True)
class EnvData:
    values: dict[str, str]
    duplicates: list[str]


def read_env(path: Path) -> EnvData:
    values: dict[str, str] = {}
    duplicates: list[str] = []
    if not path.exists():
        return EnvData(values, duplicates)

    for line in path.read_text(encoding="utf-8").splitlines():
        match = ASSIGNMENT_RE.match(line)
        if not match:
            continue
        key = match.group("key")
        if key in values:
            duplicates.append(key)
            continue
        values[key] = match.group("value")
    return EnvData(values, duplicates)


def choose_value(
    key: str,
    source: dict[str, str],
    fallback: dict[str, str],
) -> tuple[str | None, str | None]:
    if key in source:
        return source[key], key
    for alias in ALIASES.get(key, ()):  # source aliases are production secrets too
        if alias in source:
            return source[alias], alias
    if key in fallback:
        return fallback[key], key
    for alias in ALIASES.get(key, ()):  # less common, useful for local migration
        if alias in fallback:
            return fallback[alias], alias
    return None, None


def render(template: Path, source: Path, fallback: Path | None) -> tuple[str, list[str]]:
    source_data = read_env(source)
    fallback_data = read_env(fallback) if fallback else EnvData({}, [])
    source_values = source_data.values
    fallback_values = fallback_data.values
    template_lines = template.read_text(encoding="utf-8").splitlines()
    active_template_keys = {
        match.group("key")
        for line in template_lines
        if (match := ASSIGNMENT_RE.match(line))
    }

    used_source_keys: set[str] = set()
    template_keys: set[str] = set()
    output: list[str] = []
    filled_from_source: list[str] = []
    filled_from_alias: list[str] = []
    filled_from_fallback: list[str] = []

    for line in template_lines:
        active = ASSIGNMENT_RE.match(line)
        commented = COMMENTED_ASSIGNMENT_RE.match(line)

        if active:
            key = active.group("key")
            template_keys.add(key)
            value, actual_key = choose_value(key, source_values, fallback_values)
            if value is None:
                output.append(line)
                continue
            if actual_key in source_values:
                used_source_keys.add(actual_key)
                if actual_key == key:
                    filled_from_source.append(key)
                else:
                    filled_from_alias.append(f"{key}<-{actual_key}")
            else:
                filled_from_fallback.append(key)
            output.append(f"{active.group('prefix')}{key}={value}")
            continue

        if commented:
            key = commented.group("key")
            template_keys.add(key)
            if key in active_template_keys:
                output.append(line)
                continue
            value, actual_key = choose_value(key, source_values, {})
            if value is None:
                output.append(line)
                continue
            used_source_keys.add(actual_key or key)
            output.append(f"{commented.group('prefix')}{key}={value}")
            if actual_key == key:
                filled_from_source.append(key)
            else:
                filled_from_alias.append(f"{key}<-{actual_key}")
            continue

        output.append(line)

    alias_source_keys = {alias for aliases in ALIASES.values() for alias in aliases}
    legacy_keys = [
        key
        for key in source_values
        if key not in template_keys and key not in used_source_keys and key not in alias_source_keys
    ]
    if legacy_keys:
        output.extend(
            [
                "",
                "",
                "# =============================================================================",
                "# Legacy / environment-specific values not present in .env.example",
                "# Review these after upgrading the application, then either add them to",
                "# .env.example or remove them from the production environment.",
                "# =============================================================================",
            ]
        )
        for key in legacy_keys:
            output.append(f"{key}={source_values[key]}")

    report = [
        f"template_keys={len(template_keys)}",
        f"filled_from_source={len(filled_from_source)}",
        f"filled_from_alias={len(filled_from_alias)}",
        f"filled_from_fallback={len(filled_from_fallback)}",
        f"legacy_keys={len(legacy_keys)}",
    ]
    if source_data.duplicates:
        report.append("source_duplicates=" + ",".join(source_data.duplicates))
    if fallback_data.duplicates:
        report.append("fallback_duplicates=" + ",".join(fallback_data.duplicates))
    if filled_from_alias:
        report.append("aliases=" + ",".join(filled_from_alias))
    if legacy_keys:
        report.append("legacy=" + ",".join(legacy_keys))

    return "\n".join(output) + "\n", report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render an env file using .env.example layout and existing env values."
    )
    parser.add_argument("--template", default=".env.example", type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--fallback", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output if it already exists.",
    )
    args = parser.parse_args()

    if not args.template.exists():
        parser.error(f"template not found: {args.template}")
    if not args.source.exists():
        parser.error(f"source not found: {args.source}")
    if args.fallback and not args.fallback.exists():
        parser.error(f"fallback not found: {args.fallback}")
    if args.output.exists() and not args.force:
        parser.error(f"output already exists: {args.output}; pass --force to overwrite")

    content, report = render(args.template, args.source, args.fallback)
    args.output.write_text(content, encoding="utf-8")
    print(f"wrote {args.output}")
    for item in report:
        print(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
