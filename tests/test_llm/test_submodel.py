"""Tests for sub-model (副模型) infrastructure: FallbackLLMProvider + resolver."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.llm.submodel import FallbackLLMProvider, build_sub_llm

# ---------------------------------------------------------------------------
# FallbackLLMProvider — 回退链
# ---------------------------------------------------------------------------


class TestFallbackLLMProvider:
    async def test_primary_success_no_fallback(self):
        primary = AsyncMock()
        primary.complete_json.return_value = {"ok": True}
        fallback = AsyncMock()
        wrap = FallbackLLMProvider(primary=primary, fallback=fallback)

        result = await wrap.complete_json("sys", "prompt")

        assert result == {"ok": True}
        primary.complete_json.assert_awaited_once()
        fallback.complete_json.assert_not_called()
        assert wrap.fallback_count == 0

    async def test_primary_failure_falls_back_to_main(self):
        """副模型调用失败（连接/鉴权/超时）→ 回退主模型重试一次。"""
        primary = AsyncMock()
        primary.complete_json.side_effect = ConnectionError("sub down")
        fallback = AsyncMock()
        fallback.complete_json.return_value = {"recovered": True}
        wrap = FallbackLLMProvider(primary=primary, fallback=fallback)

        result = await wrap.complete_json("sys", "prompt")

        assert result == {"recovered": True}
        primary.complete_json.assert_awaited_once()
        fallback.complete_json.assert_awaited_once()
        assert wrap.fallback_count == 1

    async def test_complete_also_falls_back(self):
        primary = AsyncMock()
        primary.complete.side_effect = TimeoutError("timeout")
        fallback = AsyncMock()
        fallback.complete.return_value = MagicMock(content="ok")
        wrap = FallbackLLMProvider(primary=primary, fallback=fallback)

        result = await wrap.complete("sys", "prompt")

        assert result.content == "ok"
        assert wrap.fallback_count == 1

    async def test_fallback_failure_propagates(self):
        """主模型也失败时异常向上传播（调用方负责降级）。"""
        primary = AsyncMock()
        primary.complete_json.side_effect = ConnectionError("sub down")
        fallback = AsyncMock()
        fallback.complete_json.side_effect = ConnectionError("main down too")
        wrap = FallbackLLMProvider(primary=primary, fallback=fallback)

        with pytest.raises(ConnectionError):
            await wrap.complete_json("sys", "prompt")


# ---------------------------------------------------------------------------
# build_sub_llm — 空 key 短路
# ---------------------------------------------------------------------------


class TestBuildSubLlm:
    async def test_empty_key_returns_main(self):
        main = AsyncMock()
        result = await build_sub_llm(
            main_llm=main, api_key="", base_url="", model="", provider="anthropic"
        )
        assert result is main

    async def test_none_main_returns_none(self):
        result = await build_sub_llm(
            main_llm=None, api_key="key", base_url="", model="m", provider="anthropic"
        )
        assert result is None

    async def test_configured_key_returns_fallback_wrapper(self):
        main = AsyncMock()
        result = await build_sub_llm(
            main_llm=main,
            api_key="key",
            base_url="",
            model="claude-haiku",
            provider="anthropic",
        )
        assert isinstance(result, FallbackLLMProvider)
        assert result.fallback is main
