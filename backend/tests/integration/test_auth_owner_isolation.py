"""Integration tests for auth ownership migration and owner isolation."""

from pathlib import Path

import pytest

from models import db, Project, ReferenceFile, Task, User
from models import Material, UserTemplate


def _login(client, user_id: str) -> None:
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def test_extract_id_persistence(app, monkeypatch):
    """Parser extract_id persistence regression test.

    The NULL->backfill portion is skipped post-M3 because the ORM schema now
    enforces NOT NULL on owner_id.  The extract_id persistence part remains
    as a live regression test.
    """
    with app.app_context():
        # --- extract_id persistence part (still valid post-M3) ---
        test_user = User(display_name='Parse Test User', is_active=True)
        db.session.add(test_user)
        db.session.flush()

        project = Project(
            id='project-parse',
            owner_id=test_user.id,
            status='DRAFT',
            creation_type='idea',
        )
        db.session.add(project)
        db.session.flush()

        upload_root = Path(app.config['UPLOAD_FOLDER'])
        ref_dir = upload_root / 'reference_files'
        ref_dir.mkdir(parents=True, exist_ok=True)
        target_file = ref_dir / 'parse.pdf'
        target_file.write_bytes(b'fake')

        rf = ReferenceFile(
            project_id=project.id,
            owner_id=test_user.id,
            filename='parse.pdf',
            file_path='reference_files/parse.pdf',
            file_size=4,
            file_type='pdf',
            parse_status='pending',
        )
        db.session.add(rf)
        db.session.commit()

        import controllers.reference_file_controller as controller

        class _DummyParser:
            def parse_file(self, file_path, filename):
                return 'batch-1', '# parsed', 'extract-1', None, 0

        monkeypatch.setattr(controller, 'FileParserService', lambda **kwargs: _DummyParser())

        controller._parse_file_async(rf.id, str(target_file), rf.filename, app)

        db.session.expire_all()
        refreshed = ReferenceFile.query.get(rf.id)
        assert refreshed is not None
        assert refreshed.parse_status == 'completed'
        assert refreshed.mineru_batch_id == 'batch-1'
        assert refreshed.mineru_extract_id == 'extract-1'


def test_global_task_status_owner_only(app):
    """Global task status endpoint should be owner-scoped."""
    with app.app_context():
        user_a = User(display_name='User A', is_active=True)
        user_b = User(display_name='User B', is_active=True)
        db.session.add_all([user_a, user_b])
        db.session.flush()

        task = Task(
            project_id='global',
            owner_id=user_a.id,
            task_type='GENERATE_MATERIAL',
            status='PENDING',
        )
        task.set_progress({'total': 1, 'completed': 0, 'failed': 0})
        db.session.add(task)
        db.session.commit()

        with app.test_client() as client_anon:
            res = client_anon.get(f'/api/tasks/{task.id}')
            assert res.status_code == 401

        with app.test_client() as client_a:
            with client_a.session_transaction() as sess:
                sess['user_id'] = user_a.id
            res = client_a.get(f'/api/tasks/{task.id}')
            assert res.status_code == 200

        with app.test_client() as client_b:
            with client_b.session_transaction() as sess:
                sess['user_id'] = user_b.id
            res = client_b.get(f'/api/tasks/{task.id}')
            assert res.status_code == 404


