"""EmbeddingRepository — CRUD + vector/tsvector/hybrid search on m25_element_embeddings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class RetrievedElement:
    element_id: str
    element_type: str  # 'element' | 'character'
    name: str
    category: str
    brief: str  # search_text truncated or stored separately
    score: float  # RRF fusion score or direct score


def _format_vector(vec: list[float]) -> str:
    """Format a float list as pgvector literal: '[0.1,0.2,...]'."""
    return "[" + ",".join(str(f) for f in vec) + "]"


class EmbeddingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert_or_update(
        self,
        world_id: str,
        element_id: str,
        element_type: str,
        name: str,
        search_text: str,
        embedding: list[float],
        tsv_text: str,
        category: str | None = None,
        tier: str | None = None,
    ) -> None:
        """UPSERT a single embedding row using raw SQL (required for pgvector types)."""
        vec_literal = _format_vector(embedding)
        # Embed vector literal directly in SQL — asyncpg chokes on :param::vector
        stmt = text(f"""
            INSERT INTO m25_element_embeddings
                (world_id, element_id, element_type, category, tier, name,
                 search_text, embedding, tsv, created_at, updated_at)
            VALUES
                (:world_id, :element_id, :element_type, :category, :tier, :name,
                 :search_text, '{vec_literal}'::vector, to_tsvector('simple', :tsv_text),
                 now(), now())
            ON CONFLICT (world_id, element_id) DO UPDATE SET
                element_type = EXCLUDED.element_type,
                category = EXCLUDED.category,
                tier = EXCLUDED.tier,
                name = EXCLUDED.name,
                search_text = EXCLUDED.search_text,
                embedding = EXCLUDED.embedding,
                tsv = EXCLUDED.tsv,
                updated_at = now()
        """)
        await self.session.execute(
            stmt,
            {
                "world_id": world_id,
                "element_id": element_id,
                "element_type": element_type,
                "category": category,
                "tier": tier,
                "name": name,
                "search_text": search_text,
                "tsv_text": tsv_text,
            },
        )

    async def search_by_vector(
        self,
        world_id: str,
        embedding: list[float],
        top_k: int = 20,
        element_types: list[str] | None = None,
        categories: list[str] | None = None,
        tiers: list[str] | None = None,
    ) -> list[RetrievedElement]:
        """Cosine distance vector search."""
        vec_literal = _format_vector(embedding)
        # Embed vector literal directly in SQL — asyncpg chokes on :param::vector
        stmt = text(f"""
            SELECT element_id, element_type, name, category,
                   substring(search_text for 200) AS brief,
                   embedding <=> '{vec_literal}'::vector AS distance
            FROM m25_element_embeddings
            WHERE world_id = :world_id
              AND (:el_type_count = 0 OR element_type = ANY(:el_types))
              AND (:cat_count = 0 OR category = ANY(:categories))
              AND (:tier_count = 0 OR tier = ANY(:tiers))
            ORDER BY embedding <=> '{vec_literal}'::vector
            LIMIT :top_k
        """)
        params: dict = {
            "world_id": world_id,
            "top_k": top_k,
            "el_types": element_types or [],
            "el_type_count": len(element_types) if element_types else 0,
            "categories": categories or [],
            "cat_count": len(categories) if categories else 0,
            "tiers": tiers or [],
            "tier_count": len(tiers) if tiers else 0,
        }
        result = await self.session.execute(stmt, params)
        rows = result.all()
        return [
            RetrievedElement(
                element_id=r[0],
                element_type=r[1],
                name=r[2],
                category=r[3] or "",
                brief=r[4] or "",
                score=1.0 - float(r[5]),  # convert distance to similarity
            )
            for r in rows
        ]

    async def search_by_tsv(
        self,
        world_id: str,
        query_text: str,
        top_k: int = 20,
        element_types: list[str] | None = None,
        categories: list[str] | None = None,
        tiers: list[str] | None = None,
    ) -> list[RetrievedElement]:
        """Full-text search using tsvector.

        Uses plainto_tsquery which AND's all terms and handles special characters safely.
        query_text is space-separated tokens from jieba.
        """
        query_text = query_text.strip()
        if not query_text:
            return []

        # plainto_tsquery AND's all terms (better precision for multi-word queries)
        # and handles special characters safely (no injection risk)
        stmt = text("""
            SELECT element_id, element_type, name, category,
                   substring(search_text for 200) AS brief,
                   ts_rank(tsv, plainto_tsquery('simple', :query)) AS rank
            FROM m25_element_embeddings
            WHERE world_id = :world_id
              AND tsv @@ plainto_tsquery('simple', :query)
              AND (:el_type_count = 0 OR element_type = ANY(:el_types))
              AND (:cat_count = 0 OR category = ANY(:categories))
              AND (:tier_count = 0 OR tier = ANY(:tiers))
            ORDER BY rank DESC
            LIMIT :top_k
        """)
        result = await self.session.execute(
            stmt,
            {
                "query": query_text,
                "world_id": world_id,
                "top_k": top_k,
                "el_types": element_types or [],
                "el_type_count": len(element_types) if element_types else 0,
                "categories": categories or [],
                "cat_count": len(categories) if categories else 0,
                "tiers": tiers or [],
                "tier_count": len(tiers) if tiers else 0,
            },
        )
        rows = result.all()
        return [
            RetrievedElement(
                element_id=r[0],
                element_type=r[1],
                name=r[2],
                category=r[3] or "",
                brief=r[4] or "",
                score=float(r[5]),
            )
            for r in rows
        ]

    async def search_hybrid(
        self,
        world_id: str,
        query_text: str,
        embedding: list[float],
        top_k: int = 10,
        bm25_top_k: int = 20,
        vec_top_k: int = 20,
        bm25_rrf_k: int = 5,
        vec_rrf_k: int = 60,
        element_types: list[str] | None = None,
        categories: list[str] | None = None,
        tiers: list[str] | None = None,
    ) -> list[RetrievedElement]:
        """Hybrid search combining BM25 + vector via RRF with separate k values."""
        import asyncio

        bm25_results, vec_results = await asyncio.gather(
            self.search_by_tsv(world_id, query_text, bm25_top_k, element_types, categories, tiers),
            self.search_by_vector(world_id, embedding, vec_top_k, element_types, categories, tiers),
        )

        # RRF fusion: score(doc) = sum(1 / (k + rank_i(doc)))
        rrf_scores: dict[str, float] = {}
        element_data: dict[str, RetrievedElement] = {}

        for rank, elem in enumerate(bm25_results, start=1):
            eid = elem.element_id
            rrf_scores[eid] = rrf_scores.get(eid, 0.0) + 1.0 / (bm25_rrf_k + rank)
            if eid not in element_data:
                element_data[eid] = elem

        for rank, elem in enumerate(vec_results, start=1):
            eid = elem.element_id
            rrf_scores[eid] = rrf_scores.get(eid, 0.0) + 1.0 / (vec_rrf_k + rank)
            if eid not in element_data:
                element_data[eid] = elem

        # Sort by RRF score descending, take top_k
        sorted_ids = sorted(rrf_scores.keys(), key=lambda eid: rrf_scores[eid], reverse=True)
        results = []
        for eid in sorted_ids[:top_k]:
            data = element_data[eid]
            results.append(
                RetrievedElement(
                    element_id=data.element_id,
                    element_type=data.element_type,
                    name=data.name,
                    category=data.category,
                    brief=data.brief,
                    score=rrf_scores[eid],
                )
            )
        return results

    async def delete_by_world(self, world_id: str) -> int:
        """Delete all embeddings for a world. Returns count of deleted rows."""
        result = await self.session.execute(
            text("DELETE FROM m25_element_embeddings WHERE world_id = :wid"),
            {"wid": world_id},
        )
        return cast(CursorResult, result).rowcount

    async def delete_by_element_id(self, world_id: str, element_id: str) -> int:
        """Delete a single embedding by world_id + element_id."""
        result = await self.session.execute(
            text("DELETE FROM m25_element_embeddings WHERE world_id = :wid AND element_id = :eid"),
            {"wid": world_id, "eid": element_id},
        )
        return cast(CursorResult, result).rowcount

    async def delete_by_world_and_type(self, world_id: str, element_type: str) -> int:
        """Delete embeddings for a world filtered by element_type."""
        result = await self.session.execute(
            text("DELETE FROM m25_element_embeddings WHERE world_id = :wid AND element_type = :et"),
            {"wid": world_id, "et": element_type},
        )
        return cast(CursorResult, result).rowcount

    async def count_by_world(self, world_id: str) -> int:
        """Count embeddings for a world."""
        result = await self.session.execute(
            text("SELECT COUNT(*) FROM m25_element_embeddings WHERE world_id = :wid"),
            {"wid": world_id},
        )
        return result.scalar_one()
