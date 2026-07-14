"""Embedding provider abstraction.

EmbeddingProvider ABC + OpenAI-compatible + Mock implementations.
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod

from src.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float vectors."""


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using an OpenAI-compatible API."""

    def __init__(self, api_key: str, model: str, base_url: str = "", dimensions: int = 768):
        from openai import AsyncOpenAI

        self.model = model
        self.dimensions = dimensions
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Truncate very long texts (embedding models typically 8192 tokens ~ 32k chars)
        truncated = [t[:32000] for t in texts]
        response = await self._client.embeddings.create(
            model=self.model,
            input=truncated,
        )
        return [item.embedding for item in response.data]


class MockEmbeddingProvider(EmbeddingProvider):
    """Returns random vectors for local development."""

    def __init__(self, dimensions: int = 768):
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[random.random() for _ in range(self.dimensions)] for _ in texts]


def create_embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    """Factory: auto-select mock if no API key configured. Returns None if disabled."""
    dim = settings.embedding_dim
    if not settings.embedding_api_key:
        if settings.llm_provider == "mock":
            logger.info("EmbeddingProvider: using MockEmbeddingProvider (llm_provider=mock)")
            return MockEmbeddingProvider(dimensions=dim)
        logger.warning("EmbeddingProvider: no embedding_api_key configured, embedding disabled")
        return None
    return OpenAICompatibleEmbeddingProvider(
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        dimensions=dim,
    )
