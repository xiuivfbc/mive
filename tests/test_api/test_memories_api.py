"""API 集成测试：角色记忆端点（GET / DELETE / POST flush）。"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.models import M1World, M9User

WORLD_ID = str(uuid.uuid4())
CHAR_ID = str(uuid.uuid4())
MEM_ID = str(uuid.uuid4())
USER_ID = uuid.uuid4()


def _make_user(uid: uuid.UUID = USER_ID):
    u = MagicMock(spec=M9User)
    u.id = uid
    u.email = "test@example.com"
    u.is_admin = False
    u.avatar_url = None
    return u


def _make_world_row(user_id: uuid.UUID = USER_ID):
    w = MagicMock(spec=M1World)
    w.id = uuid.UUID(WORLD_ID)
    w.user_id = user_id
    return w


def _make_memory(mid: str = MEM_ID, char_id: str = CHAR_ID, content: str = "记忆内容"):
    m = MagicMock()
    m.id = uuid.UUID(mid)
    m.character_id = uuid.UUID(char_id)
    m.content = content
    m.session_id = None
    m.created_at = datetime(2025, 1, 1, 0, 0, 0)
    return m


def _build_client(
    world_row=None,
    short_term_mems=None,
    long_term_mems=None,
    memory_obj=None,
    current_user=None,
):
    from src.api.deps import get_current_user, get_session
    from src.api.memories import router

    app = FastAPI()
    app.include_router(router)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_world_repo = AsyncMock()
    mock_world_repo.get_by_id = AsyncMock(return_value=world_row)

    mock_mem_repo = AsyncMock()
    mock_mem_repo.list_short_term = AsyncMock(return_value=short_term_mems or [])
    mock_mem_repo.list_long_term = AsyncMock(return_value=long_term_mems or [])
    mock_mem_repo.get_by_id = AsyncMock(return_value=memory_obj)
    mock_mem_repo.delete_by_ids = AsyncMock()
    mock_mem_repo.delete_by_session = AsyncMock()

    user = current_user or _make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: mock_session

    with (
        patch("src.api.memories.WorldRepository", return_value=mock_world_repo),
        patch("src.api.memories.CharacterMemoryRepository", return_value=mock_mem_repo),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        yield client, mock_mem_repo


@pytest.fixture
def happy_client():
    mem = _make_memory()
    gen = _build_client(
        world_row=_make_world_row(),
        short_term_mems=[mem],
        memory_obj=mem,
    )
    yield from gen


class TestGetCharacterMemories:
    def test_returns_200_with_memories(self, happy_client):
        client, _ = happy_client
        resp = client.get(f"/api/worlds/{WORLD_ID}/characters/{CHAR_ID}/memories")
        assert resp.status_code == 200
        body = resp.json()
        assert "short_term" in body
        assert "long_term" in body

    def test_short_term_contains_memory(self, happy_client):
        client, _ = happy_client
        resp = client.get(f"/api/worlds/{WORLD_ID}/characters/{CHAR_ID}/memories")
        body = resp.json()
        assert len(body["short_term"]) == 1
        assert body["short_term"][0]["content"] == "记忆内容"

    def test_world_not_found_returns_404(self):
        gen = _build_client(world_row=None)
        client, _ = next(gen)
        resp = client.get(f"/api/worlds/{WORLD_ID}/characters/{CHAR_ID}/memories")
        assert resp.status_code == 404

    def test_other_user_world_returns_404(self):
        other_world = _make_world_row(user_id=uuid.uuid4())
        gen = _build_client(world_row=other_world)
        client, _ = next(gen)
        resp = client.get(f"/api/worlds/{WORLD_ID}/characters/{CHAR_ID}/memories")
        assert resp.status_code == 404


class TestDeleteCharacterMemory:
    def test_delete_own_memory_returns_ok(self, happy_client):
        client, _ = happy_client
        resp = client.delete(f"/api/worlds/{WORLD_ID}/characters/{CHAR_ID}/memories/{MEM_ID}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_nonexistent_memory_returns_404(self):
        gen = _build_client(
            world_row=_make_world_row(),
            memory_obj=None,
        )
        client, _ = next(gen)
        resp = client.delete(f"/api/worlds/{WORLD_ID}/characters/{CHAR_ID}/memories/{MEM_ID}")
        assert resp.status_code == 404


class TestDeleteSessionMemories:
    def test_delete_session_memories_returns_ok(self, happy_client):
        client, mock_mem_repo = happy_client
        session_id = str(uuid.uuid4())
        resp = client.delete(f"/api/worlds/{WORLD_ID}/sessions/{session_id}/memories")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestFlushSessionMemories:
    def _build_flush_client(self, world_row=None, flush_result=None, current_user=None):
        from src.api.deps import get_current_user, get_message_service, get_session
        from src.api.memories import router

        app = FastAPI()
        app.include_router(router)

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_world_repo = AsyncMock()
        mock_world_repo.get_by_id = AsyncMock(return_value=world_row)

        mock_message_service = AsyncMock()
        mock_message_service.flush_chat_memories = AsyncMock(
            return_value=flush_result or {"flushed": True, "characters_updated": ["叶文洁"]}
        )

        user = current_user or _make_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_session] = lambda: mock_session
        app.dependency_overrides[get_message_service] = lambda: mock_message_service

        with patch("src.api.memories.WorldRepository", return_value=mock_world_repo):
            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_message_service

    def test_flush_returns_200_on_success(self):
        session_id = str(uuid.uuid4())
        gen = self._build_flush_client(world_row=_make_world_row())
        client, _ = next(gen)
        resp = client.post(f"/api/worlds/{WORLD_ID}/sessions/{session_id}/flush-memories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["flushed"] is True
        assert "叶文洁" in body["characters_updated"]

    def test_flush_returns_no_new_messages(self):
        session_id = str(uuid.uuid4())
        gen = self._build_flush_client(
            world_row=_make_world_row(),
            flush_result={"flushed": False, "reason": "no_new_messages"},
        )
        client, _ = next(gen)
        resp = client.post(f"/api/worlds/{WORLD_ID}/sessions/{session_id}/flush-memories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["flushed"] is False
        assert body["reason"] == "no_new_messages"

    def test_flush_returns_below_threshold(self):
        session_id = str(uuid.uuid4())
        gen = self._build_flush_client(
            world_row=_make_world_row(),
            flush_result={"flushed": False, "reason": "below_threshold", "pending_count": 3},
        )
        client, _ = next(gen)
        resp = client.post(f"/api/worlds/{WORLD_ID}/sessions/{session_id}/flush-memories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["flushed"] is False
        assert body["pending_count"] == 3

    def test_flush_world_not_found_returns_404(self):
        session_id = str(uuid.uuid4())
        gen = self._build_flush_client(world_row=None)
        client, _ = next(gen)
        resp = client.post(f"/api/worlds/{WORLD_ID}/sessions/{session_id}/flush-memories")
        assert resp.status_code == 404

    def test_flush_other_user_world_returns_404(self):
        session_id = str(uuid.uuid4())
        other_world = _make_world_row(user_id=uuid.uuid4())
        gen = self._build_flush_client(world_row=other_world)
        client, _ = next(gen)
        resp = client.post(f"/api/worlds/{WORLD_ID}/sessions/{session_id}/flush-memories")
        assert resp.status_code == 404
