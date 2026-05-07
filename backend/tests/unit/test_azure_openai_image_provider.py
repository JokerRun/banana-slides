"""Tests for Azure OpenAI Responses GPT-image provider."""
import base64
import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))


def _png_b64(color='red', size=(32, 32)):
    img = Image.new('RGB', size, color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')


class TestAzureOpenAIImageProvider:
    def test_generate_image_posts_responses_json_and_decodes_base64(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            'output': [
                {
                    'type': 'image_generation_call',
                    'status': 'completed',
                    'result': _png_b64('blue', (48, 27)),
                }
            ]
        }

        with patch('services.ai_providers.image.azure_openai_provider.requests.post', return_value=response) as post:
            provider = AzureOpenAIImageProvider(
                api_key='test-key',
                responses_url='https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview',
                responses_model='gpt-5.4',
                image_deployment='gpt-image-2',
            )

            result = provider.generate_image('draw a clean slide', aspect_ratio='16:9', resolution='2K')

        assert result.size == (48, 27)
        post.assert_called_once()
        assert post.call_args.args[0] == 'https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview'
        assert post.call_args.kwargs['headers'] == {
            'api-key': 'test-key',
            'Content-Type': 'application/json',
            'x-ms-oai-image-generation-deployment': 'gpt-image-2',
        }
        assert post.call_args.kwargs['json'] == {
            'model': 'gpt-5.4',
            'input': 'draw a clean slide',
            'tools': [{
                'type': 'image_generation',
                'action': 'generate',
                'quality': 'high',
                'size': '1536x1024',
                'output_format': 'png',
            }],
        }

    def test_generate_image_with_reference_images_posts_responses_edit(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            'output': [
                {
                    'type': 'image_generation_call',
                    'status': 'completed',
                    'result': _png_b64('green', (40, 30)),
                }
            ]
        }
        ref_image = Image.new('RGB', (20, 10), 'white')

        with patch('services.ai_providers.image.azure_openai_provider.requests.post', return_value=response) as post:
            provider = AzureOpenAIImageProvider(
                api_key='test-key',
                responses_url='https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview',
                responses_model='gpt-5.4',
                image_deployment='gpt-image-2',
            )

            result = provider.generate_image('restyle this slide', ref_images=[ref_image], aspect_ratio='4:3', resolution='2K')

        assert result.size == (40, 30)
        post.assert_called_once()
        payload = post.call_args.kwargs['json']
        assert payload['model'] == 'gpt-5.4'
        assert payload['tools'] == [{
            'type': 'image_generation',
            'action': 'edit',
            'quality': 'high',
            'size': '1536x1024',
            'output_format': 'png',
        }]
        assert payload['input'][0]['role'] == 'user'
        content = payload['input'][0]['content']
        assert content[0] == {'type': 'input_text', 'text': 'restyle this slide'}
        assert content[1]['type'] == 'input_image'
        assert content[1]['image_url'].startswith('data:image/png;base64,')

    def test_generate_image_from_conversation_posts_structured_multi_turn_request(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            'output': [
                {
                    'type': 'image_generation_call',
                    'status': 'completed',
                    'result': _png_b64('purple', (64, 36)),
                }
            ]
        }
        original_slide = Image.new('RGB', (20, 10), 'white')
        template_ref = Image.new('RGB', (20, 10), 'blue')
        current_image = Image.new('RGB', (20, 10), 'green')
        contents = [
            {'role': 'user', 'parts': ['global base instruction']},
            {'role': 'user', 'parts': [original_slide, template_ref]},
            {'role': 'user', 'parts': [current_image]},
            {'role': 'user', 'parts': ['make the title more prominent']},
        ]

        with patch('services.ai_providers.image.azure_openai_provider.requests.post', return_value=response) as post:
            provider = AzureOpenAIImageProvider(
                api_key='test-key',
                responses_url='https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview',
                responses_model='gpt-5.4',
                image_deployment='gpt-image-2',
            )

            result = provider.generate_image_from_conversation(contents, aspect_ratio='16:9', resolution='2K')

        assert provider.supports_conversation_contents is True
        assert result.size == (64, 36)
        payload = post.call_args.kwargs['json']
        assert payload['model'] == 'gpt-5.4'
        assert payload['tools'] == [{
            'type': 'image_generation',
            'action': 'edit',
            'quality': 'high',
            'size': '1536x1024',
            'output_format': 'png',
        }]
        assert [message['role'] for message in payload['input']] == ['user', 'user', 'user', 'user']
        assert payload['input'][0]['content'] == [{'type': 'input_text', 'text': 'global base instruction'}]
        assert [part['type'] for part in payload['input'][1]['content']] == ['input_image', 'input_image']
        assert payload['input'][1]['content'][0]['image_url'].startswith('data:image/png;base64,')
        assert payload['input'][2]['content'][0]['type'] == 'input_image'
        assert payload['input'][3]['content'] == [{'type': 'input_text', 'text': 'make the title more prominent'}]

    def test_engine_overloaded_is_retried_before_success(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        overloaded = MagicMock()
        overloaded.status_code = 400
        overloaded.json.return_value = {'error': {'message': 'Engine is overloaded'}}
        overloaded.raise_for_status.side_effect = requests.HTTPError(response=overloaded)
        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {
            'output': [{'type': 'image_generation_call', 'status': 'completed', 'result': _png_b64('green', (64, 36))}]
        }

        with patch(
            'services.ai_providers.image.azure_openai_provider.requests.post',
            side_effect=[overloaded, success],
        ) as post, patch('services.ai_providers.image.azure_openai_provider.time.sleep') as sleep:
            provider = AzureOpenAIImageProvider(
                api_key='test-key',
                responses_url='https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview',
                responses_model='gpt-5.4',
                image_deployment='gpt-image-2',
                max_retries=1,
            )

            result = provider.generate_image('generate from style')

        assert result.size == (64, 36)
        assert post.call_count == 2
        sleep.assert_called_once()

    def test_generate_image_normalizes_landscape_output_to_requested_aspect_ratio(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            'output': [
                {
                    'type': 'image_generation_call',
                    'status': 'completed',
                    # Azure currently returns this landscape size for 16:9 requests.
                    'result': _png_b64('blue', (1536, 1024)),
                }
            ]
        }

        with patch('services.ai_providers.image.azure_openai_provider.requests.post', return_value=response):
            provider = AzureOpenAIImageProvider(
                api_key='test-key',
                responses_url='https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview',
            )

            result = provider.generate_image('make a PPT slide', aspect_ratio='16:9', resolution='2K')

        assert result.size == (1536, 864)

    def test_size_mapping_uses_azure_responses_supported_sizes(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        provider = AzureOpenAIImageProvider(
            api_key='test-key',
            responses_url='https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview',
        )

        assert provider._resolve_size('16:9', '1K') == '1536x1024'
        assert provider._resolve_size('4:3', '2K') == '1536x1024'
        assert provider._resolve_size('9:16', '4K') == '1024x1536'
        assert provider._resolve_size('1:1', '4K') == '1024x1024'

    def test_factory_uses_image_provider_format_without_changing_text_provider_format(self, monkeypatch):
        from services import ai_providers

        monkeypatch.setenv('AI_PROVIDER_FORMAT', 'gemini')
        monkeypatch.setenv('GOOGLE_API_KEY', 'google-key')
        monkeypatch.setenv('IMAGE_PROVIDER_FORMAT', 'azure_openai')
        monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'azure-key')
        monkeypatch.setenv('AZURE_OPENAI_RESPONSES_URL', 'https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview')
        monkeypatch.setenv('AZURE_OPENAI_RESPONSES_MODEL', 'gpt-5.4')
        monkeypatch.setenv('AZURE_OPENAI_IMAGE_DEPLOYMENT', 'gpt-image-2')

        provider = ai_providers.get_image_provider(model='gpt-image-2')

        assert provider.__class__.__name__ == 'AzureOpenAIImageProvider'
        assert provider.responses_model == 'gpt-5.4'
        assert provider.image_deployment == 'gpt-image-2'
        assert ai_providers.get_provider_format() == 'gemini'

    def test_factory_defaults_azure_image_deployment_to_gpt_image_2(self, monkeypatch):
        from services import ai_providers

        monkeypatch.setenv('AI_PROVIDER_FORMAT', 'gemini')
        monkeypatch.setenv('GOOGLE_API_KEY', 'google-key')
        monkeypatch.setenv('IMAGE_PROVIDER_FORMAT', 'azure_openai')
        monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'azure-key')
        monkeypatch.setenv('AZURE_OPENAI_RESPONSES_URL', 'https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview')
        monkeypatch.setenv('IMAGE_MODEL', 'gemini-3-pro-image-preview')
        monkeypatch.delenv('AZURE_OPENAI_IMAGE_DEPLOYMENT', raising=False)

        provider = ai_providers.get_image_provider(model='gemini-3-pro-image-preview')

        assert provider.image_deployment == 'gpt-image-2'
