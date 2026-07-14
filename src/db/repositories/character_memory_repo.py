from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M2CharacterMemory


class _Unset(enum.Enum):
    """哨兵枚举：区分"未传参"与"显式传 None"，同时让 pyright 能通过 `is` 正确收窄类型。"""

    TOKEN = enum.auto()


_UNSET = _Unset.TOKEN


class CharacterMemoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        character_id: uuid.UUID,
        world_id: uuid.UUID,
        session_id: uuid.UUID | None,
        memory_type: str,
        content: str,
        memory_category: str | None = None,
        short_term_reflection: str | None = None,
        memory_sequence: int | None = None,
    ) -> M2CharacterMemory:
        obj = M2CharacterMemory(
            character_id=character_id,
            world_id=world_id,
            session_id=session_id,
            memory_type=memory_type,
            content=content,
            memory_category=memory_category,
            short_term_reflection=short_term_reflection,
            memory_sequence=memory_sequence,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def add_hearsay(
        self,
        character_id: uuid.UUID,
        world_id: uuid.UUID,
        session_id: uuid.UUID | None,
        content: str,
        visible_at: datetime,
        origin_event_id: uuid.UUID | None,
        propagated_from: uuid.UUID | None,
        involved_characters: list[uuid.UUID] | None,
        propagation_meta: dict | None,
        hop_count: int = 1,
        info_amount: float | None = None,
        source_character_id: uuid.UUID | None = None,
        memory_sequence: int | None = None,
    ) -> M2CharacterMemory:
        """Write a hearsay memory (propagated from another character)."""
        obj = M2CharacterMemory(
            character_id=character_id,
            world_id=world_id,
            session_id=session_id,
            memory_type="short_term",
            content=content,
            visible_at=visible_at,
            origin_event_id=origin_event_id,
            is_hearsay=True,
            propagated_from=propagated_from,
            involved_characters=involved_characters,
            propagation_meta=propagation_meta,
            hop_count=hop_count,
            info_amount=info_amount,
            source_character_id=source_character_id,
            memory_sequence=memory_sequence,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_short_term(
        self,
        character_id: uuid.UUID,
        limit: int = 5,
        include_hearsay: bool = False,
    ) -> list[M2CharacterMemory]:
        """Query short-term memories, excluding hearsay by default."""
        stmt = (
            select(M2CharacterMemory)
            .where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.memory_type == "short_term",
            )
            .order_by(M2CharacterMemory.created_at.desc())
            .limit(limit)
        )
        if not include_hearsay:
            stmt = stmt.where(M2CharacterMemory.is_hearsay == False)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_long_term(self, character_id: uuid.UUID) -> list[M2CharacterMemory]:
        result = await self.session.execute(
            select(M2CharacterMemory)
            .where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.memory_type == "long_term",
            )
            .order_by(M2CharacterMemory.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_oldest_short_term(
        self,
        character_id: uuid.UUID,
        limit: int = 5,
        exclude_categories: list[str] | None = None,
    ) -> list[M2CharacterMemory]:
        stmt = select(M2CharacterMemory).where(
            M2CharacterMemory.character_id == character_id,
            M2CharacterMemory.memory_type == "short_term",
            M2CharacterMemory.is_hearsay == False,  # noqa: E712
        )
        if exclude_categories:
            stmt = stmt.where(~M2CharacterMemory.memory_category.in_(exclude_categories))
        stmt = stmt.order_by(M2CharacterMemory.created_at.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_ids(self, ids: list[uuid.UUID]) -> None:
        await self.session.execute(delete(M2CharacterMemory).where(M2CharacterMemory.id.in_(ids)))

    async def delete_by_session(self, session_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(M2CharacterMemory).where(M2CharacterMemory.session_id == session_id)
        )

    async def list_by_session(self, session_id: uuid.UUID) -> list[M2CharacterMemory]:
        result = await self.session.execute(
            select(M2CharacterMemory)
            .where(M2CharacterMemory.session_id == session_id)
            .order_by(M2CharacterMemory.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_characters_needing_promotion(
        self,
        character_ids: list[uuid.UUID],
        threshold: int = 40,
        exclude_categories: list[str] | None = None,
    ) -> set[uuid.UUID]:
        """Only count non-hearsay short-term memories for promotion threshold.

        When exclude_categories is provided, memories with those categories
        are excluded from the count (e.g. ["trivial"] to skip trivial memories).
        """
        if not character_ids:
            return set()
        stmt = select(M2CharacterMemory.character_id).where(
            M2CharacterMemory.character_id.in_(character_ids),
            M2CharacterMemory.memory_type == "short_term",
            M2CharacterMemory.is_hearsay == False,  # noqa: E712
        )
        if exclude_categories:
            stmt = stmt.where(~M2CharacterMemory.memory_category.in_(exclude_categories))
        stmt = stmt.group_by(M2CharacterMemory.character_id).having(func.count() >= threshold)
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def count_hearsay(self, character_id: uuid.UUID) -> int:
        """Count hearsay memories for a character."""
        result = await self.session.execute(
            select(func.count())
            .select_from(M2CharacterMemory)
            .where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.is_hearsay == True,  # noqa: E712
                M2CharacterMemory.memory_type == "short_term",
            )
        )
        return result.scalar() or 0

    async def prune_hearsay(self, character_id: uuid.UUID, keep: int = 15) -> None:
        """Prune excess hearsay, keeping the newest `keep` entries.

        Uses scalar_subquery to avoid concurrent race conditions.
        """
        keep_ids = (
            select(M2CharacterMemory.id)
            .where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.is_hearsay == True,  # noqa: E712
                M2CharacterMemory.memory_type == "short_term",
            )
            .order_by(M2CharacterMemory.created_at.desc())
            .limit(keep)
        ).scalar_subquery()

        await self.session.execute(
            delete(M2CharacterMemory).where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.is_hearsay == True,  # noqa: E712
                M2CharacterMemory.memory_type == "short_term",
                ~M2CharacterMemory.id.in_(keep_ids),
            )
        )

    async def delete_hearsay_before(self, character_id: uuid.UUID, before: datetime) -> int:
        """Delete hearsay memories before a given time (virtual time).

        Returns the count of deleted records.
        """
        result = await self.session.execute(
            delete(M2CharacterMemory).where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.is_hearsay == True,  # noqa: E712
                M2CharacterMemory.memory_type == "short_term",
                M2CharacterMemory.visible_at < before,
            )
        )
        return cast(CursorResult, result).rowcount

    async def get_by_id(self, memory_id: uuid.UUID) -> M2CharacterMemory | None:
        result = await self.session.execute(
            select(M2CharacterMemory).where(M2CharacterMemory.id == memory_id)
        )
        return result.scalar_one_or_none()

    async def update_memory(
        self,
        memory_id: uuid.UUID,
        content: str | None = None,
        memory_category: str | None = None,
        short_term_reflection: str | None = None,
        perspective_detail: str | None = None,
        reflection: str | None = None,
        event_name: str | None = None,
        involved_characters: list[uuid.UUID] | None | _Unset = _UNSET,
    ) -> M2CharacterMemory | None:
        mem = await self.get_by_id(memory_id)
        if not mem:
            return None
        if content is not None:
            mem.content = content
        if mem.memory_type == "short_term":
            if memory_category is not None:
                mem.memory_category = memory_category
            if short_term_reflection is not None:
                mem.short_term_reflection = short_term_reflection
        elif mem.memory_type == "long_term":
            if perspective_detail is not None:
                mem.perspective_detail = perspective_detail
            if reflection is not None:
                mem.reflection = reflection
            if event_name is not None:
                mem.event_name = event_name
            if involved_characters is not _UNSET:
                mem.involved_characters = involved_characters or None
            # Regenerate content from structured fields (same logic as add_structured_long_term)
            if event_name is not None or perspective_detail is not None:
                parts = [mem.event_name or "", mem.perspective_detail or ""]
                mem.content = ": ".join(p for p in parts if p)
        await self.session.flush()
        return mem

    async def get_latest_by_session(self, session_id: uuid.UUID) -> M2CharacterMemory | None:
        """返回该 session 内最新一条记忆（用于"未记录消息"基线判断）。"""
        result = await self.session.execute(
            select(M2CharacterMemory)
            .where(M2CharacterMemory.session_id == session_id)
            .order_by(M2CharacterMemory.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── Multi-hop propagation methods ───────────────────────────────────────

    async def get_max_sequence(self, character_id: uuid.UUID) -> int | None:
        """Get the maximum memory_sequence for a character (short-term)."""
        result = await self.session.execute(
            select(func.max(M2CharacterMemory.memory_sequence)).where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.memory_type == "short_term",
            )
        )
        return result.scalar()

    async def get_hearsay_by_event(
        self,
        character_id: uuid.UUID,
        origin_event_id: uuid.UUID,
    ) -> M2CharacterMemory | None:
        """Look up an existing hearsay memory for a character + event combination."""
        result = await self.session.execute(
            select(M2CharacterMemory)
            .where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.origin_event_id == origin_event_id,
                M2CharacterMemory.is_hearsay == True,  # noqa: E712
                M2CharacterMemory.memory_type == "short_term",
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_hearsay_by_session(
        self,
        character_id: uuid.UUID,
        session_id: uuid.UUID,
        source_character_id: uuid.UUID | None = None,
    ) -> M2CharacterMemory | None:
        """Look up an existing hearsay memory for a character + session combination.

        Used for chat path dedup (origin_event_id is NULL).
        """
        stmt = select(M2CharacterMemory).where(
            M2CharacterMemory.character_id == character_id,
            M2CharacterMemory.session_id == session_id,
            M2CharacterMemory.origin_event_id.is_(None),  # noqa: E711
            M2CharacterMemory.is_hearsay == True,  # noqa: E712
            M2CharacterMemory.memory_type == "short_term",
        )
        if source_character_id is not None:
            stmt = stmt.where(
                M2CharacterMemory.source_character_id == source_character_id,
            )
        stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Structured long-term memory methods (P0) ─────────────────────────

    async def add_structured_long_term(
        self,
        character_id: uuid.UUID,
        world_id: uuid.UUID,
        event_name: str,
        perspective_detail: str,
        reflection: str | None = None,
        involved_characters: list[uuid.UUID] | None = None,
        session_id: uuid.UUID | None = None,
    ) -> M2CharacterMemory:
        """Create a structured long-term memory with four fields.

        content is auto-generated from event_name + perspective_detail
        for backward compatibility with free-text display.
        """
        content_parts = [event_name, perspective_detail]
        content = ": ".join(p for p in content_parts if p)

        obj = M2CharacterMemory(
            character_id=character_id,
            world_id=world_id,
            session_id=session_id,
            memory_type="long_term",
            content=content,
            event_name=event_name,
            perspective_detail=perspective_detail,
            reflection=reflection,
            involved_characters=involved_characters,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_by_event_name(
        self, character_id: uuid.UUID, event_name: str
    ) -> M2CharacterMemory | None:
        """Look up a long-term memory by event name for dedup."""
        result = await self.session.execute(
            select(M2CharacterMemory)
            .where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.memory_type == "long_term",
                M2CharacterMemory.event_name == event_name,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_event_name_for_characters(
        self, character_ids: list[uuid.UUID], event_name: str
    ) -> list[M2CharacterMemory]:
        """Return long-term memories matching event_name for the given characters."""
        if not character_ids:
            return []
        result = await self.session.execute(
            select(M2CharacterMemory)
            .where(
                M2CharacterMemory.character_id.in_(character_ids),
                M2CharacterMemory.memory_type == "long_term",
                M2CharacterMemory.event_name == event_name,
            )
            .order_by(M2CharacterMemory.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_long_term_structured(self, character_id: uuid.UUID) -> list[M2CharacterMemory]:
        """Return long-term memories that have structured fields populated."""
        result = await self.session.execute(
            select(M2CharacterMemory)
            .where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.memory_type == "long_term",
                M2CharacterMemory.event_name.isnot(None),
            )
            .order_by(M2CharacterMemory.created_at.asc())
        )
        return list(result.scalars().all())

    # ── Awareness tag methods (P1) ────────────────────────────────────────

    async def list_by_tag(self, character_id: uuid.UUID, tag: str) -> list[M2CharacterMemory]:
        """Return memories that have a specific tag."""
        result = await self.session.execute(
            select(M2CharacterMemory)
            .where(
                M2CharacterMemory.character_id == character_id,
                M2CharacterMemory.tags.any(tag),  # type: ignore[arg-type]
            )
            .order_by(M2CharacterMemory.created_at.asc())
        )
        return list(result.scalars().all())

    async def add_tag(self, memory_id: uuid.UUID, tag: str) -> None:
        """Atomically add a tag to a memory's tags array.

        Uses SQL-level array_append to avoid read-modify-write race conditions.
        The WHERE clause ensures the tag is not added twice.
        """
        stmt = (
            update(M2CharacterMemory)
            .where(
                M2CharacterMemory.id == memory_id,
                ~M2CharacterMemory.tags.any(tag),  # type: ignore[arg-type]
            )
            .values(
                tags=func.array_append(
                    func.coalesce(M2CharacterMemory.tags, []),  # type: ignore[arg-type]
                    tag,
                )
            )
        )
        await self.session.execute(stmt)

    async def list_heard_for_integration(self, character_id: uuid.UUID) -> list[M2CharacterMemory]:
        """Return memories in 'heard' state ready for integration."""
        return await self.list_by_tag(character_id, "heard")

    # ── Embedding methods for short-term memory vector search ──────────────

    @staticmethod
    def _format_vector(vec: list[float]) -> str:
        """Format a float list as pgvector literal: '[0.1,0.2,...]'."""
        return "[" + ",".join(str(f) for f in vec) + "]"

    async def set_embedding(
        self,
        memory_id: uuid.UUID,
        embedding: list[float],
    ) -> None:
        """Store embedding vector for a memory row."""
        vec_literal = self._format_vector(embedding)
        # Embed vector literal directly in SQL — asyncpg chokes on :param::vector
        await self.session.execute(
            text(
                f"UPDATE m2_character_memories "
                f"SET embedding = '{vec_literal}'::vector "
                f"WHERE id = :mid"
            ),
            {"mid": memory_id},
        )

    async def search_short_term_by_vector(
        self,
        character_id: uuid.UUID,
        query_embedding: list[float],
        limit: int = 5,
    ) -> list[M2CharacterMemory]:
        """Vector search on short-term memories using cosine distance.

        Returns memories ordered by similarity (most similar first).
        Only searches non-hearsay short-term memories that have embeddings.
        """
        vec_literal = self._format_vector(query_embedding)
        # Embed vector literal directly in SQL — asyncpg chokes on :param::vector
        stmt = text(
            f"SELECT id FROM m2_character_memories "
            f"WHERE character_id = :cid "
            f"  AND memory_type = 'short_term' "
            f"  AND is_hearsay = false "
            f"  AND embedding IS NOT NULL "
            f"ORDER BY embedding <=> '{vec_literal}'::vector "
            f"LIMIT :limit"
        )
        result = await self.session.execute(
            stmt,
            {"cid": character_id, "limit": limit},
        )
        memory_ids = [row[0] for row in result.all()]
        if not memory_ids:
            return []
        # Fetch full objects preserving vector search order
        mems = []
        for mid in memory_ids:
            mem = await self.get_by_id(mid)
            if mem is not None:
                mems.append(mem)
        return mems
