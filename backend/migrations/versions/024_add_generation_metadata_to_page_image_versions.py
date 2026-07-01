"""add generation metadata to page image versions

Revision ID: 024_add_generation_metadata
Revises: 023_add_style_preset_metadata
Create Date: 2026-07-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "024_add_generation_metadata"
down_revision = "023_add_style_preset_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "page_image_versions",
        sa.Column("prompt_snapshot", sa.Text(), nullable=True),
    )
    op.add_column(
        "page_image_versions",
        sa.Column("ref_manifest", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("page_image_versions", "ref_manifest")
    op.drop_column("page_image_versions", "prompt_snapshot")
