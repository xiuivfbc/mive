"""API tests for /api/worlds/{world_id}/characters endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.api.characters import router
from src.models.character import Character
from tests.helpers import build_test_client


@pytest.fixture
def mock_character_service():
    return AsyncMock()


@pytest.fixture
def mock_generation_service():
    return AsyncMock()


@pytest.fixture
def mock_relation_service():
    return AsyncMock()


@pytest.fixture
def client(mock_character_service, mock_generation_service, mock_relation_service):
    from unittest.mock import MagicMock

    from src.api.deps import get_element_retrieval_service, get_relation_service, get_session

    client = build_test_client(
        router,
        character_service=mock_character_service,
        generation_service=mock_generation_service,
        relation_service=mock_relation_service,
    )
    app = client.app
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    app.dependency_overrides[get_element_retrieval_service] = lambda: MagicMock()
    app.dependency_overrides[get_relation_service] = lambda: mock_relation_service
    app.state.redis = AsyncMock()
    return client


def _make_character_dict(name="叶文洁", world_id="w-001") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "world_id": world_id,
        "name": name,
        "portrait_url": None,
        "profile": {"basic": {"name": name}, "brief": "", "detail": ""},
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }


class TestCreateCharacter:
    def test_create_success_returns_201(self, client, mock_character_service):
        mock_character_service.create.return_value = Character.model_validate(
            _make_character_dict()
        )

        resp = client.post(
            "/api/worlds/w-001/characters",
            json={"name": "叶文洁"},
        )

        assert resp.status_code == 201
        assert resp.json()["name"] == "叶文洁"

    def test_create_calls_service(self, client, mock_character_service):
        mock_character_service.create.return_value = Character.model_validate(
            _make_character_dict()
        )

        client.post("/api/worlds/w-001/characters", json={"name": "叶文洁"})

        mock_character_service.create.assert_called_once()


class TestGetCharacter:
    def test_get_success_returns_200(self, client, mock_character_service):
        char_data = _make_character_dict()
        mock_character_service.get.return_value = Character.model_validate(char_data)

        resp = client.get(f"/api/worlds/w-001/characters/{char_data['id']}")

        assert resp.status_code == 200
        assert resp.json()["name"] == "叶文洁"

    def test_get_not_found_returns_404(self, client, mock_character_service):
        mock_character_service.get.return_value = None

        resp = client.get("/api/worlds/w-001/characters/nonexistent")

        assert resp.status_code == 404


class TestListCharacters:
    def test_list_returns_200_with_array(self, client, mock_character_service):
        mock_character_service.list_by_world.return_value = [
            Character.model_validate(_make_character_dict("叶文洁")),
            Character.model_validate(_make_character_dict("汪淼")),
        ]
        mock_character_service.max_updated_at.return_value = datetime(2024, 1, 1, tzinfo=UTC)

        resp = client.get("/api/worlds/w-001/characters")

        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestUpdateCharacter:
    def test_update_success_returns_200(self, client, mock_character_service):
        char_data = _make_character_dict("叶文洁v2")
        mock_character_service.update.return_value = Character.model_validate(char_data)

        resp = client.put(
            "/api/worlds/w-001/characters/char-001",
            json={"name": "叶文洁v2"},
        )

        assert resp.status_code == 200
        assert resp.json()["name"] == "叶文洁v2"

    def test_update_not_found_returns_404(self, client, mock_character_service):
        mock_character_service.update.return_value = None

        resp = client.put(
            "/api/worlds/w-001/characters/nonexistent",
            json={"name": "不存在"},
        )

        assert resp.status_code == 404


class TestDeleteCharacter:
    def test_delete_success_returns_200(self, client, mock_character_service):
        mock_character_service.delete.return_value = True

        resp = client.delete("/api/worlds/w-001/characters/char-001")

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_not_found_returns_404(self, client, mock_character_service):
        mock_character_service.delete.return_value = False

        resp = client.delete("/api/worlds/w-001/characters/nonexistent")

        assert resp.status_code == 404


class TestGenerateCharacters:
    def test_success_returns_201(self, client, mock_generation_service):
        mock_generation_service.generate.return_value = {"characters": 2, "relations": 3}

        resp = client.post("/api/worlds/w-001/characters/generate")

        assert resp.status_code == 201
        assert resp.json()["characters"] == 2

    def test_world_not_found_404(self, client, mock_generation_service):
        mock_generation_service.generate.side_effect = ValueError("World not found")

        resp = client.post("/api/worlds/bad-id/characters/generate")

        assert resp.status_code == 404

    def test_llm_error_500(self, client, mock_generation_service):
        mock_generation_service.generate.side_effect = RuntimeError("LLM timeout")

        resp = client.post("/api/worlds/w-001/characters/generate")

        assert resp.status_code == 500
