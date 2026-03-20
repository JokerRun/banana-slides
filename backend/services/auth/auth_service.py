"""Authentication service for user/account upsert."""

import json

from models import User, UserOAuthAccount


class AuthService:
    """Auth domain operations."""

    def __init__(self, db_session):
        self.db_session = db_session

    def upsert_user_from_oauth(self, provider: str, user_info: dict) -> User:
        account = UserOAuthAccount.query.filter_by(
            provider=provider,
            provider_user_id=user_info['provider_user_id'],
        ).first()

        if account:
            user = User.query.get(account.user_id)
            if user:
                user.display_name = user_info.get('display_name')
                user.avatar_url = user_info.get('avatar_url')
            account.provider_username = user_info.get('username')
            account.email_at_provider = user_info.get('email')
            account.raw_profile = json.dumps(user_info.get('raw_profile') or {}, ensure_ascii=False)
            self.db_session.flush()
            return user

        user = User(
            display_name=user_info.get('display_name'),
            avatar_url=user_info.get('avatar_url'),
            is_active=True,
        )
        self.db_session.add(user)
        self.db_session.flush()

        account = UserOAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=user_info['provider_user_id'],
            provider_username=user_info.get('username'),
            email_at_provider=user_info.get('email'),
            raw_profile=json.dumps(user_info.get('raw_profile') or {}, ensure_ascii=False),
        )
        self.db_session.add(account)
        self.db_session.flush()

        return user
