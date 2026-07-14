"""Tests for Discord Bridge API endpoints.

POST /api/worlds/{world_id}/discord-binding
DELETE /api/worlds/{world_id}/discord-binding
GET /api/worlds/{world_id}/discord-binding
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.discord_bridge import DiscordBinding


def _make_binding(**kwargs) -> DiscordBinding:
    now = datetime.now(UTC)
    return DiscordBinding(
        id=kwargs.get("id", "binding-001"),
        world_id=kwargs.get("world_id", "world-001"),
        guild_id=kwargs.get("guild_id", "guild-123"),
        channel_daily=kwargs.get("channel_daily", "ch-daily"),
        channel_event=kwargs.get("channel_event", "ch-event"),
        channel_chat=kwargs.get("channel_chat", "ch-chat"),
        narrator_webhook_url=kwargs.get("narrator_webhook_url", None),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def mock_bridge_service():
    return AsyncMock()


@pytest.fixture
def client(mock_bridge_service):
    from src.api.discord_bridge import router

    app = FastAPI()
    app.include_router(router)
    app.state.discord_bridge_service = mock_bridge_service

    return TestClient(app)


class TestCreateBinding:
    def test_creates_binding_returns_201(self, client, mock_bridge_service):
        binding = _make_binding()
        mock_bridge_service.create_binding.return_value = binding

        resp = client.post(
            "/api/worlds/world-001/discord-binding",
            json={"guild_id": "guild-123"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["guild_id"] == "guild-123"
        assert data["world_id"] == "world-001"

    def test_missing_guild_id_returns_422(self, client, mock_bridge_service):
        resp = client.post("/api/worlds/world-001/discord-binding", json={})
        assert resp.status_code == 422

    def test_duplicate_binding_overwrites(self, client, mock_bridge_service):
        binding = _make_binding(guild_id="new-guild")
        mock_bridge_service.create_binding.return_value = binding

        resp = client.post(
            "/api/worlds/world-001/discord-binding",
            json={"guild_id": "new-guild"},
        )

        assert resp.status_code == 201
        mock_bridge_service.create_binding.assert_called_once_with("world-001", "new-guild")


class TestDeleteBinding:
    def test_deletes_binding_returns_204(self, client, mock_bridge_service):
        mock_bridge_service.delete_binding.return_value = True

        resp = client.delete("/api/worlds/world-001/discord-binding")

        assert resp.status_code == 204
        mock_bridge_service.delete_binding.assert_called_once_with("world-001")

    def test_delete_nonexistent_returns_404(self, client, mock_bridge_service):
        mock_bridge_service.delete_binding.return_value = False

        resp = client.delete("/api/worlds/world-001/discord-binding")

        assert resp.status_code == 404


class TestGetBinding:
    def test_returns_binding(self, client, mock_bridge_service):
        binding = _make_binding()
        mock_bridge_service.get_binding.return_value = binding

        resp = client.get("/api/worlds/world-001/discord-binding")

        assert resp.status_code == 200
        assert resp.json()["guild_id"] == "guild-123"

    def test_returns_404_when_not_bound(self, client, mock_bridge_service):
        mock_bridge_service.get_binding.return_value = None

        resp = client.get("/api/worlds/world-001/discord-binding")

        assert resp.status_code == 404
