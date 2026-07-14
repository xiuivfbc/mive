"""API tests for /api/worlds/{world_id}/versions endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.proposal import WorldVersion


@pytest.fixture
def mock_version_service():
    return AsyncMock()


@pytest.fixture
def client(mock_version_service):
    from src.api.versions import router

    app = FastAPI()
    app.include_router(router)
    app.state.version_service = mock_version_service
    return TestClient(app)


class TestListVersions:
    def test_list_200(self, client, mock_version_service):
        mock_version_service.list_by_world.return_value = [
            WorldVersion(id="v-001", world_id="w-001", snapshot={}, created_at=datetime.now()),
        ]
        resp = client.get("/api/worlds/w-001/versions")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestRollbackVersion:
    def test_success_201(self, client, mock_version_service):
        mock_version_service.rollback.return_value = WorldVersion(
            id="v-003",
            world_id="w-001",
            snapshot={},
            created_at=datetime.now(),
        )
        resp = client.post("/api/worlds/w-001/versions/v-001/rollback")
        assert resp.status_code == 201
        assert resp.json()["id"] == "v-003"

    def test_not_found_404(self, client, mock_version_service):
        mock_version_service.rollback.side_effect = ValueError("Version not found")
        resp = client.post("/api/worlds/w-001/versions/bad/rollback")
        assert resp.status_code == 404
