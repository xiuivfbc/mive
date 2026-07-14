from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MatterbridgeBindingCreate(BaseModel):
    """Input for creating a Matterbridge binding (token is plaintext, will be encrypted)."""

    api_url: str
    api_token: str
    config_json: dict | None = None


class MatterbridgeBindingUpdate(BaseModel):
    """Partial update for a Matterbridge binding."""

    api_url: str | None = None
    api_token: str | None = None
    enabled: bool | None = None
    config_json: dict | None = None


class MatterbridgeBinding(BaseModel):
    """DB representation of a Matterbridge binding (token is masked)."""

    id: str
    world_id: str
    api_url: str
    api_token_preview: str
    enabled: bool
    config_json: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
