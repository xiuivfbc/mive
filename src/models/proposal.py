from datetime import datetime

from pydantic import BaseModel, Field


class WorldVersion(BaseModel):
    id: str
    world_id: str
    parent_version_id: str | None = None
    created_by: str | None = None
    summary: str | None = None
    snapshot: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class UpdateVersionRequest(BaseModel):
    summary: str | None = None
