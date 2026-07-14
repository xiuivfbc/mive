"""API 集成测试：聊天会话端点（list / get messages / delete）。"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.chat_session import ChatSession, ChatSessionListResponse
from src.models.message import Message

WORLD_ID = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())


def _make_session_obj(sid: str = SESSION_ID) -> ChatSession:
    return ChatSession(
        id=sid,
        world_id=WORLD_ID,
        type="character",
        title="测试会话",
        created_at=datetime(2025, 1, 1),
    )


def _make_message(sid: str = SESSION_ID) -> Message:
    return Message(
        id=str(uuid.uuid4()),
        world_id=WORLD_ID,
        type="dialogue",
        sender_type="character",
        sender_id=str(uuid.uuid4()),
        content="你好！",
        virtual_time=datetime(2025, 1, 1),
        session_id=sid,
    )


def _build_client(service: MagicMock | None = None):
    from src.api.chat_sessions import router
    from src.api.deps import get_chat_session_service

    app = FastAPI()
    app.include_router(router)

    svc = service or AsyncMock()
    app.dependency_overrides[get_chat_session_service] = lambda: svc

    client = TestClient(app, raise_server_exceptions=False)
    return client, svc


class TestListChatSessions:
    def test_returns_200_with_sessions(self):
        svc = AsyncMock()
        svc.list_sessions = AsyncMock(
            return_value=ChatSessionListResponse(sessions=[_make_session_obj()])
        )
        client, _ = _build_client(svc)

        resp = client.get(f"/api/worlds/{WORLD_ID}/chat-sessions")

        assert resp.status_code == 200
        body = resp.json()
        assert "sessions" in body
        assert len(body["sessions"]) == 1

    def test_empty_world_returns_empty_list(self):
        svc = AsyncMock()
        svc.list_sessions = AsyncMock(return_value=ChatSessionListResponse(sessions=[]))
        client, _ = _build_client(svc)

        resp = client.get(f"/api/worlds/{WORLD_ID}/chat-sessions")

        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_session_fields_present(self):
        svc = AsyncMock()
        svc.list_sessions = AsyncMock(
            return_value=ChatSessionListResponse(sessions=[_make_session_obj()])
        )
        client, _ = _build_client(svc)

        resp = client.get(f"/api/worlds/{WORLD_ID}/chat-sessions")
        session = resp.json()["sessions"][0]

        assert "id" in session
        assert "world_id" in session
        assert "type" in session
        assert "title" in session
        assert "created_at" in session


class TestGetSessionMessages:
    def test_returns_200_with_messages(self):
        svc = AsyncMock()
        svc.get_session_messages = AsyncMock(return_value=[_make_message()])
        client, _ = _build_client(svc)

        resp = client.get(f"/api/worlds/{WORLD_ID}/chat-sessions/{SESSION_ID}/messages")

        assert resp.status_code == 200
        body = resp.json()
        assert "messages" in body
        assert len(body["messages"]) == 1

    def test_message_content_correct(self):
        svc = AsyncMock()
        svc.get_session_messages = AsyncMock(return_value=[_make_message()])
        client, _ = _build_client(svc)

        resp = client.get(f"/api/worlds/{WORLD_ID}/chat-sessions/{SESSION_ID}/messages")
        msg = resp.json()["messages"][0]

        assert msg["content"] == "你好！"
        assert msg["sender_id"] is not None

    def test_empty_session_returns_empty_list(self):
        svc = AsyncMock()
        svc.get_session_messages = AsyncMock(return_value=[])
        client, _ = _build_client(svc)

        resp = client.get(f"/api/worlds/{WORLD_ID}/chat-sessions/{SESSION_ID}/messages")

        assert resp.status_code == 200
        assert resp.json()["messages"] == []


class TestDeleteChatSession:
    def test_delete_existing_session_returns_ok(self):
        svc = AsyncMock()
        svc.delete_session = AsyncMock(return_value=True)
        client, _ = _build_client(svc)

        resp = client.delete(f"/api/worlds/{WORLD_ID}/chat-sessions/{SESSION_ID}")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_nonexistent_session_returns_404(self):
        svc = AsyncMock()
        svc.delete_session = AsyncMock(return_value=False)
        client, _ = _build_client(svc)

        resp = client.delete(f"/api/worlds/{WORLD_ID}/chat-sessions/{SESSION_ID}")

        assert resp.status_code == 404

    def test_delete_calls_service_with_correct_ids(self):
        svc = AsyncMock()
        svc.delete_session = AsyncMock(return_value=True)
        client, _ = _build_client(svc)

        client.delete(f"/api/worlds/{WORLD_ID}/chat-sessions/{SESSION_ID}")

        svc.delete_session.assert_called_once_with(WORLD_ID, SESSION_ID)
