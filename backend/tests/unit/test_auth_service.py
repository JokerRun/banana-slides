"""Auth schema and OAuth account uniqueness tests (M1)."""

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from models import User, UserOAuthAccount
from services.auth.auth_service import AuthService


def test_auth_schema_columns_exist(db_session):
    """Auth tables and owner columns exist; owner_id is NOT NULL after M3."""
    inspector = inspect(db_session.get_bind())

    table_names = inspector.get_table_names()
    assert 'users' in table_names
    assert 'user_oauth_accounts' in table_names

    for table in ['projects', 'user_templates', 'materials', 'tasks', 'reference_files']:
        columns = {col['name']: col for col in inspector.get_columns(table)}
        assert 'owner_id' in columns
        assert columns['owner_id']['nullable'] is False

    reference_file_columns = {
        col['name']: col for col in inspector.get_columns('reference_files')
    }
    assert 'mineru_extract_id' in reference_file_columns
    assert reference_file_columns['mineru_extract_id']['nullable'] is True

    reference_file_indexes = inspector.get_indexes('reference_files')
    assert any('mineru_extract_id' in index['name'] for index in reference_file_indexes)


def test_oauth_identity_unique_key(db_session):
    """Duplicate (provider, provider_user_id) must fail with IntegrityError."""
    user_a = User(display_name='User A')
    user_b = User(display_name='User B')
    db_session.add_all([user_a, user_b])
    db_session.flush()

    account_a = UserOAuthAccount(
        user_id=user_a.id,
        provider='github',
        provider_user_id='provider-user-1',
        provider_username='user-a',
    )
    account_b = UserOAuthAccount(
        user_id=user_b.id,
        provider='github',
        provider_user_id='provider-user-1',
        provider_username='user-b',
    )
    db_session.add(account_a)
    db_session.flush()
    db_session.add(account_b)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_auth_service_upsert_user_from_oauth(db_session):
    """AuthService should upsert user by (provider, provider_user_id)."""
    auth_service = AuthService(db_session)

    payload = {
        'provider_user_id': 'oauth-001',
        'display_name': 'Rico',
        'email': 'rico@example.com',
        'avatar_url': 'https://example.com/rico.png',
        'username': 'rico-u',
        'raw_profile': {'id': 'oauth-001'},
    }

    user_1 = auth_service.upsert_user_from_oauth('github', payload)
    db_session.flush()

    payload_updated = {
        **payload,
        'display_name': 'Rico Updated',
        'email': 'rico.new@example.com',
    }
    user_2 = auth_service.upsert_user_from_oauth('github', payload_updated)
    db_session.flush()

    assert user_1.id == user_2.id
    accounts = UserOAuthAccount.query.filter_by(provider='github', provider_user_id='oauth-001').all()
    assert len(accounts) == 1
    assert accounts[0].email_at_provider == 'rico.new@example.com'
