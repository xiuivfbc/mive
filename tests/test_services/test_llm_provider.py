"""Tests for LLM adapter layer."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


class TestLLMProviderInterface:
    def test_provider_is_abstract(self):
        """LLMProvider 不能直接实例化。"""
        from src.llm.base import LLMProvider

        with pytest.raises(TypeError):
            LLMProvider()


class TestAnthropicProvider:
    @staticmethod
    def _make_response(text="这是一个测试响应"):
        """构造可序列化的 anthropic 响应 mock，避免 MagicMock 属性污染 JSON log。"""
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        content_block = SimpleNamespace(text=text)
        return SimpleNamespace(
            content=[content_block],
            model="claude-sonnet-4-20250514",
            usage=usage,
            stop_reason="end_turn",
        )

    @pytest.fixture
    def mock_anthropic(self):
        """Mock anthropic SDK 的 AsyncAnthropic client。"""
        with patch("src.llm.anthropic_provider.anthropic") as mock:
            mock_client = AsyncMock()
            mock.AsyncAnthropic.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=self._make_response())
            yield mock, mock_client

    async def test_complete_returns_llm_response(self, mock_anthropic):
        """complete() 应返回 LLMResponse dataclass。"""
        from src.llm.anthropic_provider import AnthropicProvider
        from src.llm.base import LLMResponse

        provider = AnthropicProvider(api_key="test-key")
        result = await provider.complete(
            system="你是一个助手",
            prompt="你好",
        )

        assert isinstance(result, LLMResponse)
        assert result.content == "这是一个测试响应"
        assert result.model == "claude-sonnet-4-20250514"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    async def test_complete_passes_parameters(self, mock_anthropic):
        """complete() 应正确传递 system, prompt, temperature, max_tokens。"""
        from src.llm.anthropic_provider import AnthropicProvider

        mock_module, mock_client = mock_anthropic

        provider = AnthropicProvider(api_key="test-key")
        await provider.complete(
            system="系统提示",
            prompt="用户输入",
            temperature=0.5,
            max_tokens=2048,
        )

        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["system"] == "系统提示"
        assert call_kwargs.kwargs["messages"] == [{"role": "user", "content": "用户输入"}]
        assert call_kwargs.kwargs["temperature"] == 0.5
        assert call_kwargs.kwargs["max_tokens"] == 2048

    async def test_complete_json_parses_json(self, mock_anthropic):
        """complete_json() 应解析 JSON 响应。"""
        mock_module, mock_client = mock_anthropic

        json_content = json.dumps([{"name": "三体世界", "category": "地理环境"}])
        mock_client.messages.create = AsyncMock(return_value=self._make_response(text=json_content))

        from src.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key")
        result = await provider.complete_json(
            system="返回JSON",
            prompt="提取元素",
        )

        assert isinstance(result, list)
        assert result[0]["name"] == "三体世界"


class TestLLMFactory:
    def test_create_anthropic_provider(self):
        """factory 应根据 provider 名创建 AnthropicProvider。"""
        from src.llm.anthropic_provider import AnthropicProvider
        from src.llm.factory import create_llm

        provider = create_llm("anthropic", "test-key", model="claude-sonnet-4-20250514")
        assert isinstance(provider, AnthropicProvider)

    def test_create_openai_provider(self):
        """factory 应根据 provider 名创建 OpenAIProvider。"""
        from src.llm.factory import create_llm
        from src.llm.openai_provider import OpenAIProvider

        provider = create_llm("openai", "test-key", model="gpt-4o")
        assert isinstance(provider, OpenAIProvider)

    def test_create_unknown_provider_raises(self):
        """未知 provider 应抛出 ValueError。"""
        from src.llm.factory import create_llm

        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm("unknown", "test-key", model="some-model")

    def test_create_with_custom_model(self):
        """factory 应支持自定义模型名。"""
        from src.llm.factory import create_llm

        provider = create_llm("anthropic", "test-key", model="claude-haiku-4-5-20251001")
        assert provider.model == "claude-haiku-4-5-20251001"