def test_settings_task_status_locked_for_authenticated_users(app):
    """Settings test status endpoint is locked in env-only mode."""
    with app.app_context():
        user_a = User(display_name='User A', is_active=True)
        user_b = User(display_name='User B', is_active=True)
        db.session.add_all([user_a, user_b])
        db.session.flush()

        task = Task(
            project_id='settings-test',
            owner_id=user_a.id,
            task_type='TEST_TEXT_MODEL',
            status='PENDING',
        )
        db.session.add(task)
        db.session.commit()

        with app.test_client() as client_anon:
            res = client_anon.get(f'/api/settings/tests/{task.id}/status')
            assert res.status_code == 401

        with app.test_client() as client_a:
            with client_a.session_transaction() as sess:
                sess['user_id'] = user_a.id
            res = client_a.get(f'/api/settings/tests/{task.id}/status')
            assert res.status_code == 403
            payload = res.get_json()
            assert payload['error']['code'] == 'SETTINGS_LOCKED'

        with app.test_client() as client_b:
            with client_b.session_transaction() as sess:
                sess['user_id'] = user_b.id
            res = client_b.get(f'/api/settings/tests/{task.id}/status')
            assert res.status_code == 403
            payload = res.get_json()
            assert payload['error']['code'] == 'SETTINGS_LOCKED'


def test_auth_required_and_project_isolation(app):
    """Business endpoints should enforce unauthenticated=401 and non-owner=404."""
    with app.app_context():
        user_a = User(display_name='Owner', is_active=True)
        user_b = User(display_name='Other', is_active=True)
        db.session.add_all([user_a, user_b])
        db.session.flush()

        project = Project(owner_id=user_a.id, status='DRAFT', creation_type='idea')
        db.session.add(project)
        db.session.commit()

        project_id = project.id
        user_a_id = user_a.id
        user_b_id = user_b.id

    with app.test_client() as anon:
        res = anon.get('/api/projects')
        assert res.status_code == 401

    with app.test_client() as owner_client:
        _login(owner_client, user_a_id)
        res = owner_client.get(f'/api/projects/{project_id}')
        assert res.status_code == 200

    with app.test_client() as other_client:
        _login(other_client, user_b_id)
        res = other_client.get(f'/api/projects/{project_id}')
        assert res.status_code == 404


def test_files_project_route_owner_guard(app):
    """/files/<project_id>/* should be owner-scoped with 401/404 semantics."""
    with app.app_context():
        user_a = User(display_name='Owner', is_active=True)
        user_b = User(display_name='Other', is_active=True)
        db.session.add_all([user_a, user_b])
        db.session.flush()

        project = Project(owner_id=user_a.id, status='DRAFT', creation_type='idea')
        db.session.add(project)
        db.session.commit()

        target = Path(app.config['UPLOAD_FOLDER']) / project.id / 'template' / 'preview.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'project-file')

        project_id = project.id
        user_a_id = user_a.id
        user_b_id = user_b.id

    with app.test_client() as anon:
        res = anon.get(f'/files/{project_id}/template/preview.png')
        assert res.status_code == 401

    with app.test_client() as owner_client:
        _login(owner_client, user_a_id)
        res = owner_client.get(f'/files/{project_id}/template/preview.png')
        assert res.status_code == 200

    with app.test_client() as other_client:
        _login(other_client, user_b_id)
        res = other_client.get(f'/files/{project_id}/template/preview.png')
        assert res.status_code == 404


def test_files_user_template_owner_guard(app):
    """/files/user-templates/* should be owner-scoped with 401/404 semantics."""
    with app.app_context():
        user_a = User(display_name='Owner', is_active=True)
        user_b = User(display_name='Other', is_active=True)
        db.session.add_all([user_a, user_b])
        db.session.flush()

        template = UserTemplate(
            owner_id=user_a.id,
            file_path='user-templates/tpl-1/template.png',
        )
        db.session.add(template)
        db.session.commit()

        target = Path(app.config['UPLOAD_FOLDER']) / 'user-templates' / template.id / 'template.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'user-template')

        template_id = template.id
        user_a_id = user_a.id
        user_b_id = user_b.id

    with app.test_client() as anon:
        res = anon.get(f'/files/user-templates/{template_id}/template.png')
        assert res.status_code == 401

    with app.test_client() as owner_client:
        _login(owner_client, user_a_id)
        res = owner_client.get(f'/files/user-templates/{template_id}/template.png')
        assert res.status_code == 200

    with app.test_client() as other_client:
        _login(other_client, user_b_id)
        res = other_client.get(f'/files/user-templates/{template_id}/template.png')
        assert res.status_code == 404


