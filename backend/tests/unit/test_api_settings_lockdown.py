"""Settings API lockdown tests for env-only mode."""

import importlib


def test_settings_endpoints_require_auth(app):
    """Unauthenticated requests should still return 401 via auth guard."""
    with app.test_client() as anon_client:
        assert anon_client.get('/api/settings/').status_code == 401
        assert anon_client.put('/api/settings/', json={}).status_code == 401
        assert anon_client.post('/api/settings/reset').status_code == 401
        assert anon_client.post('/api/settings/verify').status_code == 401
        assert anon_client.post('/api/settings/tests/text-model', json={}).status_code == 401
        assert anon_client.get('/api/settings/tests/fake-task/status').status_code == 401


def test_settings_endpoints_locked_for_authenticated_user(client):
    """Authenticated users should get SETTINGS_LOCKED on every settings endpoint."""
    cases = [
        ('get', '/api/settings/', None),
        ('put', '/api/settings/', {}),
        ('post', '/api/settings/reset', {}),
        ('post', '/api/settings/verify', {}),
        ('post', '/api/settings/tests/text-model', {}),
        ('get', '/api/settings/tests/fake-task/status', None),
    ]

    for method, path, payload in cases:
        if payload is None:
            resp = getattr(client, method)(path)
        else:
            resp = getattr(client, method)(path, json=payload)
        assert resp.status_code == 403
        body = resp.get_json()
        assert body is not None
        assert body.get('success') is False
        assert body.get('error', {}).get('code') == 'SETTINGS_LOCKED'


def test_settings_options_is_locked_for_authenticated_user(client):
    """Blueprint-level guard should also lock implicit OPTIONS requests."""
    resp = client.open('/api/settings/', method='OPTIONS')
    assert resp.status_code == 403
    body = resp.get_json()
    assert body is not None
    assert body.get('error', {}).get('code') == 'SETTINGS_LOCKED'


def test_startup_preflight_missing_required_env(monkeypatch):
    """Missing AI_PROVIDER_FORMAT env should fail fast at app startup."""
    app_module = importlib.import_module('app')
    app_module = importlib.reload(app_module)

    monkeypatch.delenv('AI_PROVIDER_FORMAT', raising=False)
    monkeypatch.setenv('GOOGLE_API_KEY', 'mock-api-key-for-testing')

    import pytest

    with pytest.raises(ValueError, match='AI_PROVIDER_FORMAT'):
        app_module.create_app()


def test_startup_preflight_invalid_provider(monkeypatch):
    """Invalid AI_PROVIDER_FORMAT env should fail fast at app startup."""
    app_module = importlib.import_module('app')
    app_module = importlib.reload(app_module)

    monkeypatch.setenv('AI_PROVIDER_FORMAT', 'bad-provider')
    monkeypatch.setenv('GOOGLE_API_KEY', 'mock-api-key-for-testing')

    import pytest

    with pytest.raises(ValueError, match='AI_PROVIDER_FORMAT'):
        app_module.create_app()


def test_startup_preflight_rejects_legacy_azure_openai_image_override(monkeypatch):
    """Legacy IMAGE_PROVIDER_FORMAT=azure_openai should be removed, not aliased."""
    app_module = importlib.import_module('app')
    app_module = importlib.reload(app_module)

    monkeypatch.setenv('AI_PROVIDER_FORMAT', 'gemini')
    monkeypatch.setenv('GOOGLE_API_KEY', 'mock-api-key-for-testing')
    monkeypatch.setenv('IMAGE_PROVIDER_FORMAT', 'azure_openai')

    import pytest

    with pytest.raises(ValueError, match='IMAGE_PROVIDER_FORMAT'):
        app_module.create_app()


def test_startup_preflight_allows_openai_image_backend_azure(monkeypatch):
    """IMAGE_PROVIDER_FORMAT=openai + OPENAI_IMAGE_BACKEND=azure should keep text on Gemini."""
    app_module = importlib.import_module('app')
    app_module = importlib.reload(app_module)

    monkeypatch.setenv('AI_PROVIDER_FORMAT', 'gemini')
    monkeypatch.setenv('GOOGLE_API_KEY', 'mock-api-key-for-testing')
    monkeypatch.setenv('IMAGE_PROVIDER_FORMAT', 'openai')
    monkeypatch.setenv('OPENAI_IMAGE_BACKEND', 'azure')
    monkeypatch.setenv('OPENAI_API_KEY', 'openai-key')
    monkeypatch.setenv('OPENAI_API_BASE', 'https://example.cognitiveservices.azure.com/openai/v1')
    monkeypatch.setenv('OPENAI_RESPONSES_MODEL', 'gpt-5.4')
    monkeypatch.setenv('OPENAI_IMAGE_MODEL', 'gpt-image-2')
    monkeypatch.setenv('OPENAI_IMAGE_DEPLOYMENT', 'gpt-image-2')

    app = app_module.create_app()

    assert app.config['AI_PROVIDER_FORMAT'] == 'gemini'
    assert app.config['IMAGE_PROVIDER_FORMAT'] == 'openai'


def test_startup_preflight_defaults_openai_proxy_images_to_responses(monkeypatch):
    """OPENAI_IMAGE_BACKEND=proxy should default to Responses API image mode."""
    app_module = importlib.import_module('app')
    app_module = importlib.reload(app_module)

    monkeypatch.setenv('AI_PROVIDER_FORMAT', 'gemini')
    monkeypatch.setenv('GOOGLE_API_KEY', 'mock-api-key-for-testing')
    monkeypatch.setenv('IMAGE_PROVIDER_FORMAT', 'openai')
    monkeypatch.setenv('OPENAI_IMAGE_BACKEND', 'proxy')
    monkeypatch.delenv('OPENAI_IMAGE_MODE', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'proxy-key')
    monkeypatch.setenv('OPENAI_API_BASE', 'https://proxy.example/v1')
    monkeypatch.setenv('OPENAI_RESPONSES_MODEL', 'gpt-5.4')
    monkeypatch.setenv('OPENAI_IMAGE_MODEL', 'gpt-image-2')

    app = app_module.create_app()

    assert app.config['IMAGE_PROVIDER_FORMAT'] == 'openai'


def test_output_language_reads_from_config_not_db(app):
    """/api/output-language should read from app config instead of DB settings."""
    app.config['OUTPUT_LANGUAGE'] = 'en'
    with app.test_client() as c:
        resp = c.get('/api/output-language')
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload == {'data': {'language': 'en'}}
