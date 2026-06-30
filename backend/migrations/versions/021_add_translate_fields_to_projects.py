"""add translate fields to projects

Revision ID: 021_add_translate_fields
Revises: 020_add_restyle_base_prompt_snapshot
Create Date: 2026-06-30

"""
from alembic import op
import sqlalchemy as sa


revision = '021_add_translate_fields'
down_revision = '020_add_restyle_base_prompt_snapshot'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('projects', sa.Column('translate_mode', sa.String(20), nullable=True))
    op.add_column('projects', sa.Column('target_language', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('projects', 'target_language')
    op.drop_column('projects', 'translate_mode')
