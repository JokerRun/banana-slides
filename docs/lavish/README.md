# Lavish Reports

Historical Lavish planning and review artifacts for Banana Slides. **Treat the HTML
reports as archived context from when they were written**—file paths, RCA steps,
baselines, and “next step” plans inside them may no longer match the current
codebase. Use this index for discovery; verify behavior in code before acting on
a report.

Open any `.html` file in a browser for the full layout (Mermaid diagrams, tables).

| Report | Purpose |
| --- | --- |
| `banana-history-rename-fix-plan.html` | Plan for fixing project history display names and rename behavior. |
| `banana-image-context-fix-plan.html` | Plan for preserving markdown image semantics in From Description generation (structured IMAGE_REF + binary refs). |
| `banana-prompt-deep-dive.html` | Original prompt and image generation flow deep dive. |
| `banana-prompt-deep-dive-revised.html` | Revised prompt deep dive after follow-up review (same topic; extra responsive layout and 定稿方案 section—both kept as separate historical snapshots). |

## Where to look in the repo today

These reports informed later work; **canonical behavior is defined by code and
maintained docs**, not the HTML snapshots.

| Topic | Current references |
| --- | --- |
| History display names / rename | `AGENTS.md` (Project display names), `backend/README.md` (`project_name` API), `backend/models/project.py` |
| Markdown images in From Description | `backend/services/ai_service.py` (IMAGE_REF normalization), `backend/services/prompts.py`, `backend/tests/unit/test_description_prompts.py` |
| Generate prompt layering / DDI presets / edit context | `AGENTS.md` (Prompts / image edit, Style presets), `assets/presets/`, `docs/superpowers/specs/2026-03-23-restyle-edit-conversation-context-design.md` |

Active specs and plans live under `docs/superpowers/`; this directory is **archive only**.