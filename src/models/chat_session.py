from datetime import datetime

from pydantic import BaseModel


class ChatSession(BaseModel):
    id: str
    world_id: str
    type: str  # event | character
    title: str | None
    created_at: datetime
    participants: list[dict] | list[str] | None = None  # UUID array or legacy dict array
    participant_mode: str | None = None
    memories_enabled: bool = False
    version_id: str | None = None
    last_flushed_sequence: int = 0
    last_active_at: datetime | None = None
    element_injection_ids: list[str] | None = None
    constraints: str = ""


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSession]
