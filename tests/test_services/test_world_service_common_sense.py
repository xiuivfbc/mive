"""Tests for WorldService._generate_common_sense_llm()."""

from unittest.mock import AsyncMock

import pytest

from src.models.world import WorldSource
from src.services.world_service import WorldService


def _make_service(mock_llm=None):
    """Create a WorldService with mocked dependencies."""
    repo = AsyncMock()
    extraction = AsyncMock()
    search = AsyncMock()
    llm = mock_llm or AsyncMock()
    return WorldService(repo=repo, extraction=extraction, search=search, llm=llm)


class TestGenerateCommonSenseLlm:
    """_generate_common_sense_llm() tests."""

    @pytest.mark.asyncio
    async def test_returns_string_from_valid_json(self):
        """LLM returns valid JSON with common_sense string."""
        mock_llm = AsyncMock()
        mock_llm.complete_json.return_value = {
            "common_sense": "这个世界中存在魔法体系，时间流速与现实不同。"
        }
        svc = _make_service(mock_llm)

        result = await svc._generate_common_sense_llm(
            wiki_plot="some plot",
            wiki_world_setting="some setting",
        )

        assert isinstance(result, str)
        assert "魔法体系" in result

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_string(self):
        """Empty string should return None."""
        mock_llm = AsyncMock()
        mock_llm.complete_json.return_value = {"common_sense": ""}
        svc = _make_service(mock_llm)

        result = await svc._generate_common_sense_llm(
            wiki_plot="一个发生在现代北京的爱情故事",
            wiki_world_setting="现代都市",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_input_returns_none(self):
        """No plot or setting content should return None."""
        svc = _make_service()

        result = await svc._generate_common_sense_llm(
            wiki_plot=None,
            wiki_world_setting=None,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_returns_none_graceful_fallback(self):
        """LLM returning None should fallback to None."""
        mock_llm = AsyncMock()
        mock_llm.complete_json.return_value = None
        svc = _make_service(mock_llm)

        result = await svc._generate_common_sense_llm(
            wiki_plot="some plot",
            wiki_world_setting="some setting",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_returns_non_dict_graceful_fallback(self):
        """LLM returning a list instead of dict should fallback."""
        mock_llm = AsyncMock()
        mock_llm.complete_json.return_value = ["item1", "item2"]
        svc = _make_service(mock_llm)

        result = await svc._generate_common_sense_llm(
            wiki_plot="some plot",
            wiki_world_setting="some setting",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_graceful_fallback(self):
        """LLM raising exception should fallback to None."""
        mock_llm = AsyncMock()
        mock_llm.complete_json.side_effect = RuntimeError("LLM unavailable")
        svc = _make_service(mock_llm)

        result = await svc._generate_common_sense_llm(
            wiki_plot="some plot",
            wiki_world_setting="some setting",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_no_common_sense_key(self):
        """LLM returns dict without common_sense key."""
        mock_llm = AsyncMock()
        mock_llm.complete_json.return_value = {"other_key": "value"}
        svc = _make_service(mock_llm)

        result = await svc._generate_common_sense_llm(
            wiki_plot="some plot",
            wiki_world_setting="some setting",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_returns_non_string_common_sense(self):
        """LLM returns common_sense as list instead of string."""
        mock_llm = AsyncMock()
        mock_llm.complete_json.return_value = {"common_sense": ["not", "a", "string"]}
        svc = _make_service(mock_llm)

        result = await svc._generate_common_sense_llm(
            wiki_plot="some plot",
            wiki_world_setting="some setting",
        )

        assert result is None


class TestWorldSourceCommonSenseField:
    """WorldSource should have common_sense field."""

    def test_world_source_has_common_sense_default(self):
        ws = WorldSource(title="test")
        assert ws.common_sense is None

    def test_world_source_accepts_common_sense(self):
        ws = WorldSource(title="test", common_sense="这个世界存在魔法")
        assert ws.common_sense == "这个世界存在魔法"
