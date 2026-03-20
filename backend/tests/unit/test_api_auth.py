"""Auth API tests."""

from models import db, User


def test_auth_me_unauthenticated_returns_401(client):
    response = client.get('/api/auth/me')
    assert response.status_code == 401
    payload = response.get_json()
    assert payload['error']['code'] == 'AUTH_REQUIRED'


def test_callback_invalid_state_redirects_login_reason(client):
    response = client.get('/api/auth/oauth/github/callback?code=abc&state=wrong')
    assert response.status_code == 302
    assert '/login?reason=oauth_state_invalid' in response.headers['Location']


def test_callback_inactive_user_redirects_user_disabled(client, monkeypatch):
    user = User(display_name='Disabled User', is_active=False)
    db.session.add(user)
    db.session.commit()

    class DummyProvider:
        def exchange_code_for_token(self, code):
            return 'token'

        def fetch_user_info(self, access_token):
            return {'profile': {'id': 'oauth-uid', 'login': 'u1'}, 'emails': []}

        def normalize_user_info(self, profile, emails=None):
            return {
                'provider_user_id': 'oauth-uid',
                'display_name': 'Disabled User',
                'email': 'disabled@example.com',
                'avatar_url': None,
                'username': 'u1',
                'raw_profile': profile,
            }

    from models import UserOAuthAccount
    account = UserOAuthAccount(
        user_id=user.id,
        provider='github',
        provider_user_id='oauth-uid',
        provider_username='u1',
        email_at_provider='disabled@example.com',
    )
    db.session.add(account)
    db.session.commit()

    import controllers.auth_controller as auth_controller
    monkeypatch.setattr(auth_controller, 'get_oauth_provider', lambda provider: DummyProvider())

    with client.session_transaction() as session:
        session['oauth_state'] = 'expected-state'
        session['oauth_provider'] = 'github'

    response = client.get('/api/auth/oauth/github/callback?code=abc&state=expected-state')
    assert response.status_code == 302
    assert '/login?reason=user_disabled' in response.headers['Location']
