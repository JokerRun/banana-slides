"""
Restyle edit context — unit tests (Task 1 + Task 3)
"""
import pytest

from services.restyle_edit_context import (
    build_restyle_edit_context,
    reconstruct_base_prompt_snapshot,
    is_retryable_conversation_error,
    MissingStructuralImagesError,
    ContextImageLimitExceeded,
    RestyleEditContext,
)


# ── Task 1: schema & config baseline ──────────────────────────


class TestPageRestyleSnapshot:
    """Page model restyle_base_prompt_snapshot field tests"""

    def test_page_has_restyle_base_prompt_snapshot_field(self, db_session):
        from models import Page
        page = Page(project_id='p1', order_index=0, restyle_base_prompt_snapshot='BASE PROMPT')
        assert page.restyle_base_prompt_snapshot == 'BASE PROMPT'

    def test_page_to_dict_includes_snapshot(self, db_session):
        from models import Page
        page = Page(project_id='p1', order_index=0, restyle_base_prompt_snapshot='SNAP')
        data = page.to_dict()
        assert 'restyle_base_prompt_snapshot' in data
        assert data['restyle_base_prompt_snapshot'] == 'SNAP'


class TestRestyleEditConfig:
    """Config defaults for restyle edit caps"""

    def test_restyle_edit_caps_default_from_config(self):
        from config import Config
        assert Config.RESTYLE_EDIT_MAX_PRUNABLE_IMAGES == 6
        assert Config.RESTYLE_EDIT_MAX_TOTAL_IMAGES == 8


# ── Task 3: context builder ───────────────────────────────────


class TestBuildRestyleEditContext:
    """Tests for build_restyle_edit_context"""

    def test_full_context_all_components_present(self):
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/original.png',
            style_ref_paths=['/fake/ref1.png', '/fake/ref2.png'],
            restyle_base_prompt_snapshot='BASE PROMPT SNAPSHOT',
            restyle_prompt='custom style instruction',
            current_selected_path='/fake/current.png',
            edit_instruction='make it blue',
        )
        assert isinstance(ctx, RestyleEditContext)
        assert ctx.degraded_context is False
        assert ctx.baseline_images_count >= 1
        assert ctx.current_images_count >= 1
        # 4 turns: baseline text, baseline images, model output, delta
        assert len(ctx.conversation_contents) == 4
        assert ctx.conversation_contents[0]['role'] == 'user'
        assert ctx.conversation_contents[2]['role'] == 'model'

    def test_minimum_executable_original_only(self):
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/original.png',
            style_ref_paths=[],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path=None,
            edit_instruction='edit me',
        )
        assert ctx.degraded_context is True

    def test_minimum_executable_current_only(self):
        ctx = build_restyle_edit_context(
            original_slide_path=None,
            style_ref_paths=[],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path='/fake/current.png',
            edit_instruction='edit me',
        )
        assert ctx.degraded_context is True

    def test_missing_both_structural_raises(self):
        with pytest.raises(MissingStructuralImagesError):
            build_restyle_edit_context(
                original_slide_path=None,
                style_ref_paths=['/fake/ref.png'],
                restyle_base_prompt_snapshot='SNAP',
                restyle_prompt='',
                current_selected_path=None,
                edit_instruction='edit me',
            )

    def test_total_cap_exceeded_raises(self):
        with pytest.raises(ContextImageLimitExceeded):
            build_restyle_edit_context(
                original_slide_path='/fake/orig.png',
                style_ref_paths=[f'/fake/ref{i}.png' for i in range(10)],
                restyle_base_prompt_snapshot='SNAP',
                restyle_prompt='',
                current_selected_path='/fake/cur.png',
                edit_instruction='edit',
                prunable_cap=10,
                total_cap=3,  # Too small for 2 anchors + style refs
            )

    def test_pruning_preserves_at_least_one_style_ref(self):
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/orig.png',
            style_ref_paths=['/fake/ref1.png', '/fake/ref2.png', '/fake/ref3.png'],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path='/fake/cur.png',
            edit_instruction='edit',
            prunable_cap=1,  # Only room for 1 prunable
            total_cap=8,
        )
        # 2 anchors + 1 style ref = 3
        assert len(ctx.legacy_ref_images) == 3

    def test_pruning_fills_extras_after_style_refs(self):
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/orig.png',
            style_ref_paths=['/fake/ref1.png'],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path='/fake/cur.png',
            edit_instruction='edit',
            current_extra_ref_paths=['/fake/extra1.png', '/fake/extra2.png'],
            prunable_cap=2,  # 1 style ref + 1 extra
            total_cap=8,
        )
        # 2 anchors + 1 style ref + 1 extra = 4
        assert len(ctx.legacy_ref_images) == 4

    def test_pruning_extras_newest_first(self):
        """Extra refs are added newest-first (last in list = newest)"""
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/orig.png',
            style_ref_paths=[],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path='/fake/cur.png',
            edit_instruction='edit',
            current_extra_ref_paths=['/fake/old.png', '/fake/mid.png', '/fake/new.png'],
            prunable_cap=2,  # only room for 2
            total_cap=8,
        )
        # anchors + 2 extras (newest first: new, mid)
        selected_extras = [p for p in ctx.legacy_ref_images
                           if p not in ('/fake/orig.png', '/fake/cur.png')]
        assert '/fake/new.png' in selected_extras
        assert '/fake/mid.png' in selected_extras
        assert '/fake/old.png' not in selected_extras

    def test_legacy_ref_images_deterministic_order(self):
        """Legacy images follow: original, style refs, current selected, extras"""
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/orig.png',
            style_ref_paths=['/fake/ref1.png'],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path='/fake/cur.png',
            edit_instruction='edit',
            current_extra_ref_paths=['/fake/extra.png'],
            prunable_cap=6,
            total_cap=8,
        )
        assert ctx.legacy_ref_images == [
            '/fake/orig.png',
            '/fake/ref1.png',
            '/fake/cur.png',
            '/fake/extra.png',
        ]

    def test_conversation_turn1_contains_baseline_text(self):
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/orig.png',
            style_ref_paths=['/fake/ref.png'],
            restyle_base_prompt_snapshot='MY SNAPSHOT',
            restyle_prompt='my custom prompt',
            current_selected_path='/fake/cur.png',
            edit_instruction='change color',
        )
        turn1 = ctx.conversation_contents[0]
        assert turn1['role'] == 'user'
        text_parts = [p['text'] for p in turn1['parts'] if 'text' in p]
        combined = ' '.join(text_parts)
        assert 'MY SNAPSHOT' in combined
        assert 'my custom prompt' in combined

    def test_conversation_turn4_contains_edit_instruction(self):
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/orig.png',
            style_ref_paths=['/fake/ref.png'],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path='/fake/cur.png',
            edit_instruction='make it red',
        )
        turn4 = ctx.conversation_contents[3]
        assert turn4['role'] == 'user'
        text_parts = [p['text'] for p in turn4['parts'] if 'text' in p]
        assert any('make it red' in t for t in text_parts)

    def test_no_current_selected_skips_turn3(self):
        """When current selected is missing, conversation has 3 turns (skip model turn)"""
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/orig.png',
            style_ref_paths=['/fake/ref.png'],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path=None,
            edit_instruction='edit me',
        )
        # No model turn
        roles = [t['role'] for t in ctx.conversation_contents]
        assert 'model' not in roles

    def test_no_original_slide_skips_from_turn2(self):
        """When original slide missing, Turn 2 only has style refs"""
        ctx = build_restyle_edit_context(
            original_slide_path=None,
            style_ref_paths=['/fake/ref.png'],
            restyle_base_prompt_snapshot='SNAP',
            restyle_prompt='',
            current_selected_path='/fake/cur.png',
            edit_instruction='edit me',
        )
        turn2 = [t for t in ctx.conversation_contents
                 if t['role'] == 'user' and any('image_path' in p for p in t['parts'])]
        if turn2:
            image_paths = [p['image_path'] for p in turn2[0]['parts'] if 'image_path' in p]
            assert '/fake/orig.png' not in image_paths