def test_files_material_owner_guard(app):
    """/files/materials/* should be owner-scoped with 401/404 semantics."""
    with app.app_context():
        user_a = User(display_name='Owner', is_active=True)
        user_b = User(display_name='Other', is_active=True)
        db.session.add_all([user_a, user_b])
        db.session.flush()

        material = Material(
            owner_id=user_a.id,
            project_id=None,
            filename='shared.png',
            relative_path='materials/shared.png',
            url='/files/materials/shared.png',
        )
        db.session.add(material)
        db.session.commit()

        target = Path(app.config['UPLOAD_FOLDER']) / 'materials' / 'shared.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'material')

        user_a_id = user_a.id
        user_b_id = user_b.id

    with app.test_client() as anon:
        res = anon.get('/files/materials/shared.png')
        assert res.status_code == 401

    with app.test_client() as owner_client:
        _login(owner_client, user_a_id)
        res = owner_client.get('/files/materials/shared.png')
        assert res.status_code == 200

    with app.test_client() as other_client:
        _login(other_client, user_b_id)
        res = other_client.get('/files/materials/shared.png')
        assert res.status_code == 404


def test_files_mineru_owner_guard(app):
    """/files/mineru/<extract_id>/* should be owner-scoped with 401/404 semantics."""
    with app.app_context():
        user_a = User(display_name='Owner', is_active=True)
        user_b = User(display_name='Other', is_active=True)
        db.session.add_all([user_a, user_b])
        db.session.flush()

        ref = ReferenceFile(
            owner_id=user_a.id,
            project_id=None,
            filename='doc.pdf',
            file_path='reference_files/doc.pdf',
            file_size=1,
            file_type='pdf',
            parse_status='completed',
            mineru_extract_id='extract-owned',
        )
        db.session.add(ref)
        db.session.commit()

        target = Path(app.config['UPLOAD_FOLDER']) / 'mineru_files' / 'extract-owned' / 'chunk_001.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('mineru output')

        user_a_id = user_a.id
        user_b_id = user_b.id

    with app.test_client() as anon:
        res = anon.get('/files/mineru/extract-owned/chunk_001.md')
        assert res.status_code == 401

    with app.test_client() as owner_client:
        _login(owner_client, user_a_id)
        res = owner_client.get('/files/mineru/extract-owned/chunk_001.md')
        assert res.status_code == 200

    with app.test_client() as other_client:
        _login(other_client, user_b_id)
        res = other_client.get('/files/mineru/extract-owned/chunk_001.md')
        assert res.status_code == 404


def test_owner_columns_non_null_after_m3(app):
    """After M3 migration, inserting rows with NULL owner_id should raise IntegrityError."""
    import sqlalchemy
    with app.app_context():
        # Project with NULL owner_id should fail
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            p = Project(status='DRAFT', creation_type='idea', owner_id=None)
            db.session.add(p)
            db.session.flush()
        db.session.rollback()

        # UserTemplate with NULL owner_id should fail
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            t = UserTemplate(file_path='x/y.png', owner_id=None)
            db.session.add(t)
            db.session.flush()
        db.session.rollback()

        # Material with NULL owner_id should fail
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            m = Material(filename='x.png', relative_path='m/x.png', url='/files/m/x.png', owner_id=None)
            db.session.add(m)
            db.session.flush()
        db.session.rollback()

        # Task with NULL owner_id should fail
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            tk = Task(project_id='global', task_type='GENERATE_MATERIAL', status='PENDING', owner_id=None)
            db.session.add(tk)
            db.session.flush()
        db.session.rollback()

        # ReferenceFile with NULL owner_id should fail
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            rf = ReferenceFile(
                project_id=None, filename='z.pdf', file_path='rf/z.pdf',
                file_size=1, file_type='pdf', parse_status='pending', owner_id=None,
            )
            db.session.add(rf)
            db.session.flush()
        db.session.rollback()
