"""API tests for /api/worlds/{world_id}/graph/data."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.character import Character
from src.models.relation import Relation


@pytest.fixture
def mock_character_service():
    return AsyncMock()


@pytest.fixture
def mock_relation_service():
    return AsyncMock()


@pytest.fixture
def mock_world_service():
    svc = AsyncMock()
    svc.get_world.return_value = None
    return svc


@pytest.fixture
def client(mock_character_service, mock_relation_service, mock_world_service):
    from src.api.graph import router

    app = FastAPI()
    app.include_router(router)
    app.state.character_service = mock_character_service
    app.state.relation_service = mock_relation_service
    app.state.world_service = mock_world_service
    return TestClient(app)


class TestGraphData:
    def test_returns_characters_and_relations(
        self, client, mock_character_service, mock_relation_service
    ):
        mock_character_service.list_by_world.return_value = [
            Character(
                id="c-001",
                world_id="w-001",
                name="叶文洁",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ),
        ]
        mock_relation_service.list_by_world.return_value = [
            Relation(
                id="r-001",
                world_id="w-001",
                character_a="c-001",
                character_b="c-002",
                type="同事",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ),
        ]

        resp = client.get("/api/worlds/w-001/graph/data")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["characters"]) == 1
        assert len(data["relations"]) == 1
        assert data["graph_status"] == "idle"

    def test_empty_world_returns_empty_arrays(
        self, client, mock_character_service, mock_relation_service
    ):
        mock_character_service.list_by_world.return_value = []
        mock_relation_service.list_by_world.return_value = []

        resp = client.get("/api/worlds/w-001/graph/data")

        assert resp.status_code == 200
        data = resp.json()
        assert data["characters"] == []
        assert data["relations"] == []
        assert data["graph_status"] == "idle"
        assert data["graph_ontology"] is None
