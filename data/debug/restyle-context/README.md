# Restyle context debug artifacts

`data/debug/restyle-context/<task_id>/` stores JSON traces for **restyle first-pass** (`RESTYLE_IMAGES`) and **restyle single-page edit** (`EDIT_PAGE_IMAGE` on `creation_type=restyle`).

## Layout by flow

| Flow | Directory shape | Typical files |
|------|-----------------|---------------|
| Batch first-pass restyle | `task/started.json`, `task/summary.json`, `pages/page-NNN-<page_id>/` per page | `context_built.json`, `provider_decision.json`, `provider_request.json`, `provider_result.json`, `saved_version.json` |
| Single-page restyle edit | Flat under `<task_id>/` | Same five event files at task root |

`flow_kind` in traces: `first_pass_restyle` vs `edit_restyle`. Non-restyle `EDIT_PAGE_IMAGE` does not write here (see `page_image_versions.prompt_snapshot` / `ref_manifest` in DB).

## Key fields

- **First-pass** `context_built.json`: assembled prompt, style ref manifest, `snapshot_present` on page.
- **Edit** `context_built.json`: `snapshot_source` (`persisted` | `reconstructed`), `degraded_context`, turn/image counts.
- **saved_version.json**: new `version_number`, `image_path`; edit runs include `trace.source_version_number`.

## Write policy

Artifacts are written when `DEBUG_RESTYLE_CONTEXT=true`, or on degrade / provider fallback / error. See parent [../README.md](../README.md).

## Cleanup

Safe to delete individual `<task_id>` folders or all of `restyle-context/`; does not remove DB rows or uploaded images.