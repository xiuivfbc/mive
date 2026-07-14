from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M8CharacterWebhook, M8DiscordBinding


class DiscordBridgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_binding(self, world_id: str) -> M8DiscordBinding | None:
        result = await self.session.execute(
            select(M8DiscordBinding).where(M8DiscordBinding.world_id == uuid.UUID(world_id))
        )
        return result.scalar_one_or_none()

    async def upsert_binding(
        self,
        world_id: str,
        guild_id: str,
        channel_daily: str | None = None,
        channel_event: str | None = None,
        channel_chat: str | None = None,
        narrator_webhook_url: str | None = None,
    ) -> M8DiscordBinding:
        stmt = (
            insert(M8DiscordBinding)
            .values(
                id=uuid.uuid4(),
                world_id=uuid.UUID(world_id),
                guild_id=guild_id,
                channel_daily=channel_daily,
                channel_event=channel_event,
                channel_chat=channel_chat,
                narrator_webhook_url=narrator_webhook_url,
            )
            .on_conflict_do_update(
                index_elements=["world_id"],
                set_={
                    "guild_id": guild_id,
                    "channel_daily": channel_daily,
                    "channel_event": channel_event,
                    "channel_chat": channel_chat,
                    "narrator_webhook_url": narrator_webhook_url,
                },
            )
            .returning(M8DiscordBinding)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def delete_binding(self, world_id: str) -> bool:
        result = await self.session.execute(
            delete(M8DiscordBinding).where(M8DiscordBinding.world_id == uuid.UUID(world_id))
        )
        await self.session.flush()
        return cast(CursorResult, result).rowcount > 0

    # --- Character webhooks ---

    async def upsert_character_webhook(
        self,
        world_id: str,
        character_id: str,
        webhook_id: str,
        webhook_url: str,
    ) -> M8CharacterWebhook:
        stmt = (
            insert(M8CharacterWebhook)
            .values(
                id=uuid.uuid4(),
                world_id=uuid.UUID(world_id),
                character_id=uuid.UUID(character_id),
                webhook_id=webhook_id,
                webhook_url=webhook_url,
            )
            .on_conflict_do_update(
                index_elements=["character_id"],
                set_={"webhook_id": webhook_id, "webhook_url": webhook_url},
            )
            .returning(M8CharacterWebhook)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def get_character_webhook(self, character_id: str) -> M8CharacterWebhook | None:
        result = await self.session.execute(
            select(M8CharacterWebhook).where(
                M8CharacterWebhook.character_id == uuid.UUID(character_id)
            )
        )
        return result.scalar_one_or_none()

    async def list_character_webhooks(self, world_id: str) -> list[M8CharacterWebhook]:
        result = await self.session.execute(
            select(M8CharacterWebhook).where(M8CharacterWebhook.world_id == uuid.UUID(world_id))
        )
        return list(result.scalars().all())

    async def delete_character_webhooks_for_world(self, world_id: str) -> int:
        result = await self.session.execute(
            delete(M8CharacterWebhook).where(M8CharacterWebhook.world_id == uuid.UUID(world_id))
        )
        await self.session.flush()
        return cast(CursorResult, result).rowcount
