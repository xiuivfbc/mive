"""Text processing utilities for vector retrieval.

jieba Chinese tokenization + tsvector building.
"""

from __future__ import annotations

import asyncio


def build_tsv_sync(text: str, custom_words: list[str] | None = None) -> str:
    """Build a space-separated token string using jieba.

    This is the synchronous (CPU-bound) core. Wrap with build_tsv() for async usage.
    """
    import jieba

    if custom_words:
        for w in custom_words:
            jieba.add_word(w)
    words = jieba.lcut(text)
    return " ".join(w.strip() for w in words if w.strip())


async def build_tsv(text: str, custom_words: list[str] | None = None) -> str:
    """Async wrapper for build_tsv_sync using asyncio.to_thread()."""
    return await asyncio.to_thread(build_tsv_sync, text, custom_words)


async def build_tsv_batch(texts: list[str], custom_words: list[str] | None = None) -> list[str]:
    """Batch tokenization: all texts in a single to_thread call (efficient for bulk)."""

    def _batch() -> list[str]:
        if custom_words:
            import jieba

            for w in custom_words:
                jieba.add_word(w)
        return [build_tsv_sync(t) for t in texts]

    return await asyncio.to_thread(_batch)
