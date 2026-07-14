from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import RelationStatus


class Relation(BaseModel):
    id: str
    world_id: str
    character_a: str
    character_b: str
    type: str | None = None
    direction: str = "bidirectional"
    description: str | None = None
    status: str = RelationStatus.ACTIVE
    historical_changes: list[dict] | None = None
    graph_edge_uuid: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class CreateRelationRequest(BaseModel):
    character_a: str = Field(min_length=1)
    character_b: str = Field(min_length=1)
    type: str | None = None
    direction: str = "bidirectional"
    description: str | None = None


class UpdateRelationRequest(BaseModel):
    type: str | None = None
    direction: str | None = None
    description: str | None = None
    status: str | None = None
