"""add restyle_base_prompt_snapshot to pages

Revision ID: 020_add_restyle_base_prompt_snapshot
Revises: 019_clear_legacy_settings_secrets
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '020_add_restyle_base_prompt_snapshot'
down_revision = '019_clear_legacy_settings_secrets'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('pages', sa.Column('restyle_base_prompt_snapshot', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('pages', 'restyle_base_prompt_snapshot')
