"""add restyle fields to project and page

Revision ID: 013_add_restyle_fields
Revises: 012
Create Date: 2026-02-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '013_add_restyle_fields'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    # Project: restyle 模式新增字段
    op.add_column('projects', sa.Column('source_file_path', sa.String(500), nullable=True))
    op.add_column('projects', sa.Column('style_ref_image_paths', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('brand_guidelines', sa.Text(), nullable=True))

    # Page: 原始slide图片路径（restyle模式专用）
    op.add_column('pages', sa.Column('original_slide_image_path', sa.String(500), nullable=True))


def downgrade():
    op.drop_column('pages', 'original_slide_image_path')
    op.drop_column('projects', 'brand_guidelines')
    op.drop_column('projects', 'style_ref_image_paths')
    op.drop_column('projects', 'source_file_path')
