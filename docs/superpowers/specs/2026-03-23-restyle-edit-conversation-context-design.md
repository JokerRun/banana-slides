# Restyle Edit Conversation Context Design

Status: Ready for implementation planning

## 1. Context

In `restyle` workflow, first-pass generation has stable style anchors (`original slide`, `style refs`, `restyle prompt`).
However, edit-time image generation currently only sees:
1. current selected slide version,
2. optional current extra refs (upload/crop),
3. current edit instruction.

This causes multi-round drift: each new round overfits transient context and gradually loses the original style contract.

## 2. Goals

1. Preserve style consistency across multi-round restyle edits.
2. Inject immutable baseline context on every edit request.
3. Keep existing non-restyle edit behavior unchanged.
4. Support provider-compatible fallback without breaking availability.

## 3. In Scope

1. Restyle edit-time context modeling and request composition.
2. Per-page baseline prompt snapshot persistence.
3. Gemini `contents[]` multi-turn request support in image provider.
4. Compatibility fallback path when conversation mode is unavailable.
5. Tests for context completeness, ordering, and non-restyle regression safety.

## 4. Out Of Scope

1. Full long-term edit history replay for all rounds.
2. Frontend UX redesign of edit panel.
3. Cross-project style memory or global style profile.

## 5. Canonical Context Model

Every `restyle` edit request must be composed from two buckets.

## 5.1 Immutable Baseline Context

1. original slide (`page.original_slide_image_path`)
2. original reference images (`project.style_ref_image_paths`)
3. original prompts:
   - `project.restyle_prompt` (project-level custom restyle instruction)
   - `page.restyle_base_prompt_snapshot` (first-pass actual page prompt sent to model)

These fields are immutable at edit-time and act as style guardrails.

## 5.2 Mutable Current Context

1. current selected slide version (`page.generated_image_path` current pointer)
2. current ref images (optional: upload/crop/template from current edit request)
3. current modified prompt (`edit_instruction`, required per request)

These fields represent only this round’s delta intent.

## 6. Key Decisions

1. Scope gate: apply new context protocol only when `project.creation_type == "restyle"`.
2. Snapshot strategy: persist first-pass page prompt as `restyle_base_prompt_snapshot` (nullable text).
3. Transport strategy: use Gemini-style multi-turn `contents[]` for restyle edit; keep legacy path for fallback.
4. Compatibility strategy: use proactive capability check first, then reactive single retry fallback only for conversation-format rejection errors.

## 7. Data Model Changes

Add a nullable column to `pages`:

1. `restyle_base_prompt_snapshot` (`Text`, nullable)

Write rules:
1. On first successful restyle generation for a page, if empty, persist the actual prompt string.
2. Never overwrite snapshot automatically in later edits/regenerations.
3. Old projects without snapshot remain editable via degrade path.

## 8. Request Composition Design

## 8.1 Conversation Envelope (Gemini `contents[]`)

The backend builds a provider-agnostic conversation-context object first.
Gemini provider is the first adapter that serializes it to the `contents[]` wire format below.

For restyle edit, build multi-turn content with strict ordering:

1. Turn 1 (`user`, text): baseline instruction block
   - Includes:
     - style lock statement,
     - project-level `restyle_prompt` (if exists),
     - page-level `restyle_base_prompt_snapshot`.
2. Turn 2 (`user`, image parts): baseline images
   - `original slide` + original style refs (prefer all; under budget pressure keep as many as possible while preserving at least one style ref when refs exist).
3. Turn 3 (`model`, image part): current selected slide version
   - Encodes “this is the previous output state to modify”.
4. Turn 4 (`user`, text + optional images): current delta instruction
   - Includes exactly one `edit_instruction` text field,
   - plus optional current extra refs (upload/crop).

This maps requested context explicitly:
1. original slide,
2. original ref image,
3. original prompts,
4. current selected version + optional current refs + optional current modified prompts.

Turn-level invariants:
1. Turn 2 must always include `original slide` when available.
2. Turn 3 must always include `current selected slide version` when available.
3. Optional refs are prunable, required anchors are not.
4. Turn 4 text channel is single-source in v1: `edit_instruction` only.

## 8.2 Legacy Fallback Envelope

When provider cannot accept conversation `contents[]`:
1. merge baseline + current text into one strict prompt,
2. flatten refs in deterministic order:
   - `original slide`,
   - original style refs,
   - current selected version,
   - current extra refs.

