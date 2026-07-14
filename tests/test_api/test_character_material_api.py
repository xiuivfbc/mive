"""API 集成测试：GET /worlds/{id}/character-material 端点。"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.material import CharacterMaterial
from src.models.world import Element, WorldDoc, WorldMeta, WorldSource

WORLD_ID = str(uuid.uuid4())


def _make_material() -> CharacterMaterial:
    return CharacterMaterial(
        world_id=WORLD_ID,
        world_version="1.0",
        world_elements=[
            Element(id="e1", category="地点", name="长安", brief="都城", detail="繁华"),
        ],
        world_rules_summary="作品：三体\n核心设定：...",
        generated_at=datetime(2025, 1, 1),
    )


def _make_world() -> WorldDoc:
    return WorldDoc(
        world_id=WORLD_ID,
        version="1.0",
        source=WorldSource(title="三体"),
        meta=WorldMeta(),
        elements=[],
    )


def _build_client(world=None, material=None):
    from src.api.character_material import router
    from src.api.deps import get_material_service, get_world_service

    app = FastAPI()
    app.include_router(router)

    mock_world_svc = AsyncMock()
    mock_world_svc.get_world = AsyncMock(return_value=world)

    mock_material_svc = MagicMock()
    mock_material_svc.generate = MagicMock(return_value=material or _make_material())

    app.dependency_overrides[get_world_service] = lambda: mock_world_svc
    app.dependency_overrides[get_material_service] = lambda: mock_material_svc

    client = TestClient(app, raise_server_exceptions=False)
    return client, mock_world_svc, mock_material_svc


class TestCharacterMaterialEndpoint:
    def test_returns_200_with_material(self):
        client, _, _ = _build_client(world=_make_world())
        resp = client.get(f"/api/worlds/{WORLD_ID}/character-material")
        assert resp.status_code == 200

    def test_returns_material_fields(self):
        client, _, _ = _build_client(world=_make_world())
        resp = client.get(f"/api/worlds/{WORLD_ID}/character-material")
        body = resp.json()
        assert body["world_id"] == WORLD_ID
        assert "world_elements" in body
        assert "world_rules_summary" in body

    def test_world_not_found_returns_404(self):
        client, _, _ = _build_client(world=None)
        resp = client.get(f"/api/worlds/{WORLD_ID}/character-material")
        assert resp.status_code == 404

    def test_calls_world_service_with_correct_id(self):
        client, world_svc, _ = _build_client(world=_make_world())
        client.get(f"/api/worlds/{WORLD_ID}/character-material")
        world_svc.get_world.assert_called_once_with(WORLD_ID)

    def test_calls_material_service_generate(self):
        world = _make_world()
        client, _, material_svc = _build_client(world=world)
        client.get(f"/api/worlds/{WORLD_ID}/character-material")
        material_svc.generate.assert_called_once_with(world)

    def test_empty_elements_world_returns_material(self):
        """空元素世界也应正常返回素材包（rules_summary 为空字符串）。"""
        world = _make_world()
        material = CharacterMaterial(
            world_id=WORLD_ID,
            world_version="1.0",
            world_elements=[],
            world_rules_summary="",
            generated_at=datetime(2025, 1, 1),
        )
        client, _, _ = _build_client(world=world, material=material)
        resp = client.get(f"/api/worlds/{WORLD_ID}/character-material")
        assert resp.status_code == 200
        assert resp.json()["world_elements"] == []
