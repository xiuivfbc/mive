"""Pydantic models for admin config API."""

from __future__ import annotations

from pydantic import BaseModel


class AdminConfigItem(BaseModel):
    key: str
    value: str
    source: str  # "override" | "env_default"


class AdminConfigGroupResponse(BaseModel):
    group: str
    items: list[AdminConfigItem]


class AdminConfigUpdateRequest(BaseModel):
    values: dict[str, str]  # key -> value
