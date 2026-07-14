"""API tests for /api/worlds/{world_id}/relations endpoints."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.relation import Relation


@pytest.fixture
def mock_relation_service():
    return AsyncMock()


@pytest.fixture
def client(mock_relation_service):
    from unittest.mock import AsyncMock

    from src.api.relations import router
    from src.db.session import get_session

    app = FastAPI()
    app.include_router(router)
    app.state.relation_service = mock_relation_service
    app.state.redis = None  # publish_snapshot_dirty handles None gracefully

    # Override get_session so bump_generation_sql doesn't hit a real DB
    mock_session = AsyncMock()

    async def _override_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = _override_get_session
    return TestClient(app)


def _make_relation(**kwargs) -> Relation:
    data = {
        "id": str(uuid.uuid4()),
        "world_id": "w-001",
        "character_a": "a-001",
        "character_b": "b-001",
        "type": "同事",
        "direction": "bidirectional",
        "status": "active",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    data.update(kwargs)
    return Relation.model_validate(data)


class TestCreateRelation:
    def test_success_201(self, client, mock_relation_service):
        mock_relation_service.create.return_value = _make_relation()
        resp = client.post(
            "/api/worlds/w-001/relations",
            json={"character_a": "a-001", "character_b": "b-001", "type": "同事"},
        )
        assert resp.status_code == 201

    def test_character_not_found_404(self, client, mock_relation_service):
        mock_relation_service.create.side_effect = ValueError("Character not found")
        resp = client.post(
            "/api/worlds/w-001/relations",
            json={"character_a": "bad", "character_b": "b-001", "type": "同事"},
        )
        assert resp.status_code == 404


class TestGetRelation:
    def test_success_200(self, client, mock_relation_service):
        mock_relation_service.get.return_value = _make_relation()
        resp = client.get("/api/worlds/w-001/relations/rel-001")
        assert resp.status_code == 200

    def test_not_found_404(self, client, mock_relation_service):
        mock_relation_service.get.return_value = None
        resp = client.get("/api/worlds/w-001/relations/nonexistent")
        assert resp.status_code == 404


class TestListRelations:
    def test_list_200(self, client, mock_relation_service):
        mock_relation_service.list_by_world.return_value = [_make_relation()]
        resp = client.get("/api/worlds/w-001/relations")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_filter_by_character(self, client, mock_relation_service):
        mock_relation_service.list_by_world.return_value = []
        resp = client.get("/api/worlds/w-001/relations?character_id=a-001")
        assert resp.status_code == 200
        mock_relation_service.list_by_world.assert_called_once_with("w-001", "a-001")


class TestUpdateRelation:
    def test_success_200(self, client, mock_relation_service):
        mock_relation_service.update.return_value = _make_relation(type="上下级")
        resp = client.put(
            "/api/worlds/w-001/relations/rel-001",
            json={"type": "上下级"},
        )
        assert resp.status_code == 200

    def test_not_found_404(self, client, mock_relation_service):
        mock_relation_service.update.return_value = None
        resp = client.put(
            "/api/worlds/w-001/relations/nonexistent",
            json={"type": "x"},
        )
        assert resp.status_code == 404
