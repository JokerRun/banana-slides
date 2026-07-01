# Runtime style presets

Product style presets (base image, version, SHA-256, and flow-specific prompts) live under `assets/presets/<preset-id>/`. The backend is the single source of truth: it loads `preset.json`, verifies the base image hash, serves metadata and images via `/api/presets`, and copies the canonical base image into a project when `style_preset_id` is submitted.

## Layout (DDI example)

```text
assets/presets/ddi/
  preset.json              # id, legacyIds, version, sha256, prompt file names
  base.png                 # canonical base / style reference image
  prompt-generate.md       # generate-from-idea/outline/descriptions flow
  prompt-restyle.md        # restyle first-pass
  prompt-translate-restyle.md
```

Canonical preset id for DDI is `ddi-standard`. Legacy ids `ddi`, `ddi-restyle-v2` are accepted on create/upload APIs and normalized to `ddi-standard` on the project record.

## API

- `GET /api/presets` — list presets (metadata + prompt text + `imageUrl`)
- `GET /api/presets/<preset_id>/image` — canonical base PNG

## Project fields

When a preset is applied at project creation (restyle, translate+restyle, or `POST /api/projects/{id}/style-refs`), the backend sets `style_preset_id`, `style_preset_version`, `style_preset_sha256`, and copies `base.png` into the project `style_refs` directory.

## Not runtime sources

- `assets/style-presets/` — legacy layout only; see its README
- `frontend/public/restyle-presets/` — legacy public copies; UI uses `/api/presets` URLs
- `.agents/references/` — agent/design reference only; not loaded by the app