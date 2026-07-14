import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import delete, desc, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M4Message
from src.models.message import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, message: Message) -> Message:
        row = M4Message(
            id=uuid.UUID(message.id),
            world_id=uuid.UUID(message.world_id),
            session_id=uuid.UUID(message.session_id) if message.session_id else None,
            type=message.type,
            sender_type=message.sender_type,
            sender_id=uuid.UUID(message.sender_id) if message.sender_id else None,
            content=message.content,
            is_key_message=message.is_key_message,
            user_participated=message.user_participated,
            sequence=message.sequence,
            idempotency_key=message.idempotency_key,
            status=message.status,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def create_batch(self, messages: list[Message]) -> list[Message]:
        rows = []
        for msg in messages:
            row = M4Message(
                id=uuid.UUID(msg.id),
                world_id=uuid.UUID(msg.world_id),
                session_id=uuid.UUID(msg.session_id) if msg.session_id else None,
                type=msg.type,
                sender_type=msg.sender_type,
                sender_id=uuid.UUID(msg.sender_id) if msg.sender_id else None,
                content=msg.content,
                is_key_message=msg.is_key_message,
                user_participated=msg.user_participated,
                sequence=msg.sequence,
                idempotency_key=msg.idempotency_key,
                status=msg.status,
            )
            self.session.add(row)
            rows.append(row)
        await self.session.flush()
        for row in rows:
            await self.session.refresh(row)
        return [self._to_model(row) for row in rows]

    async def list_recent(self, world_id: str, limit: int = 20) -> list[Message]:
        stmt = (
            select(M4Message)
            .where(M4Message.world_id == uuid.UUID(world_id))
            .order_by(desc(M4Message.sequence).nulls_last(), M4Message.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def list_filtered(
        self,
        world_id: str,
        before_sequence: int | None = None,
        limit: int = 50,
        sender_id: str | None = None,
        type: str | None = None,
        session_id: str | None = None,
    ) -> list[Message]:
        stmt = select(M4Message).where(M4Message.world_id == uuid.UUID(world_id))

        if session_id is not None:
            stmt = stmt.where(M4Message.session_id == uuid.UUID(session_id))
        if before_sequence is not None:
            stmt = stmt.where(M4Message.sequence < before_sequence)
        if sender_id is not None:
            stmt = stmt.where(M4Message.sender_id == uuid.UUID(sender_id))
        if type is not None:
            stmt = stmt.where(M4Message.type == type)

        stmt = stmt.order_by(
            desc(M4Message.sequence).nulls_last(), M4Message.created_at.desc()
        ).limit(limit)
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def delete_before_real_time(self, world_id: str, before: datetime) -> int:
        result = await self.session.execute(
            delete(M4Message).where(
                M4Message.world_id == uuid.UUID(world_id),
                M4Message.real_time < before,
            )
        )
        return cast(CursorResult, result).rowcount

    async def get_by_id(self, message_id: str) -> "Message | None":
        row = await self.session.get(M4Message, uuid.UUID(message_id))
        return self._to_model(row) if row else None

    async def delete_by_ids(self, message_ids: list[str]) -> None:
        await self.session.execute(
            delete(M4Message).where(M4Message.id.in_([uuid.UUID(mid) for mid in message_ids]))
        )

    async def list_by_session(self, session_id: str) -> list[Message]:
        stmt = (
            select(M4Message)
            .where(M4Message.session_id == uuid.UUID(session_id))
            .order_by(M4Message.sequence.asc().nulls_last(), M4Message.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def has_messages(self, session_id: str, exclude_types: tuple[str, ...] = ()) -> bool:
        """轻量检查 session 是否有消息（SELECT 1 LIMIT 1）。"""
        stmt = select(1).where(M4Message.session_id == uuid.UUID(session_id))
        if exclude_types:
            stmt = stmt.where(M4Message.type.notin_(exclude_types))
        stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def get_max_sequence(self, session_id: str) -> int:
        """返回该 session 中最大的 sequence 值，无消息时返回 0。"""
        stmt = select(func.coalesce(func.max(M4Message.sequence), 0)).where(
            M4Message.session_id == uuid.UUID(session_id)
        )
        result = await self.session.execute(stmt)
        value = result.scalar()
        return value if value is not None else 0

    async def list_messages_after_sequence(
        self, session_id: str, after_sequence: int
    ) -> list[Message]:
        """返回该 session 中 sequence 大于指定值的消息列表，按 sequence 正序。"""
        stmt = (
            select(M4Message)
            .where(
                M4Message.session_id == uuid.UUID(session_id),
                M4Message.sequence > after_sequence,
            )
            .order_by(M4Message.sequence.asc())
        )
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    def _to_model(self, row: M4Message) -> Message:
        return Message(
            id=str(row.id),
            world_id=str(row.world_id),
            session_id=str(row.session_id) if row.session_id else None,
            type=row.type,
            sender_type=row.sender_type,
            sender_id=str(row.sender_id) if row.sender_id else None,
            sender_name=None,
            content=row.content,
            real_time=row.real_time,
            is_key_message=row.is_key_message,
            user_participated=row.user_participated,
            created_at=row.created_at,
            sequence=row.sequence,
            idempotency_key=row.idempotency_key,
            status=row.status,
        )
