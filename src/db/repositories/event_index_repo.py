"""Repository for M26EventIndex — world-level event index (V2)."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M26EventIndex


class EventIndexRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        world_id: uuid.UUID,
        event_name: str,
        brief: str,
        dissemination: float = 0.5,
        core_participants: list[uuid.UUID] | None = None,
        effective_day: int | None = None,
        id: uuid.UUID | None = None,
    ) -> M26EventIndex:
        """Create a new event index entry.

        When *id* is provided it is used as the primary key (so the entry
        can be looked up later via ``get_by_id(event_id)``).
        """
        kwargs: dict = {
            "world_id": world_id,
            "event_name": event_name,
            "brief": brief,
            "dissemination": dissemination,
            "core_participants": core_participants,
            "effective_day": effective_day,
        }
        if id is not None:
            kwargs["id"] = id
        obj = M26EventIndex(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_by_world(self, world_id: uuid.UUID | str) -> list[M26EventIndex]:
        """Return all event index entries for a world."""
        wid = uuid.UUID(world_id) if isinstance(world_id, str) else world_id
        result = await self.session.execute(
            select(M26EventIndex)
            .where(M26EventIndex.world_id == wid)
            .order_by(M26EventIndex.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, event_id: uuid.UUID | str) -> M26EventIndex | None:
        """Look up an event index entry by ID."""
        eid = uuid.UUID(event_id) if isinstance(event_id, str) else event_id
        result = await self.session.execute(select(M26EventIndex).where(M26EventIndex.id == eid))
        return result.scalar_one_or_none()

    async def update_name(self, event_id: uuid.UUID | str, new_name: str) -> None:
        """Update the event name of an existing entry."""
        eid = uuid.UUID(event_id) if isinstance(event_id, str) else event_id
        await self.session.execute(
            update(M26EventIndex).where(M26EventIndex.id == eid).values(event_name=new_name)
        )

    async def get_effective_events(
        self, world_id: uuid.UUID | str, current_day: int
    ) -> list[M26EventIndex]:
        """Return events that have become effective (effective_day <= current_day)."""
        wid = uuid.UUID(world_id) if isinstance(world_id, str) else world_id
        result = await self.session.execute(
            select(M26EventIndex)
            .where(
                M26EventIndex.world_id == wid,
                M26EventIndex.effective_day.isnot(None),
                M26EventIndex.effective_day <= current_day,
            )
            .order_by(M26EventIndex.effective_day.asc())
        )
        return list(result.scalars().all())
