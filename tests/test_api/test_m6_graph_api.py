"""Tests for M6 graph API endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_services():
    return {
        "ontology_gen": AsyncMock(),
        "graph_builder": MagicMock(),
        "entity_reader": MagicMock(),
        "task_manager": MagicMock(),
        "world_service": AsyncMock(),
        "char_service": AsyncMock(),
        "rel_service": AsyncMock(),
    }


@pytest.fixture
def client(mock_services):
    from src.api.graph import router as graph_router
    from src.api.m6_graph import router as m6_router

    app = FastAPI()

    # 注册 M6 路由
    app.include_router(m6_router)
    app.include_router(graph_router)

    # 注入 mock services 到 app.state
    app.state.ontology_generator = mock_services["ontology_gen"]
    app.state.graph_builder = mock_services["graph_builder"]
    app.state.entity_reader = mock_services["entity_reader"]
    app.state.task_manager = mock_services["task_manager"]
    app.state.character_service = mock_services["char_service"]
    app.state.relation_service = mock_services["rel_service"]

    # world_service 需要特殊处理
    world_svc = mock_services["world_service"]
    world_svc.get_world.return_value = MagicMock(
        world_id="w1", graph_status="idle", graph_ontology=None
    )
    app.state.world_service = world_svc

    return TestClient(app)


WORLD_ID = "12345678-1234-1234-1234-123456789abc"


class TestOntologyGenerate:
    def test_returns_ontology(self, client, mock_services):
        mock_services["ontology_gen"].generate.return_value = {
            "entity_types": ["character", "organization"],
            "relation_types": ["ally", "enemy"],
            "constraints": {
                "min_entity_types": 2,
                "max_entity_types": 10,
                "fallback_types": ["character"],
            },
        }

        resp = client.post(f"/api/worlds/{WORLD_ID}/graph/ontology/generate")
        assert resp.status_code == 200
        data = resp.json()
        assert "entity_types" in data
        assert "character" in data["entity_types"]


class TestGraphBuild:
    def test_returns_task_id(self, client, mock_services):
        mock_services["graph_builder"].build_async.return_value = "task_abc123"

        resp = client.post(
            f"/api/worlds/{WORLD_ID}/graph/build",
            json={"ontology": {"entity_types": ["character"], "relation_types": ["ally"]}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data


class TestTaskQuery:
    def test_returns_task_status(self, client, mock_services):
        from datetime import datetime

        from src.services.task_manager import Task, TaskStatus

        task = Task(
            task_id="task_abc",
            task_type="graph_build",
            status=TaskStatus.PROCESSING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            progress=50,
            message="building...",
        )
        mock_services["task_manager"].get_task.return_value = task

        resp = client.get(f"/api/worlds/{WORLD_ID}/graph/task/task_abc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["progress"] == 50

    def test_task_not_found(self, client, mock_services):
        mock_services["task_manager"].get_task.return_value = None

        resp = client.get(f"/api/worlds/{WORLD_ID}/graph/task/nonexistent")
        assert resp.status_code == 404


class TestEntities:
    def test_returns_entities(self, client, mock_services):
        mock_services["entity_reader"].read_entities.return_value = [
            {
                "uuid": "n1",
                "name": "张三",
                "entity_type": "character",
                "labels": ["character"],
                "summary": "",
                "attributes": {},
                "related_edges": [],
            },
        ]

        resp = client.get(f"/api/worlds/{WORLD_ID}/graph/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entities"]) == 1
        assert data["entities"][0]["name"] == "张三"

    def test_entity_type_filter(self, client, mock_services):
        mock_services["entity_reader"].read_entities.return_value = []

        client.get(f"/api/worlds/{WORLD_ID}/graph/entities?entity_types=character")
        mock_services["entity_reader"].read_entities.assert_called_once()
        call_kwargs = mock_services["entity_reader"].read_entities.call_args
        assert call_kwargs[1].get("entity_types") == ["character"] or "character" in str(
            call_kwargs
        )


class TestGraphDataExtended:
    def test_includes_graph_status(self, client, mock_services):
        mock_services["char_service"].list_by_world.return_value = []
        mock_services["rel_service"].list_by_world.return_value = []

        # mock world_service to return graph info
        world = MagicMock()
        world.graph_status = "completed"
        world.graph_ontology = {"entity_types": ["character"]}
        mock_services["world_service"].get_world.return_value = world

        resp = client.get(f"/api/worlds/{WORLD_ID}/graph/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["graph_status"] == "completed"
        assert data["graph_ontology"] is not None
