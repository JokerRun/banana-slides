"""add users/oauth tables and additive owner columns

Revision ID: 016_auth_foundation_additive
Revises: 015_image_thinking_level
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '016_auth_foundation_additive'
down_revision = '015_image_thinking_level'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = inspector.get_table_names()

    if 'users' not in table_names:
        op.create_table(
            'users',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('display_name', sa.Text(), nullable=True),
            sa.Column('avatar_url', sa.String(length=500), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'user_oauth_accounts' not in table_names:
        op.create_table(
            'user_oauth_accounts',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.String(length=36), nullable=False),
            sa.Column('provider', sa.String(length=50), nullable=False),
            sa.Column('provider_user_id', sa.String(length=255), nullable=False),
            sa.Column('provider_username', sa.String(length=255), nullable=True),
            sa.Column('email_at_provider', sa.String(length=255), nullable=True),
            sa.Column('raw_profile', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('provider', 'provider_user_id', name='uq_oauth_provider_user_id'),
        )
        op.create_index('ix_user_oauth_accounts_user_id', 'user_oauth_accounts', ['user_id'])
        op.create_index('ix_user_oauth_accounts_provider', 'user_oauth_accounts', ['provider'])
        op.create_index('ix_user_oauth_accounts_provider_user_id', 'user_oauth_accounts', ['provider_user_id'])

    owner_targets = [
        ('projects', 'ix_projects_owner_id'),
        ('user_templates', 'ix_user_templates_owner_id'),
        ('materials', 'ix_materials_owner_id'),
        ('tasks', 'ix_tasks_owner_id'),
        ('reference_files', 'ix_reference_files_owner_id'),
    ]
    for table_name, index_name in owner_targets:
        if not _column_exists(table_name, 'owner_id'):
            op.add_column(table_name, sa.Column('owner_id', sa.String(length=36), nullable=True))
        if not _index_exists(table_name, index_name):
            op.create_index(index_name, table_name, ['owner_id'])

    if not _column_exists('reference_files', 'mineru_extract_id'):
        op.add_column('reference_files', sa.Column('mineru_extract_id', sa.String(length=100), nullable=True))
    if not _index_exists('reference_files', 'ix_reference_files_mineru_extract_id'):
        op.create_index('ix_reference_files_mineru_extract_id', 'reference_files', ['mineru_extract_id'])


def downgrade() -> None:
    if _index_exists('reference_files', 'ix_reference_files_mineru_extract_id'):
        op.drop_index('ix_reference_files_mineru_extract_id', table_name='reference_files')
    if _column_exists('reference_files', 'mineru_extract_id'):
        op.drop_column('reference_files', 'mineru_extract_id')

    owner_targets = [
        ('reference_files', 'ix_reference_files_owner_id'),
        ('tasks', 'ix_tasks_owner_id'),
        ('materials', 'ix_materials_owner_id'),
        ('user_templates', 'ix_user_templates_owner_id'),
        ('projects', 'ix_projects_owner_id'),
    ]
    for table_name, index_name in owner_targets:
        if _index_exists(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
        if _column_exists(table_name, 'owner_id'):
            op.drop_column(table_name, 'owner_id')

    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = inspector.get_table_names()
    if 'user_oauth_accounts' in table_names:
        if _index_exists('user_oauth_accounts', 'ix_user_oauth_accounts_provider_user_id'):
            op.drop_index('ix_user_oauth_accounts_provider_user_id', table_name='user_oauth_accounts')
        if _index_exists('user_oauth_accounts', 'ix_user_oauth_accounts_provider'):
            op.drop_index('ix_user_oauth_accounts_provider', table_name='user_oauth_accounts')
        if _index_exists('user_oauth_accounts', 'ix_user_oauth_accounts_user_id'):
            op.drop_index('ix_user_oauth_accounts_user_id', table_name='user_oauth_accounts')
        op.drop_table('user_oauth_accounts')
    if 'users' in table_names:
        op.drop_table('users')
