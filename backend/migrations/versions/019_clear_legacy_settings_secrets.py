"""clear legacy settings secrets after env-only cutover

Revision ID: 019_clear_legacy_settings_secrets
Revises: 018_auth_owner_constraints
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '019_clear_legacy_settings_secrets'
down_revision = '018_auth_owner_constraints'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    assignments = []
    if _column_exists('settings', 'api_key'):
        assignments.append('api_key = NULL')
    if _column_exists('settings', 'mineru_token'):
        assignments.append('mineru_token = NULL')
    if _column_exists('settings', 'baidu_ocr_api_key'):
        assignments.append('baidu_ocr_api_key = NULL')

    if assignments:
        op.execute(sa.text(f"UPDATE settings SET {', '.join(assignments)}"))


def downgrade() -> None:
    # Irreversible: cleared secrets cannot be recovered from migration state.
    pass
