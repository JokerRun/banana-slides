"""Tests for OpenAI SDK image provider backends."""
import base64
import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))


def _png_b64(color='red', size=(32, 32)):
    img = Image.new('RGB', size, color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')


class FakeOpenAIClient:
    def __init__(self, response):
        self.responses = MagicMock()
        self.responses.create = MagicMock(return_value=response)
        self.chat = MagicMock()
        self.chat.completions.create = MagicMock(return_value=response)


def _responses_image_response(color='blue', size=(48, 27)):
    response = MagicMock()
    response.output = [
        {
            'type': 'image_generation_call',
            'status': 'completed',
            'result': _png_b64(color, size),
        }
    ]
    return response


def _chat_image_response(color='green', size=(40, 30)):
    message = MagicMock()
    message.multi_mod_content = [{'inline_data': {'data': _png_b64(color, size)}}]
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


class TestOpenAIImageProvider:
    def test_azure_backend_uses_openai_sdk_responses_with_forced_image_tool(self):
        from services.ai_providers.image.openai_provider import OpenAIImageProvider

        created_clients = []

        def client_factory(**kwargs):
            client = FakeOpenAIClient(_responses_image_response('blue', (48, 27)))
            client.kwargs = kwargs
            created_clients.append(client)
            return client

        provider = OpenAIImageProvider(
            api_key='test-key',
            api_base='https://example.cognitiveservices.azure.com/openai/v1',
            backend='azure',
            responses_model='gpt-5.4',
            image_model='gpt-image-2',
            image_deployment='gpt-image-2',
            api_version='preview',
            openai_client_factory=client_factory,
        )

        result = provider.generate_image('draw a clean slide', aspect_ratio='16:9', resolution='2K')

        assert result.size == (48, 27)
        assert provider.supports_conversation_contents is True
        assert provider.allow_conversation_fallback is False
        assert created_clients[0].kwargs == {
            'api_key': 'test-key',
            'base_url': 'https://example.cognitiveservices.azure.com/openai/v1',
            'default_headers': {'api-key': 'test-key'},
            'default_query': {'api-version': 'preview'},
            'timeout': provider.timeout,
            'max_retries': provider.max_retries,
        }
        created_clients[0].responses.create.assert_called_once()
        kwargs = created_clients[0].responses.create.call_args.kwargs
        assert kwargs == {
            'model': 'gpt-5.4',
            'input': 'draw a clean slide',
            'tools': [{
                'type': 'image_generation',
                'model': 'gpt-image-2',
                'quality': 'high',
                'size': 'auto',
                'output_format': 'png',
            }],
            'tool_choice': {'type': 'image_generation'},
            'parallel_tool_calls': True,
            'store': False,
            'extra_headers': {'x-ms-oai-image-generation-deployment': 'gpt-image-2'},
        }

    def test_azure_backend_conversation_posts_structured_responses_input(self):
        from services.ai_providers.image.openai_provider import OpenAIImageProvider

        fake_client = FakeOpenAIClient(_responses_image_response('purple', (64, 36)))
        original_slide = Image.new('RGB', (20, 10), 'white')
        template_ref = Image.new('RGB', (20, 10), 'blue')
        contents = [
            {'role': 'user', 'parts': ['global base instruction']},
            {'role': 'model', 'parts': [original_slide, template_ref]},
            {'role': 'user', 'parts': ['make the title more prominent']},
        ]
        provider = OpenAIImageProvider(
            api_key='test-key',
            api_base='https://example.cognitiveservices.azure.com/openai/v1',
            backend='azure',
            responses_model='gpt-5.4',
            image_model='gpt-image-2',
            image_deployment='gpt-image-2',
            openai_client_factory=lambda **_: fake_client,
        )

        result = provider.generate_image_from_conversation(contents, aspect_ratio='9:16', resolution='2K')

        assert result.size == (64, 36)
        kwargs = fake_client.responses.create.call_args.kwargs
        assert kwargs['tool_choice'] == {'type': 'image_generation'}
        assert kwargs['tools'][0]['size'] == '1024x1536'
        assert [message['role'] for message in kwargs['input']] == ['user', 'assistant', 'user']
        assert kwargs['input'][0]['content'] == [{'type': 'input_text', 'text': 'global base instruction'}]
        assert [part['type'] for part in kwargs['input'][1]['content']] == ['input_image', 'input_image']
        assert kwargs['input'][1]['content'][0]['image_url'].startswith('data:image/png;base64,')
        assert kwargs['input'][2]['content'] == [{'type': 'input_text', 'text': 'make the title more prominent'}]

    def test_proxy_backend_defaults_to_responses_and_supports_conversation(self):
        from services.ai_providers.image.openai_provider import OpenAIImageProvider

        fake_client = FakeOpenAIClient(_responses_image_response('teal', (72, 40)))
        contents = [
            {'role': 'user', 'parts': ['global style instruction']},
            {'role': 'user', 'parts': [Image.new('RGB', (20, 10), 'white')]},
            {'role': 'user', 'parts': ['edit this slide']},
        ]
        provider = OpenAIImageProvider(
            api_key='proxy-key',
            api_base='https://proxy.example/v1',
            backend='proxy',
            responses_model='gpt-5.4',
            image_model='gpt-image-2',
            openai_client_factory=lambda **_: fake_client,
        )

        result = provider.generate_image_from_conversation(contents, aspect_ratio='16:9', resolution='2K')

        assert result.size == (72, 40)
        assert provider.mode == 'responses'
        assert provider.supports_conversation_contents is True
        assert provider.allow_conversation_fallback is True
        fake_client.responses.create.assert_called_once()
        kwargs = fake_client.responses.create.call_args.kwargs
        assert kwargs['model'] == 'gpt-5.4'
        assert kwargs['tools'][0]['model'] == 'gpt-image-2'
        assert kwargs['tool_choice'] == {'type': 'image_generation'}
        assert 'extra_headers' not in kwargs
        assert [message['role'] for message in kwargs['input']] == ['user', 'user', 'user']

    def test_proxy_backend_can_explicitly_use_chat_completion_generation_path(self):
        from services.ai_providers.image.openai_provider import OpenAIImageProvider

        fake_client = FakeOpenAIClient(_chat_image_response('green', (40, 30)))
        provider = OpenAIImageProvider(
            api_key='proxy-key',
            api_base='https://proxy.example/v1',
            model='gemini-3-pro-image-preview',
            backend='proxy',
            mode='chat',
            openai_client_factory=lambda **_: fake_client,
        )

        result = provider.generate_image('draw through proxy')

        assert result.size == (40, 30)
        assert provider.supports_conversation_contents is False
        fake_client.chat.completions.create.assert_called_once()
        assert fake_client.chat.completions.create.call_args.kwargs['model'] == 'gemini-3-pro-image-preview'
        assert fake_client.chat.completions.create.call_args.kwargs['modalities'] == ['text', 'image']

    def test_chatgpt_backend_reads_codex_auth_json_for_openai_sdk(self, tmp_path):
        from services.ai_providers.image.openai_provider import OpenAIImageProvider

        auth_json = tmp_path / 'auth.json'
        auth_json.write_text(
            json.dumps({'tokens': {'access_token': 'chatgpt-token', 'account_id': 'acct_123'}}),
            encoding='utf-8',
        )
        created_kwargs = []

        def client_factory(**kwargs):
            created_kwargs.append(kwargs)
            return FakeOpenAIClient(_responses_image_response('orange', (32, 32)))

        provider = OpenAIImageProvider(
            api_key='',
            backend='chatgpt',
            responses_model='gpt-5.4',
            image_model='gpt-image-2',
            auth_json=str(auth_json),
            openai_client_factory=client_factory,
        )

        result = provider.generate_image('draw with local auth')

        assert result.size == (32, 32)
        assert created_kwargs[0]['api_key'] == 'chatgpt-token'
        assert created_kwargs[0]['base_url'] == 'https://chatgpt.com/backend-api/codex'
        assert created_kwargs[0]['default_headers'] == {'ChatGPT-Account-ID': 'acct_123'}

    def test_factory_uses_openai_image_backend_azure_without_azure_provider(self, monkeypatch):
        from services import ai_providers

        monkeypatch.setenv('AI_PROVIDER_FORMAT', 'gemini')
        monkeypatch.setenv('GOOGLE_API_KEY', 'google-key')
        monkeypatch.setenv('IMAGE_PROVIDER_FORMAT', 'openai')
        monkeypatch.setenv('OPENAI_IMAGE_BACKEND', 'azure')
        monkeypatch.setenv('OPENAI_API_KEY', 'openai-key')
        monkeypatch.setenv('OPENAI_API_BASE', 'https://example.cognitiveservices.azure.com/openai/v1')
        monkeypatch.setenv('OPENAI_API_VERSION', 'preview')
        monkeypatch.setenv('OPENAI_RESPONSES_MODEL', 'gpt-5.4')
        monkeypatch.setenv('OPENAI_IMAGE_MODEL', 'gpt-image-2')
        monkeypatch.setenv('OPENAI_IMAGE_DEPLOYMENT', 'gpt-image-2')

        provider = ai_providers.get_image_provider(model='ignored-gemini-model')

        assert provider.__class__.__name__ == 'OpenAIImageProvider'
        assert provider.backend == 'azure'
        assert provider.responses_model == 'gpt-5.4'
        assert provider.image_model == 'gpt-image-2'
        assert provider.image_deployment == 'gpt-image-2'
        assert ai_providers.get_provider_format() == 'gemini'

    def test_factory_defaults_proxy_image_backend_to_responses_mode(self, monkeypatch):
        from services import ai_providers

        monkeypatch.setenv('AI_PROVIDER_FORMAT', 'gemini')
        monkeypatch.setenv('GOOGLE_API_KEY', 'google-key')
        monkeypatch.setenv('IMAGE_PROVIDER_FORMAT', 'openai')
        monkeypatch.setenv('OPENAI_IMAGE_BACKEND', 'proxy')
        monkeypatch.delenv('OPENAI_IMAGE_MODE', raising=False)
        monkeypatch.setenv('OPENAI_API_KEY', 'proxy-key')
        monkeypatch.setenv('OPENAI_API_BASE', 'https://proxy.example/v1')
        monkeypatch.setenv('OPENAI_RESPONSES_MODEL', 'gpt-5.4')
        monkeypatch.setenv('OPENAI_IMAGE_MODEL', 'gpt-image-2')

        provider = ai_providers.get_image_provider(model='ignored-gemini-model')

        assert provider.__class__.__name__ == 'OpenAIImageProvider'
        assert provider.backend == 'proxy'
        assert provider.mode == 'responses'
        assert provider.supports_conversation_contents is True
