"""
Restyle edit context builder — assembles immutable baseline + mutable current context
for multi-round restyle edits with deterministic image pruning and degrade rules.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ── Errors ────────────────────────────────────────────────────


class MissingStructuralImagesError(ValueError):
    """Both original slide and current selected version are unavailable."""

    pass


class ContextImageLimitExceeded(ValueError):
    """Assembled image set exceeds total cap after pruning."""

    pass


# ── Data model ────────────────────────────────────────────────


@dataclass
class RestyleEditContext:
    """Provider-agnostic restyle edit context payload."""

    conversation_contents: list  # Multi-turn content for conversation providers
    legacy_prompt: str  # Flattened prompt for fallback providers
    legacy_ref_images: list  # Flattened image path list for fallback
    degraded_context: bool  # True if any baseline component missing
    baseline_images_count: int  # Images from baseline bucket
    current_images_count: int  # Images from current round bucket
    snapshot_source: str = "persisted"  # persisted | reconstructed
    turns_summary: list = field(default_factory=list)
    image_manifest: list = field(default_factory=list)


# ── Snapshot reconstruction ───────────────────────────────────


def reconstruct_base_prompt_snapshot(
    page_index: int,
    total_pages: int,
    num_style_refs: int,
    custom_prompt: str,
    style_preset_id: str | None = None,
) -> str:
    """Best-effort reconstruction when page snapshot is null."""
    from services.prompts import get_restyle_prompt
    from services.style_preset_service import (
        resolve_preset_prompt_body_for_flow,
    )

    preset_base_body, effective_custom = resolve_preset_prompt_body_for_flow(
        style_preset_id,
        "restyle",
        custom_prompt or "",
    )

    return get_restyle_prompt(
        page_index=page_index,
        total_pages=total_pages,
        num_style_refs=max(1, num_style_refs),
        custom_prompt=effective_custom,
        preset_base_body=preset_base_body,
    )


# ── Image selection / pruning ─────────────────────────────────


def _select_images(
    *,
    original_slide_path: Optional[str],
    style_ref_paths: List[str],
    current_selected_path: Optional[str],
    current_extra_ref_paths: List[str],
    prunable_cap: int,
    total_cap: int,
) -> tuple:
    """
    Deterministic image selection with pruning.

    Returns (anchors, selected_style_refs, selected_extras, baseline_count, current_count, image_manifest).
    Raises MissingStructuralImagesError / ContextImageLimitExceeded on violations.
    """
    # Structural anchors — always retained when available
    anchors: List[str] = []
    if original_slide_path:
        anchors.append(original_slide_path)
    if current_selected_path:
        anchors.append(current_selected_path)

    if not anchors:
        raise MissingStructuralImagesError(
            "Missing both original slide and current selected version"
        )

    # Prunable selection
    budget = prunable_cap

    # Reserve >=1 style-ref slot when style refs exist
    selected_style_refs: List[str] = []
    if style_ref_paths:
        selected_style_refs.append(style_ref_paths[0])
        budget -= 1
        # Fill remaining style refs in source order
        for ref in style_ref_paths[1:]:
            if budget <= 0:
                break
            selected_style_refs.append(ref)
            budget -= 1

    # Fill extras newest-first (last in list = newest)
    selected_extras: List[str] = []
    if budget > 0 and current_extra_ref_paths:
        reversed_extras = list(reversed(current_extra_ref_paths))
        for extra in reversed_extras:
            if budget <= 0:
                break
            selected_extras.append(extra)
            budget -= 1

    total = len(anchors) + len(selected_style_refs) + len(selected_extras)
    if total > total_cap:
        raise ContextImageLimitExceeded(
            f"Assembled image set ({total}) exceeds total cap ({total_cap})"
        )

    baseline_count = (1 if original_slide_path else 0) + len(selected_style_refs)
    current_count = (1 if current_selected_path else 0) + len(selected_extras)

    image_manifest = _build_image_manifest(
        original_slide_path=original_slide_path,
        style_ref_paths=style_ref_paths,
        current_selected_path=current_selected_path,
        current_extra_ref_paths=current_extra_ref_paths,
        selected_style_refs=selected_style_refs,
        selected_extras=selected_extras,
    )

    return (
        anchors,
        selected_style_refs,
        selected_extras,
        baseline_count,
        current_count,
        image_manifest,
    )


def _build_image_manifest(
    *,
    original_slide_path: Optional[str],
    style_ref_paths: List[str],
    current_selected_path: Optional[str],
    current_extra_ref_paths: List[str],
    selected_style_refs: List[str],
    selected_extras: List[str],
) -> List[dict]:
    """Build a deterministic manifest describing selected and pruned images."""
    manifest: List[dict] = []

    if original_slide_path:
        manifest.append(
            {
                "kind": "original_slide",
                "bucket": "baseline",
                "path": original_slide_path,
                "selected": True,
                "selection_reason": "anchor",
            }
        )

    for idx, path in enumerate(style_ref_paths):
        manifest.append(
            {
                "kind": "style_ref",
                "bucket": "baseline",
                "path": path,
                "selected": path in selected_style_refs,
                "selection_reason": (
                    "reserved_style_ref"
                    if path in selected_style_refs and idx == 0
                    else (
                        "kept_style_ref"
                        if path in selected_style_refs
                        else "pruned_budget"
                    )
                ),
            }
        )

    if current_selected_path:
        manifest.append(
            {
                "kind": "current_selected",
                "bucket": "current",
                "path": current_selected_path,
                "selected": True,
                "selection_reason": "anchor",
            }
        )

    for path in current_extra_ref_paths:
        manifest.append(
            {
                "kind": "current_extra_ref",
                "bucket": "current",
                "path": path,
                "selected": path in selected_extras,
                "selection_reason": (
                    "current_extra_ref" if path in selected_extras else "pruned_budget"
                ),
            }
        )

    return manifest


def _build_generic_image_manifest(
    *,
    baseline_ref_paths: List[str],
    current_selected_path: Optional[str],
    current_extra_ref_paths: List[str],
    selected_baseline_refs: List[str],
    selected_extras: List[str],
) -> List[dict]:
    """Build manifest for non-restyle generation/edit contexts."""
    manifest: List[dict] = []
    for path in baseline_ref_paths:
        manifest.append(
            {
                "kind": "generation_ref",
                "bucket": "baseline",
                "path": path,
                "selected": path in selected_baseline_refs,
                "selection_reason": (
                    "kept_generation_ref"
                    if path in selected_baseline_refs
                    else "pruned_budget"
                ),
            }
        )
    if current_selected_path:
        manifest.append(
            {
                "kind": "current_selected",
                "bucket": "current",
                "path": current_selected_path,
                "selected": True,
                "selection_reason": "anchor",
            }
        )
    for path in current_extra_ref_paths:
        manifest.append(
            {
                "kind": "current_extra_ref",
                "bucket": "current",
                "path": path,
                "selected": path in selected_extras,
                "selection_reason": (
                    "current_extra_ref" if path in selected_extras else "pruned_budget"
                ),
            }
        )
    return manifest


def _build_turns_summary(contents: List[dict]) -> List[dict]:
    """Summarize turns for fast inspection/logging."""
    summary = []
    for index, turn in enumerate(contents, 1):
        text_len = 0
        image_count = 0
        for part in turn.get("parts", []):
            if "text" in part:
                text_len += len(part["text"])
            if "image_path" in part:
                image_count += 1
        summary.append(
            {
                "index": index,
                "role": turn.get("role"),
                "text_len": text_len,
                "image_count": image_count,
            }
        )
    return summary


# ── Conversation contents builder ─────────────────────────────


_STYLE_LOCK = (
    "STYLE LOCK: You must maintain visual consistency with the original style "
    "throughout all modifications. Preserve the color scheme, typography, "
    "decorative elements, and layout language from the baseline."
)


def _build_conversation_contents(
    *,
    baseline_text: str,
    original_slide_path: Optional[str],
    selected_style_refs: List[str],
    current_selected_path: Optional[str],
    edit_instruction: str,
    selected_extras: List[str],
) -> list:
    """Build provider-agnostic multi-turn conversation contents."""
    turns: list = []

    # Turn 1 (user, text): baseline instruction block
    turns.append(
        {
            "role": "user",
            "parts": [{"text": baseline_text}],
        }
    )

    # Turn 2 (user, images): baseline images, matching first-pass prompt order:
    # style/base template refs first, then original slide content.
    turn2_parts: list = []
    for ref in selected_style_refs:
        turn2_parts.append({"image_path": ref})
    if original_slide_path:
        turn2_parts.append({"image_path": original_slide_path})
    if turn2_parts:
        turns.append({"role": "user", "parts": turn2_parts})

    # Turn 3 (user, image): current selected slide version.
    # This is user-supplied context, not a prior SDK model response. Using a
    # synthetic model turn with Gemini 3 image models triggers thought-signature
    # validation, because only real model outputs carry those signatures.
    if current_selected_path:
        turns.append(
            {
                "role": "user",
                "parts": [{"image_path": current_selected_path}],
            }
        )

    # Turn 4 (user, text + optional images): current delta instruction
    turn4_parts: list = [{"text": edit_instruction}]
    for extra in selected_extras:
        turn4_parts.append({"image_path": extra})
    turns.append({"role": "user", "parts": turn4_parts})

    return turns


# ── Legacy fallback builder ───────────────────────────────────


def _build_legacy_prompt(
    baseline_text: str,
    edit_instruction: str,
) -> str:
    """Merge baseline + current text into single prompt for legacy providers."""
    return f"{baseline_text}\n\n---\n\nEdit instruction: {edit_instruction}"


def _build_legacy_ref_images(
    *,
    original_slide_path: Optional[str],
    selected_style_refs: List[str],
    current_selected_path: Optional[str],
    selected_extras: List[str],
) -> List[str]:
    """Flatten images in deterministic order for legacy providers."""
    images: List[str] = []
    images.extend(selected_style_refs)
    if original_slide_path:
        images.append(original_slide_path)
    if current_selected_path:
        images.append(current_selected_path)
    images.extend(selected_extras)
    return images


# ── Main entry point ──────────────────────────────────────────


def build_restyle_edit_context(
    *,
    original_slide_path: Optional[str],
    style_ref_paths: List[str],
    restyle_base_prompt_snapshot: Optional[str],
    restyle_prompt: str,
    style_preset_id: Optional[str] = None,
    current_selected_path: Optional[str],
    edit_instruction: str,
    current_extra_ref_paths: Optional[List[str]] = None,
    page_index: int = 1,
    total_pages: int = 1,
    prunable_cap: int = 6,
    total_cap: int = 8,
) -> RestyleEditContext:
    """
    Build restyle edit context from immutable baseline + mutable current buckets.

    Raises:
        MissingStructuralImagesError: both structural source images unavailable.
        ContextImageLimitExceeded: assembled set exceeds total cap after pruning.
    """
    extras = current_extra_ref_paths or []
    degraded = False
    snapshot_source = "persisted"

    # Snapshot resolution
    snapshot = restyle_base_prompt_snapshot
    if not snapshot:
        snapshot = reconstruct_base_prompt_snapshot(
            page_index=page_index,
            total_pages=total_pages,
            num_style_refs=len(style_ref_paths),
            custom_prompt=restyle_prompt,
            style_preset_id=style_preset_id,
        )
        degraded = True
        snapshot_source = "reconstructed"
        logger.info(
            "restyle_edit_context: snapshot missing, using reconstruction",
            extra={"degraded_context": True},
        )

    # Degrade if structural images partially missing
    if not original_slide_path or not current_selected_path:
        degraded = True

    # Degrade if style refs missing
    if not style_ref_paths:
        degraded = True

    # Image selection + pruning
    (
        anchors,
        selected_style_refs,
        selected_extras,
        baseline_count,
        current_count,
        image_manifest,
    ) = _select_images(
        original_slide_path=original_slide_path,
        style_ref_paths=style_ref_paths,
        current_selected_path=current_selected_path,
        current_extra_ref_paths=extras,
        prunable_cap=prunable_cap,
        total_cap=total_cap,
    )

    # Assemble baseline text block
    parts = [_STYLE_LOCK]
    if restyle_prompt:
        parts.append(f"Project restyle instruction: {restyle_prompt}")
    parts.append(f"Original generation prompt:\n{snapshot}")
    baseline_text = "\n\n".join(parts)

    # Build conversation contents
    conversation = _build_conversation_contents(
        baseline_text=baseline_text,
        original_slide_path=original_slide_path,
        selected_style_refs=selected_style_refs,
        current_selected_path=current_selected_path,
        edit_instruction=edit_instruction,
        selected_extras=selected_extras,
    )

    # Build legacy fallback
    legacy_prompt = _build_legacy_prompt(baseline_text, edit_instruction)
    legacy_images = _build_legacy_ref_images(
        original_slide_path=original_slide_path,
        selected_style_refs=selected_style_refs,
        current_selected_path=current_selected_path,
        selected_extras=selected_extras,
    )
    turns_summary = _build_turns_summary(conversation)

    return RestyleEditContext(
        conversation_contents=conversation,
        legacy_prompt=legacy_prompt,
        legacy_ref_images=legacy_images,
        degraded_context=degraded,
        baseline_images_count=baseline_count,
        current_images_count=current_count,
        snapshot_source=snapshot_source,
        turns_summary=turns_summary,
        image_manifest=image_manifest,
    )


def build_image_edit_context(
    *,
    baseline_prompt_snapshot: Optional[str],
    baseline_ref_paths: Optional[List[str]],
    current_selected_path: Optional[str],
    edit_instruction: str,
    original_description: Optional[str] = None,
    current_extra_ref_paths: Optional[List[str]] = None,
    prunable_cap: int = 6,
    total_cap: int = 8,
) -> RestyleEditContext:
    """
    Build unified image edit context for ordinary/translate edit flows.

    Old versions may not have prompt metadata; in that case the builder degrades
    to the legacy edit prompt while still using the current image as anchor.
    """
    from services.prompts import get_image_edit_prompt

    baseline_refs = baseline_ref_paths or []
    extras = current_extra_ref_paths or []
    degraded = False
    snapshot_source = "persisted"

    if not current_selected_path:
        raise MissingStructuralImagesError("Missing current selected version")

    baseline_text = baseline_prompt_snapshot
    if not baseline_text:
        baseline_text = get_image_edit_prompt(
            edit_instruction=edit_instruction,
            original_description=original_description,
        )
        degraded = True
        snapshot_source = "fallback"

    budget = prunable_cap
    selected_baseline_refs: List[str] = []
    for ref in baseline_refs:
        if budget <= 0:
            break
        selected_baseline_refs.append(ref)
        budget -= 1

    selected_extras: List[str] = []
    if budget > 0 and extras:
        for extra in reversed(extras):
            if budget <= 0:
                break
            selected_extras.append(extra)
            budget -= 1

    total = 1 + len(selected_baseline_refs) + len(selected_extras)
    if total > total_cap:
        raise ContextImageLimitExceeded(
            f"Assembled image set ({total}) exceeds total cap ({total_cap})"
        )

    if len(selected_baseline_refs) < len(baseline_refs) or len(selected_extras) < len(
        extras
    ):
        degraded = True

    baseline_parts = [
        "BASELINE CONTEXT: The following prompt and reference images describe the current slide's original generation context.",
        f"Original generation prompt:\n{baseline_text}",
    ]
    baseline_block = "\n\n".join(baseline_parts)

    conversation = _build_conversation_contents(
        baseline_text=baseline_block,
        original_slide_path=None,
        selected_style_refs=selected_baseline_refs,
        current_selected_path=current_selected_path,
        edit_instruction=edit_instruction,
        selected_extras=selected_extras,
    )
    legacy_prompt = _build_legacy_prompt(baseline_block, edit_instruction)
    legacy_images = _build_legacy_ref_images(
        original_slide_path=None,
        selected_style_refs=selected_baseline_refs,
        current_selected_path=current_selected_path,
        selected_extras=selected_extras,
    )
    image_manifest = _build_generic_image_manifest(
        baseline_ref_paths=baseline_refs,
        current_selected_path=current_selected_path,
        current_extra_ref_paths=extras,
        selected_baseline_refs=selected_baseline_refs,
        selected_extras=selected_extras,
    )

    return RestyleEditContext(
        conversation_contents=conversation,
        legacy_prompt=legacy_prompt,
        legacy_ref_images=legacy_images,
        degraded_context=degraded,
        baseline_images_count=len(selected_baseline_refs),
        current_images_count=1 + len(selected_extras),
        snapshot_source=snapshot_source,
        turns_summary=_build_turns_summary(conversation),
        image_manifest=image_manifest,
    )


# ── Retryable error classifier ───────────────────────────────

# Patterns indicating provider-format/schema rejection (retryable via legacy fallback)
_RETRYABLE_PATTERNS = re.compile(
    r"(?:^|\b)(?:400|422|contents|parts|inline_data|schema|invalid_argument)(?:\b|$)",
    re.IGNORECASE,
)

# Patterns indicating non-retryable infrastructure errors
_NON_RETRYABLE_PATTERNS = re.compile(
    r"(?:^|\b)(?:500|503|timed?\s*out|timeout|internal\s+server|service\s+unavailable)(?:\b|$)",
    re.IGNORECASE,
)


def is_retryable_conversation_error(error: Exception) -> bool:
    """
    Classify whether a conversation-mode error is retryable via legacy fallback.

    Only format/schema errors (400, 422, validation) are retryable.
    Timeout, 5xx, and generic errors are NOT retryable.
    """
    msg = str(error)
    # Non-retryable takes precedence
    if _NON_RETRYABLE_PATTERNS.search(msg):
        return False
    return bool(_RETRYABLE_PATTERNS.search(msg))
