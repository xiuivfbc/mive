from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import EventStatus, EventType


class Event(BaseModel):
    id: str
    world_id: str
    event_type: str = EventType.USER_INJECTED
    name: str | None = None
    description: str | None = None
    priority: str = "medium"
    status: str = EventStatus.SCHEDULED
    is_key_event: bool = False
    user_marked: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    executed_at: datetime | None = None


class EventMarkRequest(BaseModel):
    is_key_event: bool


class EventStreamRequest(BaseModel):
    raw_input: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    memories_enabled: bool = False
    action_descriptions: bool = False
    show_narration: bool = False
    element_rerank: bool = False
    element_injection_ids: list[str] | None = None  # 手动元素注入
    constraint: str | None = None  # 临时约束


class EventDiscardRequest(BaseModel):
    message_ids: list[str]


class EventRewindRequest(BaseModel):
    card_message_id: str


class EventTrimRequest(BaseModel):
    message_ids: list[str]
