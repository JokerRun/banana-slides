"""add provider input snapshot to page image versions

Revision ID: 025_add_provider_input_snapshot
Revises: 024_add_generation_metadata
Create Date: 2026-07-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "025_add_provider_input_snapshot"
down_revision = "024_add_generation_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "page_image_versions",
        sa.Column("provider_input_snapshot", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("page_image_versions", "provider_input_snapshot")