Result quality is lower than true conversation mode but preserves safety and availability.

Fallback trigger policy:
1. If provider capability check says conversation unsupported, go directly to legacy mode (no conversation attempt).
2. If provider capability check says supported, attempt conversation once.
3. Only when the first attempt fails with provider-format/validation rejection, retry once in legacy mode.
4. For non-format failures (timeout, 5xx, internal errors), do not force legacy retry automatically.

## 8.3 Minimum Executable Image Set

Proceed/fail rules are deterministic:

1. A request is executable if at least one structural source image is available: `original slide` or `current selected version`.
2. If both structural source images are available, both must be included (subject to mode-specific ordering).
3. Style refs are optional for executability; missing style refs trigger degrade mode but do not force failure.
4. If both structural source images are missing or unreadable, fail the request with explicit recoverable error.

## 9. Backend Flow Changes

## 9.1 Restyle First-Pass Generation

In `restyle_images_task`:
1. build page prompt as today,
2. after successful image generation, persist `page.restyle_base_prompt_snapshot` if empty.

## 9.2 Restyle Edit Generation

In page edit flow:
1. detect `restyle` project,
2. collect baseline context from project/page fields,
3. collect mutable context from current request,
4. build conversation contents,
5. call image provider with provider-agnostic conversation payload (Gemini adapter uses native `contents[]`; unsupported adapters use legacy path),
6. save output with existing versioning pipeline.

Non-restyle edits use the same conversation + legacy-fallback provider path via `build_image_edit_context`, anchoring on the current version's `prompt_snapshot` and `ref_manifest` (degrade to legacy edit prompt when metadata is missing). See `task_manager.edit_page_image_task` and migration `024_add_generation_metadata_to_page_image_versions`.

## 9.3 Provider Capability And Retry Semantics

1. Capability source: image provider interface exposes `supports_conversation_contents` (static per provider/model config for a process lifecycle).
2. Current rollout scope: Gemini adapter sets `supports_conversation_contents=true`; other adapters default to `false` unless explicitly implemented.
2. Conversation mode is attempted only when:
   - project is `restyle`, and
   - provider reports `supports_conversation_contents=true`.
3. Retryable conversation rejection is explicitly limited to provider-format/schema errors (typical HTTP 400/422 or SDK validation errors mentioning `contents`, `parts`, `inline_data`, `schema`, `invalid_argument`).
4. Retry budget is fixed: at most one fallback retry in legacy mode.

## 10. Token And Size Budget Policy

To avoid runaway payload size and latency:

1. Define `RESTYLE_EDIT_MAX_PRUNABLE_IMAGES` with default `6`; this cap applies to prunable refs only (`style refs` + `current extra refs`).
2. Define `RESTYLE_EDIT_MAX_TOTAL_IMAGES` with default `8`; this cap applies to the final assembled image set (anchors + prunable refs).
3. Structural anchors are outside the prunable cap and are always retained when available:
   - `original slide`,
   - `current selected version`.
4. Effective total cap per request is `min(RESTYLE_EDIT_MAX_TOTAL_IMAGES, provider.max_images_per_request if exposed else RESTYLE_EDIT_MAX_TOTAL_IMAGES)`.
5. Deterministic pruning algorithm:
   - keep structural anchors first,
   - reserve at least one style-ref slot if style refs exist,
   - add remaining style refs in source order until prunable budget is exhausted,
   - if prunable budget remains, add current extra refs newest-first,
   - if no prunable budget remains after style-ref reservation, current extra refs are dropped entirely.
6. If assembled set still exceeds effective total cap after pruning, fail fast with recoverable error `CONTEXT_IMAGE_LIMIT_EXCEEDED` (no blind provider call).
7. Legacy flattened mode uses exactly the same selected image set and same selection algorithm.
8. If both structural sources are unavailable due to missing files, fail per Section 11.2.
9. text trimming priority:
   - keep `restyle_base_prompt_snapshot` intact first,
   - trim secondary explanatory text blocks,
   - never remove current `edit_instruction`.

## 11. Error Handling And Degrade Policy

## 11.1 Missing Baseline Snapshot

