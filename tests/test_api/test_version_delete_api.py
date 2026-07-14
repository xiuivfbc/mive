"""API tests for DELETE /api/worlds/{world_id}/versions/{version_id}."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_version_service():
    return AsyncMock()


@pytest.fixture
def client(mock_version_service):
    from src.api.deps import get_version_service
    from src.api.versions import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_version_service] = lambda: mock_version_service
    return TestClient(app)


class TestDeleteVersion:
    def test_delete_success_200(self, client, mock_version_service):
        mock_version_service.delete_version = AsyncMock()
        resp = client.delete("/api/worlds/w-001/versions/v-001")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True}

    def test_delete_not_found_404(self, client, mock_version_service):
        mock_version_service.delete_version = AsyncMock(side_effect=ValueError("Version not found"))
        resp = client.delete("/api/worlds/w-001/versions/bad")
        assert resp.status_code == 404

    def test_delete_latest_version_409(self, client, mock_version_service):
        mock_version_service.delete_version = AsyncMock(
            side_effect=ValueError("Cannot delete the current version")
        )
        resp = client.delete("/api/worlds/w-001/versions/v-latest")
        assert resp.status_code == 409
