"""Tests for discord_bot/webhook_manager.py — webhook lifecycle (Discord API mocked)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.discord_bot.webhook_manager import WebhookManager


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def manager(mock_repo):
    return WebhookManager(bot_token="test-token", repo=mock_repo)


class TestCreateCharacterWebhook:
    @pytest.mark.asyncio
    async def test_creates_webhook_and_stores_url(self, manager, mock_repo):
        discord_response = {"id": "wh-001", "url": "https://discord.com/api/webhooks/wh-001/token"}
        mock_http = AsyncMock()
        mock_http.post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=discord_response),
            raise_for_status=MagicMock(),
        )

        with patch.object(manager, "_http", mock_http):
            url = await manager.create_character_webhook(
                world_id="world-001",
                character_id="char-001",
                channel_id="ch-123",
                character_name="爱丽丝",
                avatar_url=None,
            )

        assert url == discord_response["url"]
        mock_repo.upsert_character_webhook.assert_called_once_with(
            world_id="world-001",
            character_id="char-001",
            webhook_id="wh-001",
            webhook_url=discord_response["url"],
        )

    @pytest.mark.asyncio
    async def test_discord_error_raises(self, manager, mock_repo):
        import httpx

        mock_http = AsyncMock()
        mock_http.post.return_value = MagicMock(
            status_code=403,
            raise_for_status=MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "403 Forbidden", request=MagicMock(), response=MagicMock()
                )
            ),
        )

        with patch.object(manager, "_http", mock_http):
            with pytest.raises(httpx.HTTPStatusError):
                await manager.create_character_webhook(
                    world_id="world-001",
                    character_id="char-001",
                    channel_id="ch-123",
                    character_name="爱丽丝",
                    avatar_url=None,
                )


class TestDeleteWebhook:
    @pytest.mark.asyncio
    async def test_deletes_webhook_via_discord_api(self, manager, mock_repo):
        mock_http = AsyncMock()
        mock_http.delete.return_value = MagicMock(
            status_code=204,
            raise_for_status=MagicMock(),
        )

        with patch.object(manager, "_http", mock_http):
            await manager.delete_webhook("wh-001")

        mock_http.delete.assert_called_once()
        call_url = mock_http.delete.call_args[0][0]
        assert "wh-001" in call_url


class TestCreateGuildChannel:
    @pytest.mark.asyncio
    async def test_creates_text_channel_returns_id(self, manager, mock_repo):
        discord_response = {"id": "ch-new-001", "name": "日常"}
        mock_http = AsyncMock()
        mock_http.post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value=discord_response),
            raise_for_status=MagicMock(),
        )

        with patch.object(manager, "_http", mock_http):
            channel_id = await manager.create_guild_channel(
                guild_id="guild-001",
                name="日常",
            )

        assert channel_id == "ch-new-001"

    @pytest.mark.asyncio
    async def test_delete_guild_channel(self, manager, mock_repo):
        mock_http = AsyncMock()
        mock_http.delete.return_value = MagicMock(
            status_code=200,
            raise_for_status=MagicMock(),
        )

        with patch.object(manager, "_http", mock_http):
            await manager.delete_guild_channel("ch-001")

        mock_http.delete.assert_called_once()
        assert "ch-001" in mock_http.delete.call_args[0][0]
