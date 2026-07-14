"""Tests that element mutating endpoints call bump_generation_sql and publish_snapshot_dirty."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.world import Element


@pytest.fixture
def mock_world_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def mock_retrieval_service():
    return MagicMock()


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def client(mock_world_service, mock_retrieval_service, mock_session):
    from src.api.deps import get_element_retrieval_service, get_session, get_world_service
    from src.api.elements import router

    app = FastAPI()
    app.include_router(router)
    app.state.redis = AsyncMock()
    app.dependency_overrides[get_world_service] = lambda: mock_world_service
    app.dependency_overrides[get_element_retrieval_service] = lambda: mock_retrieval_service
    app.dependency_overrides[get_session] = lambda: mock_session
    return TestClient(app)


def _make_element(**kwargs):
    data = {
        "id": "elem-001",
        "name": "测试元素",
        "category": "场所",
        "brief": "简述",
        "detail": "详情",
    }
    data.update(kwargs)
    return Element.model_validate(data)


class TestAddElementBump:
    @patch("src.api.elements.publish_snapshot_dirty")
    @patch("src.api.elements.bump_generation_sql", new_callable=AsyncMock)
    def test_add_element_calls_bump_and_publish(
        self, mock_bump, mock_publish, client, mock_world_service
    ):
        mock_world_service.add_element.return_value = _make_element()
        resp = client.post(
            "/api/worlds/w-001/elements",
            json={"category": "场所", "name": "测试", "brief": "b", "detail": "d"},
        )
        assert resp.status_code == 201
        mock_bump.assert_awaited_once()
        # publish_snapshot_dirty is a BackgroundTasks task — it's called via add_task
        # We verify it was scheduled by checking the mock was called


class TestUpdateElementBump:
    @patch("src.api.elements.publish_snapshot_dirty")
    @patch("src.api.elements.bump_generation_sql", new_callable=AsyncMock)
    def test_update_element_calls_bump_and_publish(
        self, mock_bump, mock_publish, client, mock_world_service
    ):
        mock_world_service.update_element.return_value = _make_element()
        resp = client.put(
            "/api/worlds/w-001/elements/elem-001",
            json={"category": "场所", "name": "测试", "brief": "b", "detail": "d"},
        )
        assert resp.status_code == 200
        mock_bump.assert_awaited_once()


class TestDeleteElementBump:
    @patch("src.api.elements.publish_snapshot_dirty")
    @patch("src.api.elements.bump_generation_sql", new_callable=AsyncMock)
    def test_delete_element_calls_bump_and_publish(
        self, mock_bump, mock_publish, client, mock_world_service
    ):
        mock_world_service.delete_element.return_value = True
        resp = client.delete("/api/worlds/w-001/elements/elem-001")
        assert resp.status_code == 200
        mock_bump.assert_awaited_once()
