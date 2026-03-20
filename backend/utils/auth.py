"""Session-based auth helpers."""

from functools import wraps

from flask import session

from models import User
from utils.response import error_response


def get_current_user_id() -> str | None:
    return session.get('user_id')


def get_current_user() -> User | None:
    user_id = get_current_user_id()
    if not user_id:
        return None
    return User.query.get(user_id)


def require_auth_response():
    """Return auth error response for current request, or None when authenticated."""
    user_id = get_current_user_id()
    if not user_id:
        return error_response('AUTH_REQUIRED', 'Authentication required', 401)

    user = User.query.get(user_id)
    if not user:
        session.clear()
        return error_response('AUTH_REQUIRED', 'Authentication required', 401)
    if not user.is_active:
        session.clear()
        return error_response('AUTH_REQUIRED', 'User is inactive', 401)
    return None


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_error = require_auth_response()
        if auth_error is not None:
            return auth_error
        return fn(*args, **kwargs)

    return wrapper
