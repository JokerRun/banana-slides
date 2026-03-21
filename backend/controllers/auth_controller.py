"""Auth controller - OAuth login/callback and session profile APIs."""

from flask import Blueprint, current_app, redirect, request, session

from models import db
from services.auth import AuthService, GitHubOAuth, AzureChinaOAuth
from utils import error_response, success_response
from utils.auth import get_current_user, require_auth


auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _frontend_url(path: str = '/') -> str:
    """Build an absolute frontend URL for OAuth redirects."""
    base = current_app.config.get('FRONTEND_URL', 'http://localhost:3000').rstrip('/')
    return f'{base}{path}'


def get_oauth_provider(provider: str):
    if provider == 'github':
        return GitHubOAuth(
            client_id=current_app.config['GITHUB_CLIENT_ID'],
            client_secret=current_app.config['GITHUB_CLIENT_SECRET'],
            redirect_uri=current_app.config['GITHUB_REDIRECT_URI'],
        )
    if provider == 'azure':
        return AzureChinaOAuth(
            client_id=current_app.config['AZURE_CLIENT_ID'],
            client_secret=current_app.config['AZURE_CLIENT_SECRET'],
            auth_url=current_app.config['AZURE_AUTH_URL'],
            token_url=current_app.config['AZURE_TOKEN_URL'],
            user_info_url=current_app.config['AZURE_USER_INFO_URL'],
            redirect_uri=current_app.config['AZURE_REDIRECT_URI'],
        )
    return None


@auth_bp.route('/oauth/<provider>/login', methods=['GET'])
def oauth_login(provider: str):
    oauth_provider = get_oauth_provider(provider)
    if oauth_provider is None:
        return error_response('INVALID_PROVIDER', f'unsupported provider: {provider}', 400)

    state = oauth_provider.build_state()
    session['oauth_state'] = state
    session['oauth_provider'] = provider
    session.permanent = True
    return redirect(oauth_provider.get_authorization_url(state))


@auth_bp.route('/oauth/<provider>/callback', methods=['GET'])
def oauth_callback(provider: str):
    oauth_provider = get_oauth_provider(provider)
    if oauth_provider is None:
        return redirect(_frontend_url('/login?reason=oauth_callback_invalid'))

    state = request.args.get('state')
    expected_state = session.get('oauth_state')
    if not state or not expected_state or state != expected_state:
        return redirect(_frontend_url('/login?reason=oauth_state_invalid'))

    code = request.args.get('code')
    if not code:
        return redirect(_frontend_url('/login?reason=oauth_callback_invalid'))

    try:
        token = oauth_provider.exchange_code_for_token(code)
        info_payload = oauth_provider.fetch_user_info(token)
        if provider == 'github':
            normalized = oauth_provider.normalize_user_info(
                info_payload.get('profile') or {},
                info_payload.get('emails') or [],
            )
        else:
            normalized = oauth_provider.normalize_user_info(info_payload)

        auth_service = AuthService(db.session)
        user = auth_service.upsert_user_from_oauth(provider, normalized)
        db.session.commit()

        if not user.is_active:
            session.clear()
            return redirect(_frontend_url('/login?reason=user_disabled'))

        session.clear()
        session['user_id'] = user.id
        session['provider'] = provider
        session['provider_user_id'] = normalized.get('provider_user_id')
        session.permanent = True
        return redirect(_frontend_url('/'))
    except Exception:
        db.session.rollback()
        return redirect(_frontend_url('/login?reason=oauth_profile_failed'))


@auth_bp.route('/me', methods=['GET'])
@require_auth
def me():
    user = get_current_user()
    if not user:
        return error_response('AUTH_REQUIRED', 'Authentication required', 401)
    return success_response({'user': user.to_dict()})


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return success_response({'ok': True})
