from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DiscordBindingCreate(BaseModel):
    guild_id: str


class DiscordBinding(BaseModel):
    id: str
    world_id: str
    guild_id: str
    channel_daily: str | None = None
    channel_event: str | None = None
    channel_chat: str | None = None
    narrator_webhook_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CharacterWebhook(BaseModel):
    id: str
    world_id: str
    character_id: str
    webhook_id: str
    webhook_url: str
    created_at: datetime

    model_config = {"from_attributes": True}
