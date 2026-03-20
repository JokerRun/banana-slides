"""OAuth provider normalization unit tests."""

from services.auth.oauth_providers import GitHubOAuth, AzureChinaOAuth


def test_github_email_from_verified_primary():
    provider = GitHubOAuth(
        client_id='x',
        client_secret='y',
        redirect_uri='http://localhost/callback',
    )
    profile = {
        'id': 123,
        'login': 'octo-user',
        'name': 'Octo User',
        'avatar_url': 'https://example.com/avatar.png',
    }
    emails = [
        {'email': 'alt@example.com', 'verified': True, 'primary': False},
        {'email': 'primary@example.com', 'verified': True, 'primary': True},
        {'email': 'not-verified@example.com', 'verified': False, 'primary': True},
    ]

    normalized = provider.normalize_user_info(profile, emails)

    assert normalized['provider_user_id'] == '123'
    assert normalized['username'] == 'octo-user'
    assert normalized['display_name'] == 'Octo User'
    assert normalized['email'] == 'primary@example.com'
    assert normalized['avatar_url'] == 'https://example.com/avatar.png'


def test_azure_email_fallback_to_upn():
    provider = AzureChinaOAuth(
        client_id='x',
        client_secret='y',
        auth_url='https://login.partner.microsoftonline.cn/tenant/oauth2/v2.0/authorize',
        token_url='https://login.partner.microsoftonline.cn/tenant/oauth2/v2.0/token',
        user_info_url='https://microsoftgraph.chinacloudapi.cn/v1.0/me',
        redirect_uri='http://localhost/callback',
    )
    profile = {
        'id': 'azure-uid',
        'displayName': 'Azure User',
        'mail': None,
        'userPrincipalName': 'azure.user@tenant.partner.onmschina.cn',
    }

    normalized = provider.normalize_user_info(profile)

    assert normalized['provider_user_id'] == 'azure-uid'
    assert normalized['username'] == 'azure.user@tenant.partner.onmschina.cn'
    assert normalized['display_name'] == 'Azure User'
    assert normalized['email'] == 'azure.user@tenant.partner.onmschina.cn'
    assert normalized['avatar_url'] is None
