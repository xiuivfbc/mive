from __future__ import annotations

import httpx

from src.db.repositories.discord_bridge_repo import DiscordBridgeRepository

_DISCORD_API = "https://discord.com/api/v10"


class WebhookManager:
    """Manages Discord webhook lifecycle via the Discord REST API."""

    def __init__(self, bot_token: str, repo: DiscordBridgeRepository) -> None:
        self.bot_token = bot_token
        self.repo = repo
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bot {bot_token}"},
            timeout=10.0,
        )

    async def create_character_webhook(
        self,
        world_id: str,
        character_id: str,
        channel_id: str,
        character_name: str,
        avatar_url: str | None,
    ) -> str:
        """Create a webhook for a character in the given channel. Returns webhook URL."""
        payload: dict = {"name": character_name[:80]}
        if avatar_url:
            payload["avatar"] = avatar_url

        resp = await self._http.post(
            f"{_DISCORD_API}/channels/{channel_id}/webhooks",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        webhook_id: str = data["id"]
        webhook_url: str = data["url"]

        await self.repo.upsert_character_webhook(
            world_id=world_id,
            character_id=character_id,
            webhook_id=webhook_id,
            webhook_url=webhook_url,
        )
        return webhook_url

    async def create_narrator_webhook(self, channel_id: str) -> str:
        """Create the narrator webhook in the given channel. Returns webhook URL."""
        resp = await self._http.post(
            f"{_DISCORD_API}/channels/{channel_id}/webhooks",
            json={"name": "旁白"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["url"]

    async def delete_webhook(self, webhook_id: str) -> None:
        """Delete a Discord webhook by ID."""
        resp = await self._http.delete(f"{_DISCORD_API}/webhooks/{webhook_id}")
        resp.raise_for_status()

    async def create_guild_channel(self, guild_id: str, name: str) -> str:
        """Create a text channel in the guild. Returns the new channel ID."""
        resp = await self._http.post(
            f"{_DISCORD_API}/guilds/{guild_id}/channels",
            json={"name": name, "type": 0},  # type 0 = GUILD_TEXT
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def delete_guild_channel(self, channel_id: str) -> None:
        """Delete a Discord channel by ID."""
        resp = await self._http.delete(f"{_DISCORD_API}/channels/{channel_id}")
        resp.raise_for_status()

    async def aclose(self) -> None:
        await self._http.aclose()
