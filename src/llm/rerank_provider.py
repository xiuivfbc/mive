"""Rerank provider abstraction.

RerankProvider ABC + OpenAI-compatible (BGE Rerank) + Mock implementations.
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod

from src.config import Settings

logger = logging.getLogger(__name__)


class RerankResult:
    """Single rerank result."""

    def __init__(self, index: int, score: float):
        self.index = index
        self.score = score


class RerankProvider(ABC):
    @abstractmethod
    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[RerankResult]:
        """Rerank documents by relevance to query. Returns sorted by score desc."""


class OpenAICompatibleRerankProvider(RerankProvider):
    """Rerank provider using an OpenAI-compatible /rerank endpoint (e.g. BGE Rerank)."""

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        from openai import AsyncOpenAI

        self.model = model
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[RerankResult]:
        if not documents:
            return []
        # Truncate documents to avoid exceeding model context
        truncated = [d[:8000] for d in documents]
        response = await self._client.post(
            "/rerank",
            body={
                "model": self.model,
                "query": query,
                "documents": truncated,
                "top_n": top_n,
            },
            cast_to=dict,
        )
        results = response.get("results", [])
        return [RerankResult(index=r["index"], score=r["relevance_score"]) for r in results]


class MockRerankProvider(RerankProvider):
    """Returns random scores for local development."""

    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[RerankResult]:
        if not documents:
            return []
        indices = list(range(len(documents)))
        scored = [(i, random.random()) for i in indices]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [RerankResult(index=i, score=s) for i, s in scored[:top_n]]


def create_rerank_provider(settings: Settings) -> RerankProvider | None:
    """Factory: auto-select mock if no API key configured. Returns None if disabled."""
    if not settings.rerank_api_key:
        if settings.llm_provider == "mock":
            logger.info("RerankProvider: using MockRerankProvider (llm_provider=mock)")
            return MockRerankProvider()
        logger.info("RerankProvider: no rerank_api_key configured, rerank disabled")
        return None
    return OpenAICompatibleRerankProvider(
        api_key=settings.rerank_api_key,
        model=settings.rerank_model,
        base_url=settings.rerank_base_url,
    )
