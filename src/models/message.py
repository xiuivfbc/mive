from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    id: str
    world_id: str
    type: str  # dialogue / narration / system / user
    sender_type: str  # character / narrator / system / user
    sender_id: str | None = None
    sender_name: str | None = None
    content: str
    real_time: datetime | None = None
    is_key_message: bool = False
    user_participated: bool = False
    created_at: datetime | None = None
    session_id: str | None = None
    sequence: int | None = None
    idempotency_key: str | None = None
    status: str = "normal"

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"dialogue", "narration", "system", "user", "event"}
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}, got '{v}'")
        return v

    @field_validator("sender_type")
    @classmethod
    def validate_sender_type(cls, v: str) -> str:
        allowed = {"character", "narrator", "system", "user"}
        if v not in allowed:
            raise ValueError(f"sender_type must be one of {allowed}, got '{v}'")
        return v


class SendMessageRequest(BaseModel):
    model_config = {"extra": "forbid"}

    content: str = Field(..., min_length=1)
    participant_mode: Literal["auto", "edit", "include"] = "auto"
    participants: list[dict] | None = None
    session_id: str | None = None
    memories_enabled: bool = False
    action_descriptions: bool = False
    show_narration: bool = False  # 是否生成旁白
    element_rerank: bool = False  # AI 元素精排（会话级开关，开启时用副模型打分）
    user_role: str | None = None  # 用户当前扮演的角色 ID
    idempotency_key: str | None = None
    element_injection_ids: list[str] | None = None  # 手动元素注入
    constraint: str | None = None  # 临时约束

    @field_validator("participants")
    @classmethod
    def validate_participants(cls, v: list[dict] | None) -> list[dict] | None:
        """Issue 19: validate participant dicts have required 'id' field."""
        if v is None:
            return v
        for i, p in enumerate(v):
            if not isinstance(p, dict):
                raise ValueError(f"participants[{i}] must be a dict")
            if "id" not in p:
                raise ValueError(f"participants[{i}] is missing required 'id' field")
        return v

    @field_validator("content")
    @classmethod
    def content_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content cannot be whitespace only")
        return v


class SendMessageResponse(BaseModel):
    user_message: Message
    responses: list[Message] = []
    narration: Message | None = None
    error: str | None = None
    session_id: str | None = None
    participants: list[dict] = []
    participant_mode: Literal["auto", "edit", "include"] = "auto"
    memory_flush_triggered: bool = False


class MessageListResponse(BaseModel):
    messages: list[Message]
    has_more: bool
