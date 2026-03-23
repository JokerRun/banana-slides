"""tighten owner_id columns to NOT NULL after auth rollout

Revision ID: 018_auth_owner_constraints
Revises: 017_auth_owner_backfill
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = '018_auth_owner_constraints'
down_revision = '017_auth_owner_backfill'
branch_labels = None
depends_on = None


# Tables that receive the NOT NULL constraint on owner_id.
_TABLES = ['projects', 'user_templates', 'materials', 'tasks', 'reference_files']


def upgrade():
    # SQLite does not support ALTER COLUMN ... SET NOT NULL directly.
    # Use batch mode which recreates the table behind the scenes.
    for table_name in _TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                'owner_id',
                existing_type=sa.String(36),
                nullable=False,
            )


def downgrade():
    for table_name in _TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                'owner_id',
                existing_type=sa.String(36),
                nullable=True,
            )
