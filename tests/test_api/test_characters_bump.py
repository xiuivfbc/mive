"""Tests that character mutating endpoints call bump_generation_sql and publish_snapshot_dirty."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.character import Character


@pytest.fixture
def mock_character_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def mock_world_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def mock_relation_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def mock_retrieval_service():
    return MagicMock()


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def client(
    mock_character_service,
    mock_world_service,
    mock_relation_service,
    mock_retrieval_service,
    mock_session,
):
    from src.api.characters import router
    from src.api.deps import (
        get_character_service,
        get_element_retrieval_service,
        get_relation_service,
        get_session,
        get_world_service,
    )

    app = FastAPI()
    app.include_router(router)
    app.state.redis = AsyncMock()
    app.dependency_overrides[get_character_service] = lambda: mock_character_service
    app.dependency_overrides[get_world_service] = lambda: mock_world_service
    app.dependency_overrides[get_relation_service] = lambda: mock_relation_service
    app.dependency_overrides[get_element_retrieval_service] = lambda: mock_retrieval_service
    app.dependency_overrides[get_session] = lambda: mock_session
    return TestClient(app)


def _make_character(**kwargs):
    data = {
        "id": "char-001",
        "world_id": "w-001",
        "name": "叶文洁",
        "profile": {"brief": "", "detail": ""},
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    data.update(kwargs)
    return Character.model_validate(data)


class TestCreateCharacterBump:
    @patch("src.api.characters.publish_snapshot_dirty")
    @patch("src.api.characters.bump_generation_sql", new_callable=AsyncMock)
    def test_create_character_calls_bump_and_publish(
        self, mock_bump, mock_publish, client, mock_character_service
    ):
        mock_character_service.create.return_value = _make_character()
        resp = client.post(
            "/api/worlds/w-001/characters",
            json={"name": "叶文洁", "tier": "core"},
        )
        assert resp.status_code == 201
        mock_bump.assert_awaited_once()


class TestUpdateCharacterBump:
    @patch("src.api.characters.publish_snapshot_dirty")
    @patch("src.api.characters.bump_generation_sql", new_callable=AsyncMock)
    def test_update_character_calls_bump_and_publish(
        self, mock_bump, mock_publish, client, mock_character_service
    ):
        mock_character_service.update.return_value = _make_character()
        resp = client.put(
            "/api/worlds/w-001/characters/char-001",
            json={"name": "叶文洁"},
        )
        assert resp.status_code == 200
        mock_bump.assert_awaited_once()


class TestDeleteCharacterBump:
    @patch("src.api.characters.publish_snapshot_dirty")
    @patch("src.api.characters.bump_generation_sql", new_callable=AsyncMock)
    def test_delete_character_calls_bump_and_publish(
        self, mock_bump, mock_publish, client, mock_character_service
    ):
        mock_character_service.delete.return_value = True
        resp = client.delete("/api/worlds/w-001/characters/char-001")
        assert resp.status_code == 200
        mock_bump.assert_awaited_once()
