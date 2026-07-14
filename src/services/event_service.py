from datetime import datetime

from src.db.repositories.event_repo import EventRepository
from src.models.enums import EventStatus
from src.models.event import Event


class EventService:
    def __init__(
        self,
        event_repo: EventRepository,
    ):
        self.event_repo = event_repo

    async def list_events(
        self,
        world_id: str,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        status: str | None = None,
        event_type: str | None = None,
    ) -> list[Event]:
        return await self.event_repo.list_by_world(
            world_id,
            from_time=from_time,
            to_time=to_time,
            status=status,
            event_type=event_type,
        )

    async def mark_key_event(self, event_id: str, is_key_event: bool) -> Event | None:
        return await self.event_repo.mark_key_event(event_id, is_key_event)

    async def cancel_event(self, event_id: str) -> Event:
        event = await self.event_repo.get_by_id(event_id)
        if event is None:
            raise ValueError(f"Event not found: {event_id}")
        if event.status != EventStatus.SCHEDULED:
            raise ValueError(f"Cannot cancel event with status: {event.status}")
        updated = await self.event_repo.update_status(event_id, EventStatus.CANCELLED)
        if updated is None:
            raise ValueError(f"Failed to cancel event: {event_id}")
        return updated
