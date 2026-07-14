"""API tests for /api/worlds/{world_id}/messages endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.message import Message, MessageListResponse, SendMessageResponse


@pytest.fixture
def mock_message_service():
    return AsyncMock()


@pytest.fixture
def client(mock_message_service):
    import uuid
    from unittest.mock import MagicMock

    from src.api.deps import get_current_user
    from src.api.messages import router
    from src.db.models import M9User

    app = FastAPI()
    app.include_router(router)
    app.state.message_service = mock_message_service

    # Bypass auth for unit tests
    _test_user = MagicMock(spec=M9User)
    _test_user.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    _test_user.avatar_url = None
    app.dependency_overrides[get_current_user] = lambda: _test_user

    return TestClient(app)


_TEST_WORLD_ID = "00000000-0000-0000-0000-000000000099"


def _make_message(**kwargs) -> Message:
    return Message(
        id=str(kwargs.get("id", uuid.uuid4())),
        world_id=kwargs.get("world_id", _TEST_WORLD_ID),
        type=kwargs.get("type", "dialogue"),
        sender_type=kwargs.get("sender_type", "character"),
        sender_id=str(kwargs.get("sender_id", uuid.uuid4())),
        content=kwargs.get("content", "测试消息"),
        virtual_time=kwargs.get("virtual_time", datetime(1971, 9, 7, 9, 30, 0, tzinfo=UTC)),
    )


class TestGetMessages:
    def test_get_messages_success(self, client, mock_message_service):
        mock_message_service.list_messages.return_value = MessageListResponse(
            messages=[_make_message(), _make_message(content="消息2")],
            has_more=False,
        )

        resp = client.get("/api/worlds/00000000-0000-0000-0000-000000000099/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["has_more"] is False

    def test_get_messages_with_cursor(self, client, mock_message_service):
        mock_message_service.list_messages.return_value = MessageListResponse(
            messages=[_make_message()],
            has_more=False,
        )

        resp = client.get(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            params={"before_sequence": 10, "limit": 10},
        )
        assert resp.status_code == 200
        mock_message_service.list_messages.assert_called_once()
        call_kwargs = mock_message_service.list_messages.call_args[1]
        assert call_kwargs["limit"] == 10

    def test_get_messages_with_sender_filter(self, client, mock_message_service):
        mock_message_service.list_messages.return_value = MessageListResponse(
            messages=[_make_message()],
            has_more=False,
        )

        resp = client.get(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            params={"sender_id": "char-001"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_message_service.list_messages.call_args[1]
        assert call_kwargs["sender_id"] == "char-001"

    def test_get_messages_with_type_filter(self, client, mock_message_service):
        mock_message_service.list_messages.return_value = MessageListResponse(
            messages=[_make_message(type="narration")],
            has_more=False,
        )

        resp = client.get(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            params={"type": "narration"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_message_service.list_messages.call_args[1]
        assert call_kwargs["type"] == "narration"

    def test_get_messages_default_limit(self, client, mock_message_service):
        mock_message_service.list_messages.return_value = MessageListResponse(
            messages=[],
            has_more=False,
        )

        resp = client.get("/api/worlds/00000000-0000-0000-0000-000000000099/messages")
        assert resp.status_code == 200
        call_kwargs = mock_message_service.list_messages.call_args[1]
        assert call_kwargs["limit"] == 50


class TestPostMessage:
    def test_post_message_success(self, client, mock_message_service):
        user_msg = _make_message(type="user", sender_type="user", content="你好")
        response_msg = _make_message(content="你好，有什么事？")
        mock_message_service.send_message.return_value = SendMessageResponse(
            user_message=user_msg,
            responses=[response_msg],
        )

        resp = client.post(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            json={"content": "你好"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_message"]["content"] == "你好"
        assert data["user_message"]["type"] == "user"
        assert len(data["responses"]) == 1
        assert data.get("error") is None

    def test_post_message_partial_failure(self, client, mock_message_service):
        user_msg = _make_message(type="user", sender_type="user", content="你好")
        mock_message_service.send_message.return_value = SendMessageResponse(
            user_message=user_msg,
            responses=[],
            error="dialogue_generation_failed",
        )

        resp = client.post(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            json={"content": "你好"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_message"]["content"] == "你好"
        assert data["responses"] == []
        assert data["error"] == "dialogue_generation_failed"

    def test_post_message_empty_content_rejected(self, client, mock_message_service):
        resp = client.post(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            json={"content": ""},
        )
        assert resp.status_code == 422

    def test_post_message_calls_service(self, client, mock_message_service):
        user_msg = _make_message(type="user", sender_type="user")
        mock_message_service.send_message.return_value = SendMessageResponse(
            user_message=user_msg, responses=[]
        )

        client.post(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            json={"content": "测试内容"},
        )
        mock_message_service.send_message.assert_called_once_with(
            _TEST_WORLD_ID,
            "测试内容",
            "auto",
            None,
            None,
            memories_enabled=False,
            action_descriptions=False,
            element_rerank=False,
            idempotency_key=None,
            show_narration=False,
        )

    def test_post_message_with_old_target_fields_rejected(self, client, mock_message_service):
        resp = client.post(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            json={"content": "test", "target_character_ids": ["char-001"]},
        )
        assert resp.status_code == 422

    def test_post_message_with_participant_mode_accepted(self, client, mock_message_service):
        user_msg = _make_message(type="user", sender_type="user")
        mock_message_service.send_message.return_value = SendMessageResponse(
            user_message=user_msg, responses=[]
        )
        resp = client.post(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages",
            json={
                "content": "test",
                "participant_mode": "edit",
                "participants": [{"id": "c-1", "name": "叶文洁"}],
            },
        )
        assert resp.status_code == 200

    def test_post_message_response_includes_participants(self, client, mock_message_service):
        user_msg = _make_message(type="user", sender_type="user")
        mock_message_service.send_message.return_value = SendMessageResponse(
            user_message=user_msg,
            responses=[],
            participants=[{"id": "c-1", "name": "叶文洁"}],
            participant_mode="auto",
        )
        resp = client.post(
            "/api/worlds/00000000-0000-0000-0000-000000000099/messages", json={"content": "test"}
        )
        data = resp.json()
        assert data["participants"] == [{"id": "c-1", "name": "叶文洁"}]
        assert data["participant_mode"] == "auto"
