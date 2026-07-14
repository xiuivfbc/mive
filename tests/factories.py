"""Shared test factories for building domain objects with sensible defaults."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from src.models.character import Character
from src.models.event import Event
from src.models.message import Message
from src.models.proposal import WorldVersion
from src.models.relation import Relation


def make_id() -> str:
    return str(uuid.uuid4())


def make_character(
    name: str = "叶文洁",
    world_id: str = "w-001",
    char_id: str | None = None,
    profile: dict | None = None,
    **kwargs,
) -> Character:
    return Character(
        id=char_id or make_id(),
        world_id=world_id,
        name=name,
        portrait_url=kwargs.get("portrait_url"),
        profile=profile or {"basic": {"name": name}, "brief": "", "detail": ""},
        created_at=kwargs.get("created_at", datetime.now(UTC)),
        updated_at=kwargs.get("updated_at", datetime.now(UTC)),
    )


def make_message(
    content: str = "回复消息",
    world_id: str = "w-001",
    msg_type: str = "dialogue",
    sender_type: str = "character",
    sender_id: str | None = None,
    virtual_time: datetime | None = None,  # noqa: ARG001  # kept for backward compat; Message no longer has virtual_time
    **kwargs,
) -> Message:
    return Message(
        id=kwargs.get("msg_id", make_id()),
        world_id=world_id,
        type=msg_type,
        sender_type=sender_type,
        sender_id=sender_id or make_id(),
        content=content,
        user_participated=kwargs.get("user_participated", False),
    )


def make_event(
    world_id: str = "w-001",
    name: str = "测试事件",
    event_id: str | None = None,
    status: str = "scheduled",
    priority: str = "medium",
    **kwargs,
) -> Event:
    return Event(
        id=event_id or make_id(),
        world_id=world_id,
        event_type=kwargs.get("event_type", "user_injected"),
        name=name,
        description=kwargs.get("description", ""),
        priority=priority,
        status=status,
        is_key_event=kwargs.get("is_key_event", False),
        user_marked=kwargs.get("user_marked", False),
        created_at=kwargs.get("created_at", datetime.now(UTC)),
        executed_at=kwargs.get("executed_at"),
    )


def make_version(
    ver_id: str | None = None,
    world_id: str = "w-001",
    parent_id: str | None = None,
    snapshot: dict | None = None,
    **kwargs,
) -> WorldVersion:
    return WorldVersion(
        id=ver_id or make_id(),
        world_id=world_id,
        parent_version_id=parent_id,
        created_by=kwargs.get("created_by", "user"),
        summary=kwargs.get("summary", "测试版本"),
        snapshot=snapshot or {"characters": [], "relations": []},
        created_at=kwargs.get("created_at", datetime.now(UTC)),
    )


def make_relation(
    world_id: str = "w-001",
    character_a: str = "c-001",
    character_b: str = "c-002",
    rel_type: str = "同事",
    **kwargs,
) -> Relation:
    return Relation(
        id=kwargs.get("rel_id", make_id()),
        world_id=world_id,
        character_a=character_a,
        character_b=character_b,
        type=rel_type,
        status=kwargs.get("status", "active"),
        metadata=kwargs.get("metadata"),
        created_at=kwargs.get("created_at", datetime.now(UTC)),
        updated_at=kwargs.get("updated_at", datetime.now(UTC)),
    )


def make_impact(
    character_name: str = "叶文洁",
    character_id: str = "c-001",
    impact_type: str = "emotional",
    severity: str = "medium",
    reason: str = "测试影响",
) -> SimpleNamespace:
    """Build an impact object (as SimpleNamespace for .attribute access)."""
    return SimpleNamespace(
        character_name=character_name,
        character_id=character_id,
        impact_type=impact_type,
        severity=severity,
        reason=reason,
    )
