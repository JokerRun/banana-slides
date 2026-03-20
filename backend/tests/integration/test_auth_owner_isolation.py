"""Integration tests for auth ownership migration and mineru mapping persistence."""

import importlib.util
from pathlib import Path

from models import db, Project, ReferenceFile, Task, User


def _load_m017_module():
    backend_dir = Path(__file__).resolve().parents[2]
    migration_path = backend_dir / 'migrations' / 'versions' / '017_auth_owner_backfill.py'
    spec = importlib.util.spec_from_file_location('m017_auth_owner_backfill', migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_owner_and_persist_extract_id(app, monkeypatch):
    """M2 should backfill legacy owner_id and persist parser extract_id."""
    m017 = _load_m017_module()

    with app.app_context():
        conn = db.engine.connect()
        tx = conn.begin()
        try:
            conn.exec_driver_sql(
                """
                INSERT INTO projects (id, owner_id, status, creation_type, created_at, updated_at)
                VALUES ('project-a', NULL, 'DRAFT', 'idea', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO user_templates (id, owner_id, file_path, created_at, updated_at)
                VALUES ('tpl-a', NULL, 'user-templates/tpl-a/a.png', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO materials (id, owner_id, project_id, filename, relative_path, url, created_at, updated_at)
                VALUES ('mat-a', NULL, NULL, 'mat.png', 'materials/mat.png', '/files/materials/mat.png', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO tasks (id, owner_id, project_id, task_type, status, created_at)
                VALUES ('task-a', NULL, 'global', 'GENERATE_MATERIAL', 'PENDING', CURRENT_TIMESTAMP)
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO reference_files (id, owner_id, project_id, filename, file_path, file_size, file_type, parse_status, created_at, updated_at)
                VALUES
                    ('ref-project', NULL, 'project-a', 'a.pdf', 'reference_files/a.pdf', 1, 'pdf', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('ref-orphan', NULL, 'missing-project', 'b.pdf', 'reference_files/b.pdf', 1, 'pdf', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )

            m017.run_owner_backfill(conn)

            bootstrap_id = m017.BOOTSTRAP_USER_ID
            user_row = conn.exec_driver_sql(
                "SELECT id, is_active FROM users WHERE id = ?",
                (bootstrap_id,),
            ).fetchone()
            assert user_row is not None
            assert user_row[1] == 0

            for table, row_id in [
                ('projects', 'project-a'),
                ('user_templates', 'tpl-a'),
                ('materials', 'mat-a'),
                ('tasks', 'task-a'),
                ('reference_files', 'ref-project'),
                ('reference_files', 'ref-orphan'),
            ]:
                owner_row = conn.exec_driver_sql(
                    f"SELECT owner_id FROM {table} WHERE id = ?",
                    (row_id,),
                ).fetchone()
                assert owner_row is not None
                assert owner_row[0] == bootstrap_id
        finally:
            tx.rollback()
            conn.close()

        project = Project(
            id='project-parse',
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


def test_settings_task_status_owner_scope(app):
    """Settings task status should be owner-scoped as well."""
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
            assert res.status_code == 200

        with app.test_client() as client_b:
            with client_b.session_transaction() as sess:
                sess['user_id'] = user_b.id
            res = client_b.get(f'/api/settings/tests/{task.id}/status')
            assert res.status_code == 404
