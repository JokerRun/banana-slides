"""add restyle_prompt field to projects

Revision ID: 014_add_restyle_prompt
Revises: 013_add_restyle_fields
Create Date: 2026-03-04

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '014_add_restyle_prompt'
down_revision = '013_add_restyle_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('projects', sa.Column('restyle_prompt', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('projects', 'restyle_prompt')
