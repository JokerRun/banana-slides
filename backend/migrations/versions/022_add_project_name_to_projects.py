"""add project_name to projects

Revision ID: 022_add_project_name
Revises: 021_add_translate_fields
Create Date: 2026-07-01

"""

from alembic import op
import sqlalchemy as sa


revision = "022_add_project_name"
down_revision = "021_add_translate_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("project_name", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("projects", "project_name")
