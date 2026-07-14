from datetime import datetime

from pydantic import BaseModel, Field


class Character(BaseModel):
    id: str
    world_id: str
    name: str
    portrait_url: str | None = None
    profile: dict = Field(default_factory=dict)
    graph_node_uuid: str | None = None
    entity_type: str = "character"
    tier: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class CreateCharacterRequest(BaseModel):
    name: str = Field(min_length=1)
    portrait_url: str | None = None
    profile: dict | None = None


class UpdateCharacterRequest(BaseModel):
    name: str | None = None
    portrait_url: str | None = None
    profile: dict | None = None
    tier: str | None = None
