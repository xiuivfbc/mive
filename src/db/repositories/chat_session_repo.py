import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import delete, desc, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M4ChatSession, M4Message
from src.models.chat_session import ChatSession


class ChatSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        world_id: str,
        type: str,
        title: str | None = None,
        version_id: str | None = None,
        memories_enabled: bool = False,
        element_injection_ids: list[str] | None = None,
        constraints: str = "",
    ) -> ChatSession:
        row = M4ChatSession(
            id=uuid.uuid4(),
            world_id=uuid.UUID(world_id),
            type=type,
            title=title,
            version_id=uuid.UUID(version_id) if version_id else None,
            memories_enabled=memories_enabled,
            element_injection_ids=element_injection_ids,
            constraints=constraints,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def get_by_id(self, session_id: str) -> ChatSession | None:
        row = await self.session.get(M4ChatSession, uuid.UUID(session_id))
        return self._to_model(row) if row else None

    async def list_event_sessions_after(self, world_id: str, after: datetime) -> list[ChatSession]:
        stmt = (
            select(M4ChatSession)
            .where(
                M4ChatSession.world_id == uuid.UUID(world_id),
                M4ChatSession.type == "event",
                M4ChatSession.created_at > after,
            )
            .order_by(M4ChatSession.created_at)
        )
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def list_by_world(self, world_id: str, limit: int = 100) -> list[ChatSession]:
        stmt = (
            select(M4ChatSession)
            .where(M4ChatSession.world_id == uuid.UUID(world_id))
            .order_by(desc(M4ChatSession.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def update_title(self, session_id: str, title: str) -> None:
        stmt = select(M4ChatSession).where(M4ChatSession.id == uuid.UUID(session_id))
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.title = title
            await self.session.flush()

    async def update_participants(
        self,
        session_id: str,
        participants: list[dict],
        participant_mode: str,
    ) -> None:
        """Store participants as a UUID string array.

        Accepts list[dict] with ``{id, name}`` (the format returned by
        ``DialogueGenerationService.select_participants``) and extracts only
        the ``id`` values for storage.
        """
        stmt = select(M4ChatSession).where(M4ChatSession.id == uuid.UUID(session_id))
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            # Extract UUID strings from dict format, filtering out any invalid entries
            uuid_list: list[str] = []
            for p in participants:
                if isinstance(p, dict):
                    pid = p.get("id")
                    if pid:
                        uuid_list.append(str(pid))
                elif isinstance(p, str):
                    # Already a UUID string (e.g. from migrated data)
                    uuid_list.append(p)
            row.participants = uuid_list
            row.participant_mode = participant_mode
            await self.session.flush()

    async def update_last_flushed_sequence(
        self, session_id: str, last_flushed_sequence: int
    ) -> bool:
        """Update last_flushed_sequence only if current value is lower (optimistic lock).

        Issue 16 fix: prevents concurrent flushes from overwriting a higher value.
        Returns True if the update was applied, False if skipped (concurrent flush
        already advanced the value).
        """
        from sqlalchemy import update

        stmt = (
            update(M4ChatSession)
            .where(
                M4ChatSession.id == uuid.UUID(session_id),
                M4ChatSession.last_flushed_sequence < last_flushed_sequence,
            )
            .values(last_flushed_sequence=last_flushed_sequence)
        )
        result = await self.session.execute(stmt)
        return cast(CursorResult, result).rowcount > 0

    async def delete(self, session_id: str) -> bool:
        sid = uuid.UUID(session_id)
        stmt = select(M4ChatSession).where(M4ChatSession.id == sid)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return False
        # 先删消息（连同 LLM 上下文一起清除），再删 session
        await self.session.execute(delete(M4Message).where(M4Message.session_id == sid))
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def update_last_active_at(self, session_id: str) -> None:
        """Update last_active_at to current time."""
        from sqlalchemy import update

        from src.db.models import _utcnow

        stmt = (
            update(M4ChatSession)
            .where(M4ChatSession.id == uuid.UUID(session_id))
            .values(last_active_at=_utcnow())
        )
        await self.session.execute(stmt)

    async def update_session_options(
        self,
        session_id: str,
        element_injection_ids: list[str] | None = None,
        constraints: str = "",
    ) -> None:
        """Update element injection and constraint settings for a session."""
        from sqlalchemy import update

        stmt = (
            update(M4ChatSession)
            .where(M4ChatSession.id == uuid.UUID(session_id))
            .values(element_injection_ids=element_injection_ids, constraints=constraints)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    def _to_model(self, row: M4ChatSession) -> ChatSession:
        return ChatSession(
            id=str(row.id),
            world_id=str(row.world_id),
            type=row.type,
            title=row.title,
            created_at=row.created_at,
            participants=row.participants,
            participant_mode=row.participant_mode,
            memories_enabled=row.memories_enabled,
            version_id=str(row.version_id) if row.version_id else None,
            last_flushed_sequence=row.last_flushed_sequence or 0,
            last_active_at=row.last_active_at,
            element_injection_ids=row.element_injection_ids,
            constraints=row.constraints or "",
        )
