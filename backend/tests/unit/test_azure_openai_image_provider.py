"""Tests for Azure OpenAI GPT-image provider."""
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
    def test_generate_image_posts_json_and_decodes_base64(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        response = MagicMock()
        response.json.return_value = {'data': [{'b64_json': _png_b64('blue', (40, 24))}]}

        with patch('services.ai_providers.image.azure_openai_provider.requests.post', return_value=response) as post:
            provider = AzureOpenAIImageProvider(
                api_key='test-key',
                endpoint='https://example.openai.azure.com',
                deployment='gpt-image-2',
                api_version='preview',
            )

            result = provider.generate_image('draw a clean slide', aspect_ratio='16:9', resolution='2K')

        assert result.size == (40, 24)
        post.assert_called_once()
        assert post.call_args.args[0] == 'https://example.openai.azure.com/openai/v1/images/generations?api-version=preview'
        assert post.call_args.kwargs['headers']['api-key'] == 'test-key'
        assert post.call_args.kwargs['json'] == {
            'model': 'gpt-image-2',
            'prompt': 'draw a clean slide',
            'n': 1,
            'size': '1920x1088',
            'quality': 'high',
            'output_format': 'png',
        }

    def test_generate_image_with_reference_images_posts_multipart_edit(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        response = MagicMock()
        response.json.return_value = {'data': [{'b64_json': _png_b64('green')}]}
        ref_image = Image.new('RGB', (20, 10), 'white')

        with patch('services.ai_providers.image.azure_openai_provider.requests.post', return_value=response) as post:
            provider = AzureOpenAIImageProvider(
                api_key='test-key',
                image_generation_url='https://example.cognitiveservices.azure.com/openai/deployments/gpt-image-2/images/generations?api-version=2024-02-01',
                deployment='gpt-image-2',
            )

            result = provider.generate_image('restyle this slide', ref_images=[ref_image], aspect_ratio='4:3', resolution='2K')

        assert result.size == (32, 32)
        post.assert_called_once()
        assert post.call_args.args[0] == 'https://example.cognitiveservices.azure.com/openai/deployments/gpt-image-2/images/edits?api-version=2024-02-01'
        assert post.call_args.kwargs['headers']['api-key'] == 'test-key'
        assert post.call_args.kwargs['data'] == {
            'prompt': 'restyle this slide',
            'n': '1',
            'size': '1600x1200',
            'quality': 'high',
            'output_format': 'png',
        }
        files = post.call_args.kwargs['files']
        assert len(files) == 1
        assert files[0][0] == 'image[]'
        assert files[0][1][0] == 'reference_1.png'
        assert files[0][1][2] == 'image/png'

    def test_reference_image_falls_back_to_generation_when_edit_endpoint_unavailable(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        edit_response = MagicMock()
        edit_response.status_code = 404
        edit_response.raise_for_status.side_effect = requests.HTTPError(response=edit_response)

        generation_response = MagicMock()
        generation_response.json.return_value = {'data': [{'b64_json': _png_b64('purple', (24, 24))}]}

        ref_image = Image.new('RGB', (20, 10), 'white')
        with patch(
            'services.ai_providers.image.azure_openai_provider.requests.post',
            side_effect=[edit_response, generation_response],
        ) as post:
            provider = AzureOpenAIImageProvider(
                api_key='test-key',
                image_generation_url='https://example.cognitiveservices.azure.com/openai/deployments/gpt-image-2/images/generations?api-version=2024-02-01',
                deployment='gpt-image-2',
            )

            result = provider.generate_image('generate from style', ref_images=[ref_image])

        assert result.size == (24, 24)
        assert post.call_count == 2
        assert post.call_args_list[0].args[0].endswith('/images/edits?api-version=2024-02-01')
        assert post.call_args_list[1].args[0].endswith('/images/generations?api-version=2024-02-01')
        assert 'files' not in post.call_args_list[1].kwargs

    def test_size_mapping_uses_gpt_image_2_valid_multiples_of_16(self):
        from services.ai_providers.image.azure_openai_provider import AzureOpenAIImageProvider

        provider = AzureOpenAIImageProvider(api_key='test-key', endpoint='https://example.openai.azure.com')

        assert provider._resolve_size('16:9', '1K') == '1280x720'
        assert provider._resolve_size('16:9', '2K') == '1920x1088'
        assert provider._resolve_size('16:9', '4K') == '3840x2160'
        assert provider._resolve_size('1:1', '4K') == '2880x2880'

    def test_factory_uses_image_provider_format_without_changing_text_provider_format(self, monkeypatch):
        from services import ai_providers

        monkeypatch.setenv('AI_PROVIDER_FORMAT', 'gemini')
        monkeypatch.setenv('GOOGLE_API_KEY', 'google-key')
        monkeypatch.setenv('IMAGE_PROVIDER_FORMAT', 'azure_openai')
        monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'azure-key')
        monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://example.openai.azure.com')

        provider = ai_providers.get_image_provider(model='gpt-image-2')

        assert provider.__class__.__name__ == 'AzureOpenAIImageProvider'
        assert ai_providers.get_provider_format() == 'gemini'
