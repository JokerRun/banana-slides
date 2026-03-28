"""
Tests for image provider conversation capability and Gemini conversation adapter
"""
import pytest
from google.genai import types as genai_types
from unittest.mock import patch, MagicMock
from PIL import Image
import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))


class TestProviderCapabilityFlag:
    """Test supports_conversation_contents capability flag"""

    def test_genai_provider_supports_conversation_contents(self):
        """GenAI provider should report conversation support"""
        with patch('services.ai_providers.image.genai_provider.genai'):
            from services.ai_providers.image.genai_provider import GenAIImageProvider
            provider = GenAIImageProvider(api_key='test-key')
            assert provider.supports_conversation_contents is True

    def test_openai_provider_does_not_support_conversation_contents(self):
        """OpenAI provider should NOT report conversation support"""
        from services.ai_providers.image.openai_provider import OpenAIImageProvider
        provider = OpenAIImageProvider(api_key='test-key')
        assert provider.supports_conversation_contents is False

    def test_base_provider_defaults_to_no_conversation_support(self):
        """Base ImageProvider should default to no conversation support"""
        from services.ai_providers.image.base import ImageProvider
        assert ImageProvider.supports_conversation_contents is False


class TestGenAIConversationAdapter:
    """Test GenAI generate_image_from_conversation method"""

    def test_generate_image_from_conversation_calls_generate_content(self):
        """Should serialize conversation contents into SDK typed content objects."""
        with patch('services.ai_providers.image.genai_provider.genai'):
            from services.ai_providers.image.genai_provider import GenAIImageProvider
            provider = GenAIImageProvider(api_key='test-key')

            # Create a fake image response
            fake_image = Image.new('RGB', (100, 100), 'red')
            mock_part = MagicMock()
            mock_part.text = None
            mock_part.as_image.return_value = fake_image
            mock_response = MagicMock()
            mock_response.parts = [mock_part]

            provider.client.models.generate_content.return_value = mock_response

            contents = [
                {
                    'role': 'user',
                    'parts': [
                        'restyle this',
                        Image.new('RGB', (32, 24), 'blue'),
                    ],
                },
                {'role': 'model', 'parts': ['ok']},
            ]
            result = provider.generate_image_from_conversation(
                contents=contents,
                aspect_ratio='16:9',
                resolution='2K'
            )

            assert result is not None
            assert isinstance(result, Image.Image)
            provider.client.models.generate_content.assert_called_once()
            serialized_contents = provider.client.models.generate_content.call_args.kwargs['contents']
            assert isinstance(serialized_contents[0], genai_types.UserContent)
            assert isinstance(serialized_contents[1], genai_types.ModelContent)
            assert serialized_contents[0].parts[0].text == 'restyle this'
            assert serialized_contents[0].parts[1].inline_data.mime_type == 'image/png'
            assert serialized_contents[1].parts[0].text == 'ok'

    def test_generate_image_from_conversation_returns_last_image(self):
        """Should return the last image when multiple images in response"""
        with patch('services.ai_providers.image.genai_provider.genai'):
            from services.ai_providers.image.genai_provider import GenAIImageProvider
            provider = GenAIImageProvider(api_key='test-key')

            # First image (draft)
            draft_image = Image.new('RGB', (50, 50), 'blue')
            mock_part1 = MagicMock()
            mock_part1.text = None
            mock_part1.as_image.return_value = draft_image

            # Second image (final)
            final_image = Image.new('RGB', (200, 200), 'green')
            mock_part2 = MagicMock()
            mock_part2.text = None
            mock_part2.as_image.return_value = final_image

            mock_response = MagicMock()
            mock_response.parts = [mock_part1, mock_part2]

            provider.client.models.generate_content.return_value = mock_response

            result = provider.generate_image_from_conversation(
                contents=[{'role': 'user', 'parts': [{'text': 'x'}]}]
            )

            assert result.size == (200, 200)

    def test_generate_image_from_conversation_no_image_raises(self):
        """Should raise when response has no image"""
        with patch('services.ai_providers.image.genai_provider.genai'):
            from services.ai_providers.image.genai_provider import GenAIImageProvider
            provider = GenAIImageProvider(api_key='test-key')

            # Response with only text, no image
            mock_part = MagicMock()
            mock_part.text = "some text"
            mock_response = MagicMock()
            mock_response.parts = [mock_part]

            provider.client.models.generate_content.return_value = mock_response

            with pytest.raises(Exception):
                provider.generate_image_from_conversation(
                    contents=[{'role': 'user', 'parts': [{'text': 'x'}]}]
                )

    def test_generate_image_from_conversation_passes_config(self):
        """Should pass aspect_ratio, resolution, thinking_level to config"""
        with patch('services.ai_providers.image.genai_provider.genai'):
            from services.ai_providers.image.genai_provider import GenAIImageProvider
            provider = GenAIImageProvider(api_key='test-key')

            fake_image = Image.new('RGB', (100, 100), 'red')
            mock_part = MagicMock()
            mock_part.text = None
            mock_part.as_image.return_value = fake_image
            mock_response = MagicMock()
            mock_response.parts = [mock_part]

            provider.client.models.generate_content.return_value = mock_response

            provider.generate_image_from_conversation(
                contents=[{'role': 'user', 'parts': [{'text': 'x'}]}],
                aspect_ratio='4:3',
                resolution='4K',
                thinking_level='high'
            )

            config = provider.client.models.generate_content.call_args.kwargs['config']
            assert config.image_config.aspect_ratio == '4:3'
            assert config.image_config.image_size == '4K'
            assert str(config.thinking_config.thinking_level) == 'ThinkingLevel.HIGH'
            assert config.thinking_config.include_thoughts is True

    def test_base_provider_conversation_raises_not_implemented(self):
        """Base provider generate_image_from_conversation should raise NotImplementedError"""
        from services.ai_providers.image.base import ImageProvider

        class DummyProvider(ImageProvider):
            def generate_image(self, *args, **kwargs):
                return None

        provider = DummyProvider()
        with pytest.raises(NotImplementedError):
            provider.generate_image_from_conversation(contents=[])
