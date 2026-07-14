"""API tests for /api/worlds/{world_id}/matterbridge endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.matterbridge import router, push_to_stream_queues, _stream_queues
from src.services.matterbridge_service import MatterbridgeMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_WORLD_ID = "00000000-0000-0000-0000-000000000099"
_INVALID_WORLD_ID = "not-a-uuid"


def _make_binding_dict(
    world_id: str = _TEST_WORLD_ID,
    api_url: str = "http://mb.local:4242",
    api_token_preview: str = "abcd****efgh",
    enabled: bool = True,
    config_json: dict | None = None,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "world_id": world_id,
        "api_url": api_url,
        "api_token_preview": api_token_preview,
        "enabled": enabled,
        "config_json": config_json,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_stream_queues():
    """Ensure _stream_queues is clean before and after each test."""
    _stream_queues.clear()
    yield
    _stream_queues.clear()


@pytest.fixture
def mock_mb_service():
    return AsyncMock()


@pytest.fixture
def client(mock_mb_service):
    from unittest.mock import AsyncMock, MagicMock

    from src.api.deps import get_current_user, get_matterbridge_service
    from src.db.models import M9User

    app = FastAPI()
    app.include_router(router)

    # Override auth
    _test_user = MagicMock(spec=M9User)
    _test_user.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    app.dependency_overrides[get_current_user] = lambda: _test_user

    # Override matterbridge service
    app.dependency_overrides[get_matterbridge_service] = lambda: mock_mb_service

    return TestClient(app)


# ---------------------------------------------------------------------------
# GET / — get_binding
# ---------------------------------------------------------------------------


class TestGetBinding:
    def test_get_binding_success(self, client, mock_mb_service):
        mock_mb_service.get_binding.return_value = _make_binding_dict()

        resp = client.get(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["world_id"] == _TEST_WORLD_ID
        assert data["api_url"] == "http://mb.local:4242"
        assert "api_token_preview" in data
        assert data["enabled"] is True

    def test_get_binding_not_found(self, client, mock_mb_service):
        mock_mb_service.get_binding.return_value = None

        resp = client.get(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge")
        assert resp.status_code == 404

    def test_get_binding_invalid_world_id(self, client, mock_mb_service):
        resp = client.get(f"/api/worlds/{_INVALID_WORLD_ID}/matterbridge")
        assert resp.status_code == 400
        assert "Invalid world ID" in resp.json()["detail"]

    def test_get_binding_unauthenticated(self, mock_mb_service):
        """Without the auth override, should get 401/403."""
        from fastapi.testclient import TestClient as TC

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides = {}  # no auth override

        from src.api.deps import get_matterbridge_service

        app.dependency_overrides[get_matterbridge_service] = lambda: mock_mb_service

        with TC(app) as unauth_client:
            resp = unauth_client.get(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge")
        # Without bearer token, FastAPI returns 401 or 403
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST / — create_or_update_binding
# ---------------------------------------------------------------------------


class TestCreateBinding:
    def test_create_binding_success(self, client, mock_mb_service):
        mock_mb_service.create_or_update_binding.return_value = _make_binding_dict()

        resp = client.post(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge",
            json={
                "api_url": "http://mb.local:4242",
                "api_token": "secret-token-123",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["world_id"] == _TEST_WORLD_ID

    def test_create_binding_with_config(self, client, mock_mb_service):
        mock_mb_service.create_or_update_binding.return_value = _make_binding_dict(
            config_json={"gateways": ["gw1"]}
        )

        resp = client.post(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge",
            json={
                "api_url": "http://mb.local:4242",
                "api_token": "tok",
                "config_json": {"gateways": ["gw1"]},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["config_json"] == {"gateways": ["gw1"]}

    def test_create_binding_invalid_world_id(self, client, mock_mb_service):
        resp = client.post(
            f"/api/worlds/{_INVALID_WORLD_ID}/matterbridge",
            json={"api_url": "http://mb.local", "api_token": "tok"},
        )
        assert resp.status_code == 400

    def test_create_binding_missing_fields(self, client, mock_mb_service):
        resp = client.post(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge",
            json={"api_url": "http://mb.local"},  # missing api_token
        )
        assert resp.status_code == 422  # validation error


# ---------------------------------------------------------------------------
# PATCH / — update_binding
# ---------------------------------------------------------------------------


class TestUpdateBinding:
    def test_update_binding_success(self, client, mock_mb_service):
        mock_mb_service.update_binding_field.return_value = _make_binding_dict(enabled=False)

        resp = client.patch(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_update_binding_not_found(self, client, mock_mb_service):
        mock_mb_service.update_binding_field.return_value = None

        resp = client.patch(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge",
            json={"enabled": False},
        )
        assert resp.status_code == 404

    def test_update_binding_empty_body(self, client, mock_mb_service):
        resp = client.patch(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge",
            json={},
        )
        assert resp.status_code == 400
        assert "No fields" in resp.json()["detail"]

    def test_update_binding_token(self, client, mock_mb_service):
        mock_mb_service.update_binding_field.return_value = _make_binding_dict()

        resp = client.patch(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge",
            json={"api_token": "new-secret"},
        )
        assert resp.status_code == 200
        # Verify the service was called with the plaintext token
        mock_mb_service.update_binding_field.assert_awaited_once_with(
            _TEST_WORLD_ID, api_token="new-secret",
        )


# ---------------------------------------------------------------------------
# DELETE / — delete_binding
# ---------------------------------------------------------------------------


class TestDeleteBinding:
    def test_delete_binding_success(self, client, mock_mb_service):
        mock_mb_service.delete_binding.return_value = True

        resp = client.delete(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge")
        assert resp.status_code == 204

    def test_delete_binding_not_found(self, client, mock_mb_service):
        mock_mb_service.delete_binding.return_value = False

        resp = client.delete(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge")
        assert resp.status_code == 404

    def test_delete_binding_invalid_world_id(self, client, mock_mb_service):
        resp = client.delete(f"/api/worlds/{_INVALID_WORLD_ID}/matterbridge")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /message — send_message
# ---------------------------------------------------------------------------


class TestSendMessageAPI:
    def test_send_message_success(self, client, mock_mb_service):
        mock_mb_service.send_message.return_value = True

        resp = client.post(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/message",
            json={
                "text": "hello world",
                "username": "bot",
                "gateway": "gw1",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_send_message_failure(self, client, mock_mb_service):
        mock_mb_service.send_message.return_value = False

        resp = client.post(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/message",
            json={
                "text": "hello",
                "username": "bot",
                "gateway": "gw1",
            },
        )
        assert resp.status_code == 502
        assert "Matterbridge" in resp.json()["detail"]

    def test_send_message_with_optional_fields(self, client, mock_mb_service):
        mock_mb_service.send_message.return_value = True

        resp = client.post(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/message",
            json={
                "text": "reply",
                "username": "bot",
                "gateway": "gw1",
                "avatar": "http://avatar.png",
                "parent_id": "parent-msg-1",
            },
        )
        assert resp.status_code == 200
        mock_mb_service.send_message.assert_awaited_once_with(
            world_id=_TEST_WORLD_ID,
            text="reply",
            username="bot",
            gateway="gw1",
            avatar="http://avatar.png",
            parent_id="parent-msg-1",
        )

    def test_send_message_missing_required_fields(self, client, mock_mb_service):
        resp = client.post(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/message",
            json={"text": "hi"},  # missing username and gateway
        )
        assert resp.status_code == 422

    def test_send_message_invalid_world_id(self, client, mock_mb_service):
        resp = client.post(
            f"/api/worlds/{_INVALID_WORLD_ID}/matterbridge/message",
            json={"text": "hi", "username": "u", "gateway": "gw"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /messages — get_messages
# ---------------------------------------------------------------------------


class TestGetMessagesAPI:
    def test_get_messages_success(self, client, mock_mb_service):
        msg1 = MatterbridgeMessage(
            text="msg1", username="u1", gateway="gw", protocol="discord",
            msg_id="m1", timestamp="2026-01-01T00:00:00Z",
        )
        msg2 = MatterbridgeMessage(
            text="msg2", username="u2", gateway="gw", protocol="telegram",
            msg_id="m2", timestamp="2026-01-01T00:01:00Z",
        )
        mock_mb_service.get_history.return_value = [msg1, msg2]

        resp = client.get(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/messages",
            params={"gateway": "gw"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["text"] == "msg1"
        assert data[0]["username"] == "u1"
        assert data[1]["text"] == "msg2"

    def test_get_messages_empty(self, client, mock_mb_service):
        mock_mb_service.get_history.return_value = []

        resp = client.get(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/messages",
            params={"gateway": "gw"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_messages_missing_gateway_param(self, client, mock_mb_service):
        resp = client.get(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/messages")
        assert resp.status_code == 422  # gateway is required

    def test_get_messages_with_limit(self, client, mock_mb_service):
        mock_mb_service.get_history.return_value = []

        resp = client.get(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/messages",
            params={"gateway": "gw", "limit": 10},
        )
        assert resp.status_code == 200
        mock_mb_service.get_history.assert_awaited_once_with(
            _TEST_WORLD_ID, gateway="gw", limit=10,
        )

    def test_get_messages_invalid_world_id(self, client, mock_mb_service):
        resp = client.get(
            f"/api/worlds/{_INVALID_WORLD_ID}/matterbridge/messages",
            params={"gateway": "gw"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /status — get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_get_status_with_binding(self, client, mock_mb_service):
        mock_mb_service.get_binding.return_value = _make_binding_dict()
        # is_stream_running is synchronous in the real service;
        # AsyncMock auto-wraps it as async, so use MagicMock explicitly
        mock_mb_service.is_stream_running = MagicMock(return_value=True)
        mock_mb_service.health_check.return_value = {"status": "ok"}

        resp = client.get(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["world_id"] == _TEST_WORLD_ID
        assert data["binding_configured"] is True
        assert data["stream_running"] is True
        assert data["matterbridge_health"]["status"] == "ok"
        assert data["connected_sse_clients"] == 0

    def test_get_status_no_binding(self, client, mock_mb_service):
        mock_mb_service.get_binding.return_value = None
        mock_mb_service.is_stream_running = MagicMock(return_value=False)

        resp = client.get(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["binding_configured"] is False
        assert data["stream_running"] is False
        assert data["matterbridge_health"]["status"] == "error"

    def test_get_status_invalid_world_id(self, client, mock_mb_service):
        resp = client.get(f"/api/worlds/{_INVALID_WORLD_ID}/matterbridge/status")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# push_to_stream_queues helper
# ---------------------------------------------------------------------------


class TestStreamQueueHelper:
    def test_push_to_empty_queues(self):
        # Should not raise when no queues exist
        push_to_stream_queues("nonexistent", {"text": "hi"})

    def test_push_to_registered_queue(self):
        import asyncio

        q = asyncio.Queue(maxsize=256)
        _stream_queues["world1"] = {q}

        push_to_stream_queues("world1", {"text": "hello"})
        assert not q.empty()
        data = q.get_nowait()
        assert data == {"text": "hello"}

    def test_push_drops_on_full_queue(self):
        import asyncio

        q = asyncio.Queue(maxsize=1)
        q.put_nowait("fill")  # fill the queue
        _stream_queues["world2"] = {q}

        # Should not raise even though queue is full
        push_to_stream_queues("world2", {"text": "dropped"})
        assert q.qsize() == 1  # still only the original item


# ---------------------------------------------------------------------------
# Response format validation
# ---------------------------------------------------------------------------


class TestResponseFormat:
    def test_binding_response_has_all_fields(self, client, mock_mb_service):
        mock_mb_service.get_binding.return_value = _make_binding_dict()

        resp = client.get(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge")
        assert resp.status_code == 200
        data = resp.json()

        required_fields = [
            "id", "world_id", "api_url", "api_token_preview",
            "enabled", "created_at", "updated_at",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_send_message_response_format(self, client, mock_mb_service):
        mock_mb_service.send_message.return_value = True

        resp = client.post(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/message",
            json={"text": "hi", "username": "u", "gateway": "gw"},
        )
        assert resp.status_code == 200
        assert "ok" in resp.json()

    def test_status_response_format(self, client, mock_mb_service):
        mock_mb_service.get_binding.return_value = _make_binding_dict()
        mock_mb_service.is_stream_running = MagicMock(return_value=False)
        mock_mb_service.health_check.return_value = {"status": "ok"}

        resp = client.get(f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/status")
        assert resp.status_code == 200
        data = resp.json()

        required_fields = [
            "world_id", "binding_configured", "enabled",
            "stream_running", "matterbridge_health", "connected_sse_clients",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_messages_response_format(self, client, mock_mb_service):
        mock_mb_service.get_history.return_value = [
            MatterbridgeMessage(text="t", username="u", gateway="gw", msg_id="m1"),
        ]

        resp = client.get(
            f"/api/worlds/{_TEST_WORLD_ID}/matterbridge/messages",
            params={"gateway": "gw"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

        msg = data[0]
        expected_fields = [
            "text", "username", "gateway", "avatar", "protocol",
            "id", "timestamp", "event", "parent_id",
        ]
        for field in expected_fields:
            assert field in msg, f"Missing field: {field}"
