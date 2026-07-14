"""Tests for SearchService - Tavily web search integration."""

from unittest.mock import AsyncMock, patch

import pytest


class TestSearchService:
    @pytest.fixture
    def mock_tavily(self):
        """Mock tavily SDK。"""
        with patch("src.services.search_service.AsyncTavilyClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            yield mock_cls, mock_client

    @pytest.fixture
    def service(self, mock_tavily):
        from src.services.search_service import SearchService

        return SearchService(api_key="test-key")

    async def test_search_returns_results(self, service, mock_tavily):
        """search() 应返回 SearchResult 列表。"""
        _, mock_client = mock_tavily
        mock_client.search.return_value = {
            "results": [
                {
                    "url": "https://zh.wikipedia.org/wiki/三体",
                    "title": "三体 (小说)",
                    "content": "《三体》是刘慈欣创作的科幻小说...",
                    "score": 0.95,
                },
            ]
        }

        from src.services.search_service import SearchResult

        results = await service.search("三体 刘慈欣")

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].url == "https://zh.wikipedia.org/wiki/三体"
        assert results[0].score == 0.95

    async def test_search_passes_allowed_domains(self, service, mock_tavily):
        """search() 应将 allowed_domains 传给 Tavily。"""
        _, mock_client = mock_tavily
        mock_client.search.return_value = {"results": []}

        await service.search(
            "三体",
            allowed_domains=["wikipedia.org", "baike.baidu.com"],
        )

        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["include_domains"] == ["wikipedia.org", "baike.baidu.com"]

    async def test_search_handles_empty_response(self, service, mock_tavily):
        """搜索无结果时应返回空列表。"""
        _, mock_client = mock_tavily
        mock_client.search.return_value = {"results": []}

        results = await service.search("不存在的内容")
        assert results == []

    async def test_search_respects_max_results(self, service, mock_tavily):
        """search() 应将 max_results 传给 Tavily。"""
        _, mock_client = mock_tavily
        mock_client.search.return_value = {"results": []}

        await service.search("测试", max_results=3)

        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["max_results"] == 3
