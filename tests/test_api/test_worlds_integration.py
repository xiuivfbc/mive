"""World + Characters + Graph API integration tests — real DB + real services + mocked LLM."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.llm.base import LLMResponse
from src.services.extraction_service import ExtractionService

pytestmark = pytest.mark.usefixtures("api_client")

MAX_POLL_ATTEMPTS = 20
POLL_INTERVAL = 0.5


@pytest.fixture(autouse=True)
def _ensure_mock_state():
    """Re-establish correct mock LLM state before each test.

    Module-scoped fixtures in other test files replace app.state.llm with bare
    AsyncMock instances.  Even though those fixtures restore on teardown, the
    session-scoped api_client mock can drift.  This fixture guarantees a working
    mock is in place for every test in this module.
    """
    from src.main import app

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = LLMResponse(
        content="模拟世界观概述文本", model="test", input_tokens=0, output_tokens=0
    )
    mock_llm.complete_json.return_value = {
        "messages": [
            {
                "type": "narration",
                "sender_type": "narrator",
                "sender_name": "旁白",
                "content": "（模拟回复）",
                "virtual_time_offset_minutes": 0,
            }
        ]
    }
    app.state.llm = mock_llm
    app.state.extraction_service = ExtractionService(llm=mock_llm)
    app.state.search_service = None
    yield


async def _wait_ready(api_client, world_id: str):
    """轮询 creation-status 直到 world ready。"""
    for _ in range(MAX_POLL_ATTEMPTS):
        r = await api_client.get(f"/api/worlds/{world_id}/creation-status")
        if r.status_code == 200 and r.json()["status"] == "ready":
            return
        if r.json().get("status") == "failed":
            pytest.fail(f"World {world_id} creation failed")
        await asyncio.sleep(POLL_INTERVAL)
    pytest.fail(f"World {world_id} did not become ready in time")


class TestWorldCRUD:
    """Tracer bullet: create → list → get roundtrip."""

    async def test_create_and_list_worlds(self, api_client):
        # Count existing worlds
        r = await api_client.get("/api/worlds")
        assert r.status_code == 200
        before_count = len(r.json())

        r = await api_client.post("/api/worlds", json={"title": "三体世界"})
        assert r.status_code == 202
        world_id = r.json()["world_id"]

        await _wait_ready(api_client, world_id)

        r = await api_client.get("/api/worlds")
        assert r.status_code == 200
        worlds = r.json()
        assert len(worlds) == before_count + 1
        world_ids = [w["world_id"] for w in worlds]
        assert world_id in world_ids

    async def test_get_world_by_id(self, api_client):
        r = await api_client.post(
            "/api/worlds",
            json={"title": "沙丘世界", "author": "弗兰克·赫伯特"},
        )
        assert r.status_code == 202
        world_id = r.json()["world_id"]

        await _wait_ready(api_client, world_id)

        r = await api_client.get(f"/api/worlds/{world_id}")
        assert r.status_code == 200
        world = r.json()
        assert world["source"]["title"] == "沙丘世界"
        assert world["source"]["author"] == "弗兰克·赫伯特"

    async def test_get_nonexistent_world_returns_404(self, api_client):
        r = await api_client.get("/api/worlds/00000000-0000-0000-0000-000000000099")
        assert r.status_code == 404

    async def test_copy_world(self, api_client):
        r = await api_client.post("/api/worlds", json={"title": "原版世界"})
        assert r.status_code == 202
        original_id = r.json()["world_id"]

        await _wait_ready(api_client, original_id)

        r = await api_client.post(f"/api/worlds/{original_id}/copy")
        assert r.status_code == 201
        copy = r.json()
        assert copy["source"]["title"] == "原版世界"
        assert copy["world_id"] != original_id


class TestCharactersChain:
    """World → Characters → Graph 链路测试."""

    async def _create_world(self, api_client, title="角色测试世界"):
        r = await api_client.post("/api/worlds", json={"title": title})
        assert r.status_code == 202
        world_id = r.json()["world_id"]
        await _wait_ready(api_client, world_id)
        return world_id

    async def test_create_and_list_characters(self, api_client):
        world_id = await self._create_world(api_client)

        # M14: world creation auto-generates a world user character (username = "testuser")
        r = await api_client.get(f"/api/worlds/{world_id}/characters")
        assert r.status_code == 200
        initial = r.json()
        assert len(initial) == 1
        assert initial[0]["name"] == "testuser"

        # Create a character
        r = await api_client.post(
            f"/api/worlds/{world_id}/characters",
            json={"name": "叶文洁", "profile": {"brief": "天体物理学家"}},
        )
        assert r.status_code == 201
        char = r.json()
        assert char["name"] == "叶文洁"
        assert char["world_id"] == world_id
        _char_id = char["id"]

        # Create another
        r = await api_client.post(
            f"/api/worlds/{world_id}/characters",
            json={"name": "汪淼", "profile": {"brief": "纳米材料科学家"}},
        )
        assert r.status_code == 201

        # List should have 3 (world user + 2 created)
        r = await api_client.get(f"/api/worlds/{world_id}/characters")
        assert r.status_code == 200
        chars = r.json()
        assert len(chars) == 3
        names = {c["name"] for c in chars}
        assert {"叶文洁", "汪淼"}.issubset(names)

    async def test_get_character_by_id(self, api_client):
        world_id = await self._create_world(api_client)

        r = await api_client.post(
            f"/api/worlds/{world_id}/characters",
            json={"name": "罗辑", "profile": {"brief": "面壁者"}},
        )
        char_id = r.json()["id"]

        r = await api_client.get(f"/api/worlds/{world_id}/characters/{char_id}")
        assert r.status_code == 200
        assert r.json()["name"] == "罗辑"

    async def test_update_character(self, api_client):
        world_id = await self._create_world(api_client)

        r = await api_client.post(
            f"/api/worlds/{world_id}/characters",
            json={"name": "程心"},
        )
        char_id = r.json()["id"]

        r = await api_client.put(
            f"/api/worlds/{world_id}/characters/{char_id}",
            json={"name": "程心", "profile": {"brief": "执剑人"}},
        )
        assert r.status_code == 200
        assert r.json()["profile"]["brief"] == "执剑人"

    async def test_delete_character(self, api_client):
        world_id = await self._create_world(api_client)

        r = await api_client.post(
            f"/api/worlds/{world_id}/characters",
            json={"name": "云天明"},
        )
        char_id = r.json()["id"]

        r = await api_client.delete(f"/api/worlds/{world_id}/characters/{char_id}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True

        r = await api_client.get(f"/api/worlds/{world_id}/characters/{char_id}")
        assert r.status_code == 404

    async def test_graph_data_with_characters_and_relations(self, api_client):
        world_id = await self._create_world(api_client)

        # Create two characters
        r = await api_client.post(
            f"/api/worlds/{world_id}/characters",
            json={"name": "叶文洁"},
        )
        char_a_id = r.json()["id"]

        r = await api_client.post(
            f"/api/worlds/{world_id}/characters",
            json={"name": "汪淼"},
        )
        char_b_id = r.json()["id"]

        # Create a relation between them
        r = await api_client.post(
            f"/api/worlds/{world_id}/relations",
            json={
                "character_a": char_a_id,
                "character_b": char_b_id,
                "type": "同事",
            },
        )
        assert r.status_code == 201

        # Get graph data
        r = await api_client.get(f"/api/worlds/{world_id}/graph/data")
        assert r.status_code == 200
        graph = r.json()
        assert len(graph["characters"]) == 3  # 2 created + 1 world user character (M14)
        assert len(graph["relations"]) == 1
        assert graph["relations"][0]["type"] == "同事"