If `restyle_base_prompt_snapshot` is null:
1. reconstruct baseline prompt by calling the same first-pass prompt builder contract (`get_restyle_prompt(page_index, total_pages, num_style_refs, custom_prompt, preset_base_body=...)`), using best-effort current metadata and `project.style_preset_id` when present (canonical text from `style_preset_service`),
2. reconstruction argument sources are fixed:
   - `page_index = page.order_index + 1`,
   - `total_pages = count(project.pages)`,
   - `num_style_refs = max(1, len(project.style_ref_image_paths))` (fallback keeps `IMAGE 1/IMAGE 2` label contract in prompt template even when refs are currently missing),
   - `custom_prompt = project.restyle_prompt or ""`,
2. byte-for-byte equivalence with historical first-pass prompt is not required,
3. mark `degraded_context=true` in logs,
4. continue request (no hard fail).

## 11.2 Missing Original Slide / Refs

1. If original slide missing: proceed with current selected version + available style refs, mark degrade mode.
2. If current selected version missing: proceed with original slide + available style refs, mark degrade mode.
3. If style refs missing entirely: proceed with available structural source image + prompt-only constraints, mark degrade mode.
4. If both structural source images (`original slide` and `current selected version`) are missing or unreadable: return recoverable failure with explicit error details.

## 11.3 Provider Feature Gap

Provider fallback behavior is deterministic:
1. log capability decision before request (`conversation_supported=true/false`),
2. if unsupported, execute legacy mode directly,
3. if supported, try conversation once,
4. on retryable provider-format/schema rejection only, set `provider_fallback=true` and retry once in legacy mode,
5. preserve task semantics and versioning behavior in both paths.

## 12. Observability

Add structured logging fields in restyle edit generation path:

1. `context_mode`: `restyle_conversation` | `legacy_flattened`
2. `baseline_images_count`
3. `current_images_count`
4. `degraded_context`
5. `provider_fallback`
6. `snapshot_present`
7. `conversation_attempted`

These fields are required to diagnose drift and fallback frequency.

## 13. Test Strategy

## 13.1 Unit Tests

1. conversation builder includes all required baseline/current parts.
2. ordering test for turn sequence and image order.
3. snapshot fallback test when snapshot missing.
4. pruning policy test for image-cap enforcement.
5. legacy flatten fallback composition test.
6. minimum executable image-set matrix test (`original-only`, `current-only`, `both`, `neither`).
7. retryable-error classifier test for provider fallback trigger.

## 13.2 Integration Tests

1. restyle project edit with full baseline + extra refs uses conversation mode.
2. legacy restyle project (no snapshot) still edits successfully with degrade flag.
3. non-restyle project edit follows old path and behavior remains unchanged.
4. generation failure does not mutate current version pointer.

## 13.3 Regression Checks

1. page version history still increments monotonically.
2. `set-current` version behavior remains intact.
3. existing restyle batch generation behavior unaffected.

## 14. Acceptance Criteria

Eligible-call definition for this section:
1. project type is `restyle`,
2. at least one structural source image is available,
3. provider reports `supports_conversation_contents=true`.

1. For restyle edits, each request includes immutable baseline context and mutable current context by protocol.
2. Snapshot field is persisted for newly generated restyle pages.
3. Old restyle projects without snapshot remain editable via degrade path.
4. Non-restyle edit flow has no behavior regression.
5. In QA runs covering at least 3 restyle slides × 5 sequential edits each, every eligible call logs `conversation_attempted=true` and first-attempt mode `context_mode=restyle_conversation`; fallback completions must log `provider_fallback=true`.
6. Logs provide enough evidence to verify context mode and fallback/degrade conditions.

## 15. Risks And Mitigations

1. Risk: payload too large causes latency spikes.
   Mitigation: enforce image cap + deterministic pruning.
2. Risk: provider incompatibility with conversation format.
   Mitigation: strict fallback to flattened legacy mode.
3. Risk: missing historical baseline data in old projects.
   Mitigation: nullable snapshot + on-demand reconstructed baseline prompt.

## 16. Rollout Plan

1. Phase R1: schema + snapshot persistence in first-pass restyle generation.
2. Phase R2: restyle edit conversation builder + provider interface extension.
3. Phase R3: fallback path + logging + tests.
4. Phase R4: manual QA for multi-round drift and production observation (non-blocking quality metric):
   - In 3 restyle slides × 5 sequential edits, target no more than 1/15 outputs marked as style drift by both reviewers using rubric (at least 2 of 3: `palette mismatch`, `typography language mismatch`, `decorative/layout language mismatch`) versus original baseline.
