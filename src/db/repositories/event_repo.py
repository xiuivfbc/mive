import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M3Event
from src.models.enums import EventStatus, EventType
from src.models.event import Event


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, world_id: str, data: dict) -> Event:
        row = M3Event(
            world_id=uuid.UUID(world_id),
            event_type=data.get("event_type", EventType.USER_INJECTED),
            name=data.get("name"),
            description=data.get("description"),
            priority=data.get("priority", "medium"),
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def get_by_id(self, event_id: str) -> Event | None:
        row = await self.session.get(M3Event, uuid.UUID(event_id))
        if row is None:
            return None
        return self._to_model(row)

    async def list_by_world(
        self,
        world_id: str,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        status: str | None = None,
        event_type: str | None = None,
    ) -> list[Event]:
        stmt = select(M3Event).where(M3Event.world_id == uuid.UUID(world_id))
        if from_time is not None:
            stmt = stmt.where(M3Event.created_at >= from_time)
        if to_time is not None:
            stmt = stmt.where(M3Event.created_at <= to_time)
        if status is not None:
            stmt = stmt.where(M3Event.status == status)
        if event_type is not None:
            stmt = stmt.where(M3Event.event_type == event_type)
        stmt = stmt.order_by(M3Event.created_at)
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def update_status(
        self, event_id: str, status: str, executed_at: datetime | None = None
    ) -> Event | None:
        row = await self.session.get(M3Event, uuid.UUID(event_id))
        if row is None:
            return None
        row.status = status
        if status == EventStatus.COMPLETED:
            row.executed_at = executed_at or datetime.now(UTC).replace(tzinfo=None)
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def mark_key_event(self, event_id: str, is_key_event: bool) -> Event | None:
        row = await self.session.get(M3Event, uuid.UUID(event_id))
        if row is None:
            return None
        row.is_key_event = is_key_event
        row.user_marked = True
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def find_due_events(
        self, world_id: str, from_time: datetime, to_time: datetime
    ) -> list[Event]:
        """查找时间窗口内到期的 scheduled 事件"""
        stmt = (
            select(M3Event)
            .where(M3Event.world_id == uuid.UUID(world_id))
            .where(M3Event.status == EventStatus.SCHEDULED)
            .where(M3Event.created_at >= from_time)
            .where(M3Event.created_at <= to_time)
            .order_by(M3Event.created_at)
        )
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def count_by_world(self, world_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).where(M3Event.world_id == uuid.UUID(world_id))
        )
        return result.scalar_one()

    async def get_nth_event_time(self, world_id: str, n: int) -> datetime | None:
        result = await self.session.execute(
            select(M3Event.created_at)
            .where(M3Event.world_id == uuid.UUID(world_id))
            .order_by(M3Event.created_at.desc())
            .offset(n - 1)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def cancel_after(self, world_id: str, after: datetime) -> None:
        await self.session.execute(
            sa_update(M3Event)
            .where(
                M3Event.world_id == uuid.UUID(world_id),
                M3Event.created_at > after,
            )
            .values(status=EventStatus.CANCELLED)
        )

    def _to_model(self, row: M3Event) -> Event:
        return Event(
            id=str(row.id),
            world_id=str(row.world_id),
            event_type=row.event_type or EventType.USER_INJECTED,
            name=row.name,
            description=row.description,
            priority=row.priority or "medium",
            status=row.status or EventStatus.SCHEDULED,
            is_key_event=row.is_key_event or False,
            user_marked=row.user_marked or False,
            created_at=row.created_at,
            executed_at=row.executed_at,
        )
