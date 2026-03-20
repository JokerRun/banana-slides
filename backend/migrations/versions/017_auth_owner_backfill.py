"""backfill owner_id with bootstrap user and keep legacy resources accessible

Revision ID: 017_auth_owner_backfill
Revises: 016_auth_foundation_additive
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
from sqlalchemy import inspect


revision = '017_auth_owner_backfill'
down_revision = '016_auth_foundation_additive'
branch_labels = None
depends_on = None

BOOTSTRAP_USER_ID = 'bootstrap-local-user'


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def ensure_bootstrap_user(conn):
    existing = conn.exec_driver_sql(
        "SELECT id FROM users WHERE id = ?",
        (BOOTSTRAP_USER_ID,),
    ).fetchone()
    if existing:
        conn.exec_driver_sql(
            "UPDATE users SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (BOOTSTRAP_USER_ID,),
        )
        return

    conn.exec_driver_sql(
        """
        INSERT INTO users (id, display_name, avatar_url, is_active, created_at, updated_at)
        VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (BOOTSTRAP_USER_ID, 'Bootstrap Legacy Owner', None),
    )


def run_owner_backfill(conn):
    ensure_bootstrap_user(conn)

    for table_name in ['projects', 'user_templates', 'materials', 'tasks']:
        conn.exec_driver_sql(
            f"UPDATE {table_name} SET owner_id = ? WHERE owner_id IS NULL",
            (BOOTSTRAP_USER_ID,),
        )

    conn.exec_driver_sql(
        """
        UPDATE reference_files
        SET owner_id = (
            SELECT p.owner_id
            FROM projects p
            WHERE p.id = reference_files.project_id
        )
        WHERE owner_id IS NULL
          AND project_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM projects p2 WHERE p2.id = reference_files.project_id)
        """
    )

    conn.exec_driver_sql(
        "UPDATE reference_files SET owner_id = ? WHERE owner_id IS NULL",
        (BOOTSTRAP_USER_ID,),
    )


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists('users'):
        return
    run_owner_backfill(conn)


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists('users'):
        return

    for table_name in ['projects', 'user_templates', 'materials', 'tasks', 'reference_files']:
        conn.exec_driver_sql(
            f"UPDATE {table_name} SET owner_id = NULL WHERE owner_id = ?",
            (BOOTSTRAP_USER_ID,),
        )

    conn.exec_driver_sql(
        "DELETE FROM users WHERE id = ?",
        (BOOTSTRAP_USER_ID,),
    )
