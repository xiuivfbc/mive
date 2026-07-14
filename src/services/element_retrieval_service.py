"""ElementRetrievalService — hybrid retrieval + embedding rebuild pipeline."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.db.repositories.embedding_repo import EmbeddingRepository, RetrievedElement
from src.llm.embedding_provider import EmbeddingProvider
from src.utils.text_processing import build_tsv, build_tsv_batch

if TYPE_CHECKING:
    from src.db.repositories.character_repo import CharacterRepository
    from src.db.repositories.world_repo import WorldRepository

logger = logging.getLogger(__name__)

_MAX_TEXT_LEN = 2000


def _build_element_text(name: str, brief: str, detail: str) -> str:
    """Build search text for a non-character element."""
    text = f"{name}\n{brief}\n{detail}"
    return text[:_MAX_TEXT_LEN]


def _build_character_text(name: str, profile: dict) -> str:
    """Build search text for a character."""
    brief = profile.get("brief", "")
    detail = profile.get("detail", "")
    text = f"{name}\n{brief}\n{detail}"
    return text[:_MAX_TEXT_LEN]


class ElementRetrievalService:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        embedding_repo: EmbeddingRepository,
        world_repo: WorldRepository | None = None,
        character_repo: CharacterRepository | None = None,
        retrieval_top_k: int = 10,
        retrieval_bm25_top_k: int = 20,
        retrieval_vec_top_k: int = 20,
        retrieval_bm25_rrf_k: int = 5,
        retrieval_vec_rrf_k: int = 60,
    ):
        self.embedding_provider = embedding_provider
        self.embedding_repo = embedding_repo
        self.world_repo = world_repo
        self.character_repo = character_repo
        self.retrieval_top_k = retrieval_top_k
        self.retrieval_bm25_top_k = retrieval_bm25_top_k
        self.retrieval_vec_top_k = retrieval_vec_top_k
        self.retrieval_bm25_rrf_k = retrieval_bm25_rrf_k
        self.retrieval_vec_rrf_k = retrieval_vec_rrf_k

    async def retrieve(
        self,
        world_id: str,
        query: str,
        *,
        top_k: int | None = None,
        element_types: list[str] | None = None,
        categories: list[str] | None = None,
        tiers: list[str] | None = None,
    ) -> list[RetrievedElement]:
        """Hybrid retrieval: BM25 + vector via RRF."""
        k = top_k or self.retrieval_top_k
        try:
            # Tokenize query for BM25
            tsv_query = await build_tsv(query)

            # Get query embedding
            embeddings = await self.embedding_provider.embed([query])
            if not embeddings:
                logger.warning("[retrieval] embedding returned empty for query")
                return []
            query_embedding = embeddings[0]

            results = await self.embedding_repo.search_hybrid(
                world_id=world_id,
                query_text=tsv_query,
                embedding=query_embedding,
                top_k=k,
                bm25_top_k=self.retrieval_bm25_top_k,
                vec_top_k=self.retrieval_vec_top_k,
                bm25_rrf_k=self.retrieval_bm25_rrf_k,
                vec_rrf_k=self.retrieval_vec_rrf_k,
                element_types=element_types,
                categories=categories,
                tiers=tiers,
            )
            return results
        except Exception:
            logger.warning("[retrieval] hybrid search failed for world=%s", world_id, exc_info=True)
            # Rollback to clear InFailedSQLTransactionError state
            try:
                await self.embedding_repo.session.rollback()
            except Exception:
                pass
            return []

    async def rebuild_embeddings(self, world_id: str) -> bool:
        """Full rebuild: delete all + re-generate from world_doc + M2Character.

        Returns True on success (including the no-items case), False if the
        rebuild could not complete — callers should surface this rather than
        silently treating embedding rebuild as always successful.
        """
        try:
            if self.world_repo is None:
                logger.warning(
                    "[rebuild_embeddings] world_repo not available, skip world=%s",
                    world_id,
                )
                return False

            # Delete existing
            await self.embedding_repo.delete_by_world(world_id)

            # Load world doc
            world_doc = await self.world_repo.get(world_id)
            if not world_doc:
                logger.warning("[rebuild_embeddings] world_doc not found for world=%s", world_id)
                return False

            world_user_char_id = (
                str(world_doc.user_character_id) if world_doc.user_character_id else None
            )

            # Collect all items to embed
            items: list[dict] = []

            # Non-character elements from world_doc
            for elem in world_doc.elements or []:
                # Skip character elements (they live in M2Character)
                if elem.category and ("人物" in elem.category or "角色" in elem.category):
                    continue
                items.append(
                    {
                        "element_id": elem.id,
                        "element_type": "element",
                        "name": elem.name,
                        "search_text": _build_element_text(elem.name, elem.brief, elem.detail),
                        "category": elem.category,
                        "tier": None,
                    }
                )

            # Characters from M2Character (exclude user character)
            if self.character_repo:
                characters = await self.character_repo.list_by_world(world_id)
                for char in characters:
                    if world_user_char_id and char.id == world_user_char_id:
                        continue
                    profile = char.profile or {}
                    items.append(
                        {
                            "element_id": f"char_{char.id}",
                            "element_type": "character",
                            "name": char.name,
                            "search_text": _build_character_text(char.name, profile),
                            "category": None,
                            "tier": char.tier,
                        }
                    )

            if not items:
                logger.info("[rebuild_embeddings] no items to embed for world=%s", world_id)
                return True

            # Batch embed with chunking (embedding APIs typically limit to 2048 per call)
            _EMBED_BATCH_SIZE = 512  # noqa: N806
            texts = [item["search_text"] for item in items]
            custom_names = [item["name"] for item in items]

            all_embeddings: list[list[float]] = []
            for i in range(0, len(texts), _EMBED_BATCH_SIZE):
                chunk = texts[i : i + _EMBED_BATCH_SIZE]
                chunk_embeddings = await self.embedding_provider.embed(chunk)
                all_embeddings.extend(chunk_embeddings)

            if len(all_embeddings) != len(items):
                logger.error(
                    "[rebuild_embeddings] embedding count mismatch: got %d expected %d",
                    len(all_embeddings),
                    len(items),
                )
                return False

            # Build tsvector for all items in one to_thread call
            tsv_texts = await build_tsv_batch(texts, custom_words=custom_names)

            # UPSERT all
            for item, emb, tsv_text in zip(items, all_embeddings, tsv_texts, strict=True):
                await self.embedding_repo.insert_or_update(
                    world_id=world_id,
                    element_id=item["element_id"],
                    element_type=item["element_type"],
                    name=item["name"],
                    search_text=item["search_text"],
                    embedding=emb,
                    tsv_text=tsv_text,
                    category=item["category"],
                    tier=item["tier"],
                )

            await self.embedding_repo.session.flush()
            count = await self.embedding_repo.count_by_world(world_id)
            logger.info("[rebuild_embeddings] completed world=%s total=%d", world_id, count)
            return True

        except Exception:
            logger.warning("[rebuild_embeddings] failed for world=%s", world_id, exc_info=True)
            # A DBAPIError leaves the session's transaction unusable until
            # rolled back — without this, the caller's session.commit() would
            # raise PendingRollbackError and mask the real failure.
            await self.embedding_repo.session.rollback()
            return False

    async def update_single_embedding(
        self,
        world_id: str,
        element_id: str,
        element_type: str,
        name: str,
        search_text: str,
        category: str | None = None,
        tier: str | None = None,
    ) -> None:
        """Single UPSERT for incremental updates."""
        try:
            embeddings = await self.embedding_provider.embed([search_text])
            if not embeddings:
                logger.warning("[update_single] embedding returned empty for %s", element_id)
                return
            tsv_text = await build_tsv(search_text, custom_words=[name])
            await self.embedding_repo.insert_or_update(
                world_id=world_id,
                element_id=element_id,
                element_type=element_type,
                name=name,
                search_text=search_text,
                embedding=embeddings[0],
                tsv_text=tsv_text,
                category=category,
                tier=tier,
            )
            await self.embedding_repo.session.flush()
        except Exception:
            logger.warning(
                "[update_single] failed for element=%s world=%s",
                element_id,
                world_id,
                exc_info=True,
            )

    async def delete_by_world(self, world_id: str) -> None:
        """Delete all embeddings for a world."""
        try:
            await self.embedding_repo.delete_by_world(world_id)
            await self.embedding_repo.session.flush()
        except Exception:
            logger.warning("[delete_by_world] failed for world=%s", world_id, exc_info=True)


async def retrieve_as_context(
    service: ElementRetrievalService | None,
    *,
    world_id: str,
    query: str,
    world_doc=None,
    top_k: int = 12,
    detail_budget: int = 1200,
) -> str:
    """Retrieve relevant elements and format as LLM prompt text block.

    Falls back to loading all non-character elements from world_doc if
    retrieval service is unavailable or returns nothing.
    """
    elements: list = []

    # Try retrieval-augmented search
    if service is not None:
        try:
            results = await service.retrieve(world_id, query, top_k=top_k)
            if results:
                elements = [
                    type(
                        "Elem",
                        (),
                        {
                            "category": r.category or "其他",
                            "name": r.name,
                            "brief": r.brief or "",
                            "detail": r.brief or "",
                        },
                    )()
                    for r in results
                ]
        except Exception:
            logger.warning(
                "[retrieve_as_context] retrieval failed for world=%s, falling back",
                world_id,
                exc_info=True,
            )

    # Fallback: load from world_doc
    if not elements and world_doc:
        all_elems = getattr(world_doc, "elements", None) or []
        non_char = [
            e
            for e in all_elems
            if e.category and "人物" not in e.category and "角色" not in e.category
        ]
        non_char.sort(key=lambda e: e.category)
        elements = non_char[:top_k]

    if not elements:
        return ""

    # Format as text block
    lines: list[str] = []
    used = 0
    for e in elements:
        brief = getattr(e, "brief", "") or ""
        detail = getattr(e, "detail", "") or ""
        line = f"  [{e.category}] {e.name}：{brief}"
        if detail:
            line += f"（{detail}）"
        if used + len(line) > detail_budget:
            remaining = detail_budget - used
            if remaining > 20:
                lines.append(line[:remaining] + "…")
            break
        lines.append(line)
        used += len(line)

    return "\n".join(lines)
