"""replace image_thinking_budget with image_thinking_level

Revision ID: 015_image_thinking_level
Revises: 014_add_restyle_prompt
Create Date: 2026-03-14 00:00:00.000000

Replace enable_image_reasoning (bool) + image_thinking_budget (int)
with image_thinking_level (str: none/minimal/high) for Gemini 3 models.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '015_image_thinking_level'
down_revision = '014_add_restyle_prompt'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    if not _column_exists('settings', 'image_thinking_level'):
        op.add_column('settings', sa.Column('image_thinking_level', sa.String(10), nullable=False, server_default='none'))

    # Migrate: if image_reasoning was enabled, default to 'minimal'
    if _column_exists('settings', 'enable_image_reasoning'):
        op.execute("""
            UPDATE settings
            SET image_thinking_level = CASE
                WHEN enable_image_reasoning = 1 THEN 'minimal'
                ELSE 'none'
            END
        """)
        op.drop_column('settings', 'enable_image_reasoning')

    if _column_exists('settings', 'image_thinking_budget'):
        op.drop_column('settings', 'image_thinking_budget')


def downgrade() -> None:
    if not _column_exists('settings', 'enable_image_reasoning'):
        op.add_column('settings', sa.Column('enable_image_reasoning', sa.Boolean(), nullable=False, server_default='0'))
    if not _column_exists('settings', 'image_thinking_budget'):
        op.add_column('settings', sa.Column('image_thinking_budget', sa.Integer(), nullable=False, server_default='1024'))

    if _column_exists('settings', 'image_thinking_level'):
        op.execute("""
            UPDATE settings
            SET enable_image_reasoning = CASE
                WHEN image_thinking_level != 'none' THEN 1
                ELSE 0
            END
        """)
        op.drop_column('settings', 'image_thinking_level')
