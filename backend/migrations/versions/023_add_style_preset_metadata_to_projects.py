"""add style preset metadata to projects

Revision ID: 023_add_style_preset_metadata
Revises: 022_add_project_name
Create Date: 2026-07-01

"""

from alembic import op
import sqlalchemy as sa


revision = "023_add_style_preset_metadata"
down_revision = "022_add_project_name"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("style_preset_id", sa.String(100), nullable=True))
    op.add_column("projects", sa.Column("style_preset_version", sa.String(50), nullable=True))
    op.add_column("projects", sa.Column("style_preset_sha256", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("projects", "style_preset_sha256")
    op.drop_column("projects", "style_preset_version")
    op.drop_column("projects", "style_preset_id")
