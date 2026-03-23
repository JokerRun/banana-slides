"""OAuth provider adapters for GitHub and Azure China."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode
import secrets

import requests


@dataclass
class OAuthUserInfo:
    provider_user_id: str
    display_name: str | None
    email: str | None
    avatar_url: str | None
    username: str | None
    raw_profile: dict


class OAuthProvider:
    provider: str

    def build_state(self) -> str:
        return secrets.token_urlsafe(24)


class GitHubOAuth(OAuthProvider):
    provider = 'github'
    AUTHORIZE_URL = 'https://github.com/login/oauth/authorize'
    TOKEN_URL = 'https://github.com/login/oauth/access_token'
    USER_URL = 'https://api.github.com/user'
    EMAILS_URL = 'https://api.github.com/user/emails'

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str, nonce: str | None = None) -> str:
        query = urlencode(
            {
                'client_id': self.client_id,
                'redirect_uri': self.redirect_uri,
                'scope': 'user:email',
                'state': state,
            }
        )
        return f'{self.AUTHORIZE_URL}?{query}'

    def exchange_code_for_token(self, code: str) -> str:
        response = requests.post(
            self.TOKEN_URL,
            headers={'Accept': 'application/json'},
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': code,
                'redirect_uri': self.redirect_uri,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get('access_token')
        if not token:
            raise ValueError('missing access_token from github')
        return token

    def fetch_user_info(self, access_token: str) -> dict:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/vnd.github+json',
        }
        user_resp = requests.get(self.USER_URL, headers=headers, timeout=15)
        user_resp.raise_for_status()
        emails_resp = requests.get(self.EMAILS_URL, headers=headers, timeout=15)
        emails_resp.raise_for_status()
        return {
            'profile': user_resp.json(),
            'emails': emails_resp.json(),
        }

    def normalize_user_info(self, profile: dict, emails: list[dict] | None = None) -> dict:
        email = None
        emails = emails or []
        for item in emails:
            if item.get('verified') and item.get('primary'):
                email = item.get('email')
                break
        if not email:
            for item in emails:
                if item.get('verified'):
                    email = item.get('email')
                    break

        username = profile.get('login')
        display_name = profile.get('name') or username
        return {
            'provider_user_id': str(profile.get('id')),
            'display_name': display_name,
            'email': email,
            'avatar_url': profile.get('avatar_url'),
            'username': username,
            'raw_profile': profile,
        }


class AzureChinaOAuth(OAuthProvider):
    provider = 'azure'

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        auth_url: str,
        token_url: str,
        user_info_url: str,
        redirect_uri: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url
        self.token_url = token_url
        self.user_info_url = user_info_url
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str, nonce: str | None = None) -> str:
        query = urlencode(
            {
                'client_id': self.client_id,
                'response_type': 'code',
                'redirect_uri': self.redirect_uri,
                'response_mode': 'query',
                'scope': 'openid profile email offline_access https://microsoftgraph.chinacloudapi.cn/User.Read',
                'state': state,
            }
        )
        return f'{self.auth_url}?{query}'

    def exchange_code_for_token(self, code: str) -> str:
        response = requests.post(
            self.token_url,
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': self.redirect_uri,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get('access_token')
        if not token:
            raise ValueError('missing access_token from azure')
        return token

    def fetch_user_info(self, access_token: str) -> dict:
        response = requests.get(
            self.user_info_url,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def normalize_user_info(self, profile: dict) -> dict:
        upn = profile.get('userPrincipalName')
        email = profile.get('mail') or upn
        return {
            'provider_user_id': str(profile.get('id')),
            'display_name': profile.get('displayName'),
            'email': email,
            'avatar_url': None,
            'username': upn,
            'raw_profile': profile,
        }