class TestReconstructBasePromptSnapshot:
    """Tests for snapshot reconstruction"""

    def test_reconstruct_returns_string(self):
        result = reconstruct_base_prompt_snapshot(
            page_index=1, total_pages=5, num_style_refs=2, custom_prompt='',
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_reconstruct_includes_page_info(self):
        result = reconstruct_base_prompt_snapshot(
            page_index=3, total_pages=10, num_style_refs=1, custom_prompt='my style',
        )
        assert '3' in result or 'Page' in result

    def test_reconstruct_with_zero_refs_uses_min_one(self):
        result = reconstruct_base_prompt_snapshot(
            page_index=1, total_pages=1, num_style_refs=0, custom_prompt='',
        )
        assert 'IMAGE' in result


class TestSnapshotFallbackInContext:
    """Test that missing snapshot triggers reconstruction and degrade"""

    def test_missing_snapshot_uses_reconstruction(self):
        ctx = build_restyle_edit_context(
            original_slide_path='/fake/orig.png',
            style_ref_paths=['/fake/ref.png'],
            restyle_base_prompt_snapshot=None,
            restyle_prompt='custom style',
            current_selected_path='/fake/cur.png',
            edit_instruction='edit me',
            page_index=2,
            total_pages=5,
        )
        assert ctx.degraded_context is True
        assert len(ctx.conversation_contents) >= 3


class TestRetryableConversationError:
    """Tests for is_retryable_conversation_error classifier"""

    def test_400_error_is_retryable(self):
        assert is_retryable_conversation_error(
            Exception("400 Bad Request: invalid contents format")) is True

    def test_422_error_is_retryable(self):
        assert is_retryable_conversation_error(
            Exception("422 invalid_argument: schema validation failed")) is True

    def test_schema_error_is_retryable(self):
        assert is_retryable_conversation_error(
            Exception("inline_data format not supported")) is True

    def test_parts_error_is_retryable(self):
        assert is_retryable_conversation_error(
            Exception("Invalid parts in contents")) is True

    def test_timeout_error_is_not_retryable(self):
        assert is_retryable_conversation_error(
            Exception("Request timed out after 300s")) is False

    def test_500_error_is_not_retryable(self):
        assert is_retryable_conversation_error(
            Exception("500 Internal Server Error")) is False

    def test_503_error_is_not_retryable(self):
        assert is_retryable_conversation_error(
            Exception("503 Service Unavailable")) is False

    def test_generic_error_is_not_retryable(self):
        assert is_retryable_conversation_error(
            Exception("something went wrong")) is False
