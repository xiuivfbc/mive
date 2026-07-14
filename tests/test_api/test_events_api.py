"""API tests for /api/worlds/{world_id}/events endpoints."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.event import Event


@pytest.fixture
def mock_event_service():
    return AsyncMock()


@pytest.fixture
def mock_event_dialogue_service():
    svc = AsyncMock()

    # stream_dialogue is an async generator — set up a simple SSE stream
    async def _fake_stream(*args, **kwargs):
        yield (
            "event: event_injected\n"
            'data: {"event_id":"abc","title":"暴风雪",'
            '"description":"暴风雪来了",'
            '"participants":["叶文洁"],'
            '"card_message_id":"card1"}\n\n'
        )
        yield (
            "event: speaker_turn\n"
            'data: {"id":"msg1","sender_name":"叶文洁",'
            '"sender_id":"char1","content":"暴风雪来了！"}\n\n'
        )
        yield "event: memory_updating\ndata: {}\n\n"
        yield "event: done\ndata: {}\n\n"

    svc.stream_dialogue = _fake_stream
    return svc


@pytest.fixture
def client(mock_event_service, mock_event_dialogue_service):
    import uuid
    from unittest.mock import AsyncMock

    from src.api.deps import get_current_user
    from src.api.events import router
    from src.db.models import M9User

    app = FastAPI()
    app.include_router(router)
    app.state.event_service = mock_event_service
    app.state.event_dialogue_service = mock_event_dialogue_service

    # Bypass auth for unit tests
    _test_user = MagicMock(spec=M9User)
    _test_user.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    _test_user.avatar_url = None
    app.dependency_overrides[get_current_user] = lambda: _test_user

    return TestClient(app)


def _make_event(**kwargs) -> Event:
    return Event(
        id=kwargs.get("id", str(uuid.uuid4())),
        world_id=kwargs.get("world_id", "w-001"),
        event_type="user_injected",
        name=kwargs.get("name", "瘟疫爆发"),
        description=kwargs.get("description", "一场严重的瘟疫席卷北方大陆"),
        priority=kwargs.get("priority", "medium"),
        status=kwargs.get("status", "scheduled"),
        is_key_event=kwargs.get("is_key_event", False),
        created_at=datetime.now(),
    )


class TestListEvents:
    def test_list_events_success(self, client, mock_event_service):
        events = [_make_event(name="事件A"), _make_event(name="事件B")]
        mock_event_service.list_events.return_value = events

        resp = client.get("/api/worlds/w-001/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_events_with_filters(self, client, mock_event_service):
        mock_event_service.list_events.return_value = []

        resp = client.get(
            "/api/worlds/w-001/events",
            params={
                "from_time": "2024-01-01T00:00:00",
                "to_time": "2024-01-31T00:00:00",
                "status": "scheduled",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestMarkKeyEvent:
    def test_mark_key_event_success(self, client, mock_event_service):
        evt = _make_event(is_key_event=True)
        mock_event_service.mark_key_event.return_value = evt

        resp = client.put(
            "/api/worlds/w-001/events/evt-001/mark",
            json={"is_key_event": True},
        )
        assert resp.status_code == 200
        assert resp.json()["is_key_event"] is True

    def test_mark_nonexistent_event(self, client, mock_event_service):
        mock_event_service.mark_key_event.return_value = None

        resp = client.put(
            "/api/worlds/w-001/events/evt-001/mark",
            json={"is_key_event": True},
        )
        assert resp.status_code == 404


class TestCancelEvent:
    def test_cancel_event_success(self, client, mock_event_service):
        evt = _make_event(status="cancelled")
        mock_event_service.cancel_event.return_value = evt

        resp = client.delete("/api/worlds/w-001/events/evt-001")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_completed_event_returns_400(self, client, mock_event_service):
        mock_event_service.cancel_event.side_effect = ValueError(
            "Cannot cancel event with status: completed"
        )

        resp = client.delete("/api/worlds/w-001/events/evt-001")
        assert resp.status_code == 400


class TestStreamEventDialogue:
    def test_stream_returns_event_stream_content_type(self, client):
        resp = client.post(
            "/api/worlds/w-001/events/stream",
            json={"raw_input": "一场暴风雪突然袭来"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    def test_stream_contains_sse_events(self, client):
        resp = client.post(
            "/api/worlds/w-001/events/stream",
            json={"raw_input": "一场暴风雪突然袭来"},
        )
        body = resp.text
        assert "event: event_injected" in body
        assert "event: speaker_turn" in body
        assert "event: done" in body

    def test_stream_empty_raw_input_rejected(self, client):
        resp = client.post(
            "/api/worlds/w-001/events/stream",
            json={"raw_input": ""},
        )
        assert resp.status_code == 422


class TestDiscardEvent:
    def test_discard_returns_ok(self, client, mock_event_dialogue_service):
        mock_event_dialogue_service.discard_event = AsyncMock()

        resp = client.post(
            "/api/worlds/w-001/events/evt-001/discard",
            json={"message_ids": [str(uuid.uuid4()), str(uuid.uuid4())]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_discard_calls_service_with_correct_args(self, client, mock_event_dialogue_service):
        mock_event_dialogue_service.discard_event = AsyncMock()
        msg_ids = [str(uuid.uuid4())]

        client.post(
            "/api/worlds/w-001/events/evt-001/discard",
            json={"message_ids": msg_ids},
        )
        mock_event_dialogue_service.discard_event.assert_called_once_with("evt-001", msg_ids)

    def test_discard_empty_message_ids_allowed(self, client, mock_event_dialogue_service):
        mock_event_dialogue_service.discard_event = AsyncMock()

        resp = client.post(
            "/api/worlds/w-001/events/evt-001/discard",
            json={"message_ids": []},
        )
        assert resp.status_code == 200
