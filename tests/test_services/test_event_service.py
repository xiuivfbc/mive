import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.db.repositories.event_repo import EventRepository
from src.models.event import Event
from src.services.event_service import EventService


@pytest.fixture
def mock_event_repo():
    return AsyncMock(spec=EventRepository)


@pytest.fixture
def event_service(mock_event_repo):
    return EventService(
        event_repo=mock_event_repo,
    )


WORLD_ID = str(uuid.uuid4())
CHAR_ID = str(uuid.uuid4())


def _make_event(**kwargs):
    return Event(
        id=kwargs.get("id", str(uuid.uuid4())),
        world_id=WORLD_ID,
        event_type="user_injected",
        name=kwargs.get("name", "瘟疫爆发"),
        description=kwargs.get("description", "一场严重的瘟疫席卷北方大陆"),
        priority=kwargs.get("priority", "medium"),
        status=kwargs.get("status", "scheduled"),
        is_key_event=kwargs.get("is_key_event", False),
        created_at=datetime.now(),
    )


class TestEventServiceListEvents:
    async def test_list_events(self, event_service, mock_event_repo):
        events = [_make_event(name="事件A"), _make_event(name="事件B")]
        mock_event_repo.list_by_world.return_value = events

        result = await event_service.list_events(WORLD_ID)
        assert len(result) == 2
        mock_event_repo.list_by_world.assert_called_once_with(
            WORLD_ID, from_time=None, to_time=None, status=None, event_type=None
        )

    async def test_list_events_with_filters(self, event_service, mock_event_repo):
        mock_event_repo.list_by_world.return_value = []

        await event_service.list_events(
            WORLD_ID,
            from_time=datetime(2024, 1, 1, 0, 0, 0),
            to_time=datetime(2024, 1, 31, 0, 0, 0),
            status="scheduled",
        )

        mock_event_repo.list_by_world.assert_called_once_with(
            WORLD_ID,
            from_time=datetime(2024, 1, 1, 0, 0, 0),
            to_time=datetime(2024, 1, 31, 0, 0, 0),
            status="scheduled",
            event_type=None,
        )


class TestEventServiceMarkKeyEvent:
    async def test_mark_key_event(self, event_service, mock_event_repo):
        evt = _make_event(is_key_event=True)
        mock_event_repo.mark_key_event.return_value = evt

        result = await event_service.mark_key_event("evt_001", True)
        assert result.is_key_event is True
        mock_event_repo.mark_key_event.assert_called_once_with("evt_001", True)


class TestEventServiceCancelEvent:
    async def test_cancel_scheduled_event(self, event_service, mock_event_repo):
        evt = _make_event(status="cancelled")
        mock_event_repo.get_by_id.return_value = _make_event(status="scheduled")
        mock_event_repo.update_status.return_value = evt

        result = await event_service.cancel_event("evt_001")
        assert result.status == "cancelled"
        mock_event_repo.update_status.assert_called_once_with("evt_001", "cancelled")

    async def test_cancel_nonexistent_raises(self, event_service, mock_event_repo):
        mock_event_repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await event_service.cancel_event("nonexistent")

    async def test_cancel_completed_event_raises(self, event_service, mock_event_repo):
        mock_event_repo.get_by_id.return_value = _make_event(status="completed")

        with pytest.raises(ValueError, match="Cannot cancel"):
            await event_service.cancel_event("evt_001")
