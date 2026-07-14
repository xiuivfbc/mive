"""Admin config API -- dynamic LLM/embedding configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.deps import get_admin_user
from src.db.models import M9User
from src.db.session import async_session
from src.models.admin_config import AdminConfigGroupResponse, AdminConfigUpdateRequest
from src.services.admin_config_service import AdminConfigService

router = APIRouter(prefix="/api/admin/config", tags=["admin-config"])


@router.get("/{group}", response_model=AdminConfigGroupResponse)
async def get_config_group(
    group: str,
    request: Request,
    admin_user: M9User = Depends(get_admin_user),
):
    """Get all config items for a group (llm, sub_llm, embedding)."""
    async with async_session() as session:
        service = AdminConfigService(session, request)
        try:
            return await service.get_group(group)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/{group}", response_model=AdminConfigGroupResponse)
async def update_config_group(
    group: str,
    body: AdminConfigUpdateRequest,
    request: Request,
    admin_user: M9User = Depends(get_admin_user),
):
    """Update config values for a group. Immediately persisted and hot-reloaded."""
    async with async_session() as session:
        service = AdminConfigService(session, request)
        try:
            return await service.update_group(group, body.values)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{group}", response_model=AdminConfigGroupResponse)
async def reset_config_group(
    group: str,
    request: Request,
    admin_user: M9User = Depends(get_admin_user),
):
    """Reset a group to environment variable defaults."""
    async with async_session() as session:
        service = AdminConfigService(session, request)
        try:
            return await service.reset_group(group)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
