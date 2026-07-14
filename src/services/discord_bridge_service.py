from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.db.models import M8DiscordBinding
from src.db.repositories.discord_bridge_repo import DiscordBridgeRepository
from src.models.discord_bridge import DiscordBinding

if TYPE_CHECKING:
    from src.discord_bot.webhook_manager import WebhookManager

logger = logging.getLogger(__name__)

_DISCORD_API = "https://discord.com/api/v10"


class DiscordBridgeService:
    def __init__(
        self,
        repo: DiscordBridgeRepository,
        webhook_manager: WebhookManager | None = None,
    ) -> None:
        self.repo = repo
        self.wm = webhook_manager

    async def get_binding(self, world_id: str) -> DiscordBinding | None:
        row = await self.repo.get_binding(world_id)
        return self._to_model(row) if row else None

    async def create_binding(self, world_id: str, guild_id: str) -> DiscordBinding:
        """Store guild_id only. Call setup_binding to create channels + webhooks."""
        row = await self.repo.upsert_binding(world_id=world_id, guild_id=guild_id)
        return self._to_model(row)

    async def setup_binding(
        self,
        world_id: str,
        guild_id: str,
        characters: list,
        base_url: str,
    ) -> DiscordBinding:
        """Create Discord channels + webhooks for all characters, then save binding.

        characters: list of Character pydantic models (need .id, .name)
        base_url: public URL of the backend (e.g. https://xxx.ngrok.io) for avatar URLs
        """
        if self.wm is None:
            raise RuntimeError("WebhookManager not configured (DISCORD_BOT_TOKEN missing?)")

        # 1. Create three channels
        ch_daily = await self.wm.create_guild_channel(guild_id, "日常")
        ch_event = await self.wm.create_guild_channel(guild_id, "事件")
        ch_chat = await self.wm.create_guild_channel(guild_id, "角色聊天")

        # 2. Create narrator webhook in #事件 channel
        narrator_wh = await self.wm.create_narrator_webhook(ch_event)

        # 3. Create character webhooks in #角色聊天 channel
        for char in characters:
            avatar_url = f"{base_url}/api/worlds/{world_id}/characters/{char.id}/avatar"
            try:
                await self.wm.create_character_webhook(
                    world_id=world_id,
                    character_id=str(char.id),
                    channel_id=ch_chat,
                    character_name=char.name,
                    avatar_url=avatar_url,
                )
            except Exception as e:
                logger.warning("Failed to create webhook for %s: %s", char.name, e)

        # 4. Upsert binding with all channel IDs
        row = await self.repo.upsert_binding(
            world_id=world_id,
            guild_id=guild_id,
            channel_daily=ch_daily,
            channel_event=ch_event,
            channel_chat=ch_chat,
            narrator_webhook_url=narrator_wh,
        )
        return self._to_model(row)

    async def delete_binding(self, world_id: str) -> bool:
        """Delete binding and clean up Discord webhooks/channels."""
        row = await self.repo.get_binding(world_id)
        if row is None:
            return False

        if self.wm is not None:
            # Delete character webhooks
            webhooks = await self.repo.list_character_webhooks(world_id)
            for wh in webhooks:
                try:
                    await self.wm.delete_webhook(wh.webhook_id)
                except Exception as e:
                    logger.warning("Failed to delete webhook %s: %s", wh.webhook_id, e)

            # Delete channels
            for ch_id in [row.channel_daily, row.channel_event, row.channel_chat]:
                if ch_id:
                    try:
                        await self.wm.delete_guild_channel(ch_id)
                    except Exception as e:
                        logger.warning("Failed to delete channel %s: %s", ch_id, e)

        await self.repo.delete_character_webhooks_for_world(world_id)
        return await self.repo.delete_binding(world_id)

    @staticmethod
    def _to_model(row: M8DiscordBinding) -> DiscordBinding:
        return DiscordBinding(
            id=str(row.id),
            world_id=str(row.world_id),
            guild_id=row.guild_id,
            channel_daily=row.channel_daily,
            channel_event=row.channel_event,
            channel_chat=row.channel_chat,
            narrator_webhook_url=row.narrator_webhook_url,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
