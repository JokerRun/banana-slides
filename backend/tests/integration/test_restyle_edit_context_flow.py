"""
Integration tests for restyle edit conversation context flow (Task 4).

Tests the wiring: edit_page_image_task → restyle detection → conversation context → provider.
"""

import os
import json
import tempfile
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from PIL import Image

import sys
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))


# ── Helpers ───────────────────────────────────────────────────


def _create_test_image(color='red', size=(100, 100)):
    """Create a temp PNG file and return its path."""
    img = Image.new('RGB', size, color)
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    img.save(tmp, format='PNG')
    tmp.close()
    return tmp.name


# ── Tests ─────────────────────────────────────────────────────


class TestRestyleEditConversationMode:
    """Restyle project edits should use conversation context when provider supports it."""

    def test_restyle_edit_calls_conversation_path(self, app, db_session):
        """Restyle project edit should call edit_restyle_image_with_context."""
        with app.app_context():
            from models import db, Project, Page, Task, User
            from services.task_manager import edit_page_image_task

            # Setup data
            user = User(display_name='Test', is_active=True)
            db.session.add(user)
            db.session.commit()

            project = Project(
                idea_prompt='test',
                creation_type='restyle',
                owner_id=user.id,
                restyle_prompt='apply dark style',
            )
            db.session.add(project)
            db.session.commit()

            orig_path = _create_test_image('red')
            cur_path = _create_test_image('blue')

            page = Page(
                project_id=project.id,
                order_index=0,
                original_slide_image_path=orig_path,
                generated_image_path=cur_path,
                status='COMPLETED',
                restyle_base_prompt_snapshot='ORIGINAL PROMPT SNAPSHOT',
            )
            db.session.add(page)
            db.session.commit()

            task = Task(
                project_id=project.id,
                owner_id=user.id,
                task_type='EDIT_PAGE_IMAGE',
                status='PENDING',
            )
            db.session.add(task)
            db.session.commit()

            # Mock AI service — edit_restyle_image_with_context should be called
            mock_ai = MagicMock()
            result_img = Image.new('RGB', (1920, 1080), 'green')
            mock_ai.edit_restyle_image_with_context.return_value = result_img
            # Legacy path should NOT be called
            mock_ai.edit_image.return_value = None

            mock_file_service = MagicMock()
            mock_file_service.get_absolute_path.side_effect = lambda p: p

            try:
                with patch('services.task_manager.save_image_with_version',
                           return_value=(cur_path, 2)):
                    edit_page_image_task(
                        task.id, project.id, page.id,
                        'make it brighter',
                        mock_ai, mock_file_service,
                        '16:9', '2K', None, None, None, app
                    )

                # Verify conversation path was called
                mock_ai.edit_restyle_image_with_context.assert_called_once()
                # Verify legacy path was NOT called
                mock_ai.edit_image.assert_not_called()

                # Verify task completed
                db.session.expire_all()
                task = Task.query.get(task.id)
                assert task.status == 'COMPLETED'
            finally:
                os.unlink(orig_path)
                os.unlink(cur_path)

    def test_non_restyle_edit_uses_legacy_path(self, app, db_session):
        """Non-restyle (idea) project edit should use legacy edit_image path."""
        with app.app_context():
            from models import db, Project, Page, Task, User
            from services.task_manager import edit_page_image_task

            user = User(display_name='Test', is_active=True)
            db.session.add(user)
            db.session.commit()

            project = Project(
                idea_prompt='test idea',
                creation_type='idea',
                owner_id=user.id,
            )
            db.session.add(project)
            db.session.commit()

            cur_path = _create_test_image('blue')

            page = Page(
                project_id=project.id,
                order_index=0,
                generated_image_path=cur_path,
                status='COMPLETED',
            )
            db.session.add(page)
            db.session.commit()

            task = Task(
                project_id=project.id,
                owner_id=user.id,
                task_type='EDIT_PAGE_IMAGE',
                status='PENDING',
            )
            db.session.add(task)
            db.session.commit()

            mock_ai = MagicMock()
            result_img = Image.new('RGB', (1920, 1080), 'green')
            mock_ai.edit_image.return_value = result_img

            mock_file_service = MagicMock()
            mock_file_service.get_absolute_path.return_value = cur_path

            try:
                with patch('services.task_manager.save_image_with_version',
                           return_value=(cur_path, 2)):
                    edit_page_image_task(
                        task.id, project.id, page.id,
                        'make it brighter',
                        mock_ai, mock_file_service,
                        '16:9', '2K', 'original desc', None, None, app
                    )

                # Verify legacy path was used
                mock_ai.edit_image.assert_called_once()
                # Verify conversation path was NOT used
                mock_ai.edit_restyle_image_with_context.assert_not_called()

                # Verify task completed
                db.session.expire_all()
                task = Task.query.get(task.id)
                assert task.status == 'COMPLETED'
            finally:
                os.unlink(cur_path)

    def test_restyle_edit_context_receives_correct_params(self, app, db_session):
        """Verify build_restyle_edit_context is called with correct parameters."""
        with app.app_context():
            from models import db, Project, Page, Task, User
            from services.task_manager import edit_page_image_task
            from services.restyle_edit_context import RestyleEditContext

            user = User(display_name='Test', is_active=True)
            db.session.add(user)
            db.session.commit()

            project = Project(
                idea_prompt='test',
                creation_type='restyle',
                owner_id=user.id,
                restyle_prompt='corporate blue',
            )
            project.set_style_ref_image_paths(['/path/to/style1.png'])
            db.session.add(project)
            db.session.commit()

            orig_path = _create_test_image('red')
            cur_path = _create_test_image('blue')

            page = Page(
                project_id=project.id,
                order_index=2,
                original_slide_image_path=orig_path,
                generated_image_path=cur_path,
                status='COMPLETED',
                restyle_base_prompt_snapshot='SNAPSHOT TEXT',
            )
            db.session.add(page)
            # Add a second page so total_pages > 1
            page2 = Page(
                project_id=project.id,
                order_index=1,
                status='DRAFT',
            )
            db.session.add(page2)
            db.session.commit()

            task = Task(
                project_id=project.id,
                owner_id=user.id,
                task_type='EDIT_PAGE_IMAGE',
                status='PENDING',
            )
            db.session.add(task)
            db.session.commit()

            mock_ai = MagicMock()
            result_img = Image.new('RGB', (1920, 1080), 'green')
            mock_ai.edit_restyle_image_with_context.return_value = result_img

            mock_file_service = MagicMock()
            mock_file_service.get_absolute_path.side_effect = lambda p: p

            captured_ctx_kwargs = {}

            def mock_build_ctx(**kwargs):
                captured_ctx_kwargs.update(kwargs)
                return RestyleEditContext(
                    conversation_contents=[],
                    legacy_prompt='fallback',
                    legacy_ref_images=[],
                    degraded_context=False,
                    baseline_images_count=1,
                    current_images_count=1,
                )

            try:
                with patch('services.task_manager.save_image_with_version',
                           return_value=(cur_path, 2)), \
                     patch('services.restyle_edit_context.build_restyle_edit_context',
                           side_effect=mock_build_ctx):
                    edit_page_image_task(
                        task.id, project.id, page.id,
                        'change the title',
                        mock_ai, mock_file_service,
                        '16:9', '2K', None, None, None, app
                    )

                # Verify context builder received correct params
                assert captured_ctx_kwargs['restyle_base_prompt_snapshot'] == 'SNAPSHOT TEXT'
                assert captured_ctx_kwargs['restyle_prompt'] == 'corporate blue'
                assert captured_ctx_kwargs['edit_instruction'] == 'change the title'
                assert captured_ctx_kwargs['page_index'] == 3  # 0-indexed 2 → 1-indexed 3
                assert captured_ctx_kwargs['total_pages'] == 2
                assert captured_ctx_kwargs['original_slide_path'] == orig_path
                assert captured_ctx_kwargs['current_selected_path'] == cur_path
            finally:
                os.unlink(orig_path)
                os.unlink(cur_path)


