"""API 集成测试：图谱命令端点 POST /graph-command/parse + /apply。"""

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.models import M9User

WORLD_ID = str(uuid.uuid4())
USER_ID = uuid.uuid4()


def _make_user():
    u = MagicMock(spec=M9User)
    u.id = USER_ID
    u.preferred_language = "zh-CN"
    u.avatar_url = None
    return u


@contextmanager
def _build_client(parse_result=None, apply_result=None, llm_missing=False):
    from src.api.deps import get_current_user
    from src.api.graph_command import router
    from src.db.session import get_session

    app = FastAPI()
    app.include_router(router)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: _make_user()
    app.dependency_overrides[get_session] = lambda: mock_session

    mock_svc = AsyncMock()
    mock_svc.parse = AsyncMock(return_value=parse_result or {"operations": [], "summary": ""})
    mock_svc.apply = AsyncMock(
        return_value=apply_result
        or {
            "added_chars": [],
            "added_rels": [],
            "deleted_rels": [],
            "updated_rels": [],
            "errors": [],
        }
    )

    if not llm_missing:
        app.state.llm = MagicMock()

    app.state.redis = AsyncMock()

    with (
        patch("src.api.graph_command.GraphCommandService", return_value=mock_svc),
        patch("src.api.graph_command.CharacterRepository"),
        patch("src.api.graph_command.RelationRepository"),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        yield client, mock_svc


class TestParseCommand:
    def test_parse_returns_200(self):
        with _build_client(parse_result={"operations": [], "summary": "测试"}) as (client, _):
            resp = client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/parse",
                json={"command": "添加角色Alice"},
            )
            assert resp.status_code == 200

    def test_parse_returns_operations(self):
        ops = [{"op": "add_character", "name": "Alice"}]
        with _build_client(parse_result={"operations": ops, "summary": "添加"}) as (client, _):
            resp = client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/parse",
                json={"command": "添加角色Alice"},
            )
            body = resp.json()
            assert body["operations"] == ops

    def test_parse_calls_service_with_command(self):
        with _build_client() as (client, svc):
            client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/parse",
                json={"command": "删除Bob"},
            )
            svc.parse.assert_called_once_with(WORLD_ID, "删除Bob")

    def test_parse_no_llm_returns_503(self):
        with _build_client(llm_missing=True) as (client, _):
            resp = client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/parse",
                json={"command": "test"},
            )
            assert resp.status_code == 503

    def test_parse_empty_command_returns_200(self):
        with _build_client() as (client, _):
            resp = client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/parse",
                json={"command": ""},
            )
            assert resp.status_code == 200


class TestApplyCommand:
    def test_apply_returns_200(self):
        apply_result = {
            "added_chars": ["Alice"],
            "added_rels": [],
            "deleted_rels": [],
            "updated_rels": [],
            "errors": [],
        }
        with _build_client(apply_result=apply_result) as (client, _):
            resp = client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/apply",
                json={"operations": [{"op": "add_character", "name": "Alice"}]},
            )
            assert resp.status_code == 200

    def test_apply_returns_result_summary(self):
        apply_result = {
            "added_chars": ["Alice", "Bob"],
            "added_rels": ["Alice↔Bob:友人"],
            "deleted_rels": [],
            "updated_rels": [],
            "errors": [],
        }
        with _build_client(apply_result=apply_result) as (client, _):
            resp = client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/apply",
                json={"operations": []},
            )
            body = resp.json()
            assert "Alice" in body["added_chars"]

    def test_apply_calls_service_with_operations(self):
        with _build_client() as (client, svc):
            ops = [{"op": "delete_character", "name": "Alice"}]
            client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/apply",
                json={"operations": ops},
            )
            svc.apply.assert_called_once_with(WORLD_ID, ops)

    def test_apply_no_llm_returns_503(self):
        with _build_client(llm_missing=True) as (client, _):
            resp = client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/apply",
                json={"operations": []},
            )
            assert resp.status_code == 503

    def test_apply_empty_operations_returns_200(self):
        with _build_client() as (client, _):
            resp = client.post(
                f"/api/worlds/{WORLD_ID}/graph-command/apply",
                json={"operations": []},
            )
            assert resp.status_code == 200