class TestAIServiceRestyleEdit:
    """Test AIService.edit_restyle_image_with_context method."""

    def test_conversation_mode_success(self, app):
        """Provider supports conversation → should use it and return image."""
        with app.app_context():
            from services.ai_service import AIService
            from services.restyle_edit_context import RestyleEditContext

            mock_text = MagicMock()
            mock_image = MagicMock()
            mock_image.supports_conversation_contents = True
            result_img = Image.new('RGB', (1920, 1080), 'green')
            mock_image.generate_image_from_conversation.return_value = result_img

            ai = AIService(text_provider=mock_text, image_provider=mock_image)

            ctx = RestyleEditContext(
                conversation_contents=[
                    {'role': 'user', 'parts': [{'text': 'hello'}]},
                ],
                legacy_prompt='fallback prompt',
                legacy_ref_images=[],
                degraded_context=False,
                baseline_images_count=1,
                current_images_count=1,
            )

            result = ai.edit_restyle_image_with_context(ctx, '16:9', '2K')

            assert result == result_img
            mock_image.generate_image_from_conversation.assert_called_once()
            mock_image.generate_image.assert_not_called()

    def test_conversation_fallback_on_retryable_error(self, app):
        """Retryable error (400) → should fall back to legacy generate_image."""
        with app.app_context():
            from services.ai_service import AIService
            from services.restyle_edit_context import RestyleEditContext

            mock_text = MagicMock()
            mock_image = MagicMock()
            mock_image.supports_conversation_contents = True
            mock_image.generate_image_from_conversation.side_effect = Exception(
                "400 Bad Request: invalid_argument contents"
            )
            result_img = Image.new('RGB', (1920, 1080), 'green')
            mock_image.generate_image.return_value = result_img

            ai = AIService(text_provider=mock_text, image_provider=mock_image)

            ctx = RestyleEditContext(
                conversation_contents=[
                    {'role': 'user', 'parts': [{'text': 'hello'}]},
                ],
                legacy_prompt='fallback prompt',
                legacy_ref_images=[],
                degraded_context=False,
                baseline_images_count=1,
                current_images_count=1,
            )

            result = ai.edit_restyle_image_with_context(ctx, '16:9', '2K')

            assert result == result_img
            mock_image.generate_image_from_conversation.assert_called_once()
            mock_image.generate_image.assert_called_once()

    def test_conversation_non_retryable_error_raises(self, app):
        """Non-retryable error (timeout/5xx) → should NOT fall back, should raise."""
        with app.app_context():
            from services.ai_service import AIService
            from services.restyle_edit_context import RestyleEditContext

            mock_text = MagicMock()
            mock_image = MagicMock()
            mock_image.supports_conversation_contents = True
            mock_image.generate_image_from_conversation.side_effect = Exception(
                "503 service unavailable"
            )

            ai = AIService(text_provider=mock_text, image_provider=mock_image)

            ctx = RestyleEditContext(
                conversation_contents=[
                    {'role': 'user', 'parts': [{'text': 'hello'}]},
                ],
                legacy_prompt='fallback prompt',
                legacy_ref_images=[],
                degraded_context=False,
                baseline_images_count=1,
                current_images_count=1,
            )

            with pytest.raises(Exception, match="503"):
                ai.edit_restyle_image_with_context(ctx, '16:9', '2K')

            # Legacy should NOT have been called
            mock_image.generate_image.assert_not_called()

    def test_no_conversation_support_uses_legacy_directly(self, app):
        """Provider without conversation support → use legacy directly."""
        with app.app_context():
            from services.ai_service import AIService
            from services.restyle_edit_context import RestyleEditContext

            mock_text = MagicMock()
            mock_image = MagicMock()
            mock_image.supports_conversation_contents = False
            result_img = Image.new('RGB', (1920, 1080), 'green')
            mock_image.generate_image.return_value = result_img

            ai = AIService(text_provider=mock_text, image_provider=mock_image)

            ctx = RestyleEditContext(
                conversation_contents=[
                    {'role': 'user', 'parts': [{'text': 'hello'}]},
                ],
                legacy_prompt='fallback prompt',
                legacy_ref_images=[],
                degraded_context=False,
                baseline_images_count=1,
                current_images_count=1,
            )

            result = ai.edit_restyle_image_with_context(ctx, '16:9', '2K')

            assert result == result_img
            mock_image.generate_image.assert_called_once()

    def test_resolve_conversation_images(self, app):
        """_resolve_conversation_images should convert image_path to PIL Images."""
        with app.app_context():
            from services.ai_service import AIService

            mock_text = MagicMock()
            mock_image = MagicMock()
            ai = AIService(text_provider=mock_text, image_provider=mock_image)

            img_path = _create_test_image('red')
            try:
                contents = [
                    {
                        'role': 'user',
                        'parts': [
                            {'text': 'hello'},
                            {'image_path': img_path},
                        ],
                    },
                    {
                        'role': 'model',
                        'parts': [
                            {'image_path': img_path},
                        ],
                    },
                ]

                resolved = ai._resolve_conversation_images(contents)

                # Text parts become strings
                assert resolved[0]['parts'][0] == 'hello'
                # Image parts become PIL Images
                assert isinstance(resolved[0]['parts'][1], Image.Image)
                assert isinstance(resolved[1]['parts'][0], Image.Image)
                # Roles preserved
                assert resolved[0]['role'] == 'user'
                assert resolved[1]['role'] == 'model'
            finally:
                os.unlink(img_path)

    def test_resolve_conversation_images_missing_file_skipped(self, app):
        """Missing image files should be skipped with warning."""
        with app.app_context():
            from services.ai_service import AIService

            mock_text = MagicMock()
            mock_image = MagicMock()
            ai = AIService(text_provider=mock_text, image_provider=mock_image)

            contents = [
                {
                    'role': 'user',
                    'parts': [
                        {'text': 'hello'},
                        {'image_path': '/nonexistent/image.png'},
                    ],
                },
            ]

            resolved = ai._resolve_conversation_images(contents)

            # Only text should remain, missing image skipped
            assert len(resolved[0]['parts']) == 1
            assert resolved[0]['parts'][0] == 'hello'
