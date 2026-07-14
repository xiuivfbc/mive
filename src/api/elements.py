from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (
    build_element_retrieval_from_session,
    get_element_retrieval_service,
    get_session,
    get_world_service,
)
from src.models.world import UpdateElementRequest
from src.services.snapshot_sync_service import bump_generation_sql, publish_snapshot_dirty
from src.services.world_service import WorldService

if TYPE_CHECKING:
    from src.llm.embedding_provider import EmbeddingProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worlds", tags=["elements"])


class AddElementRequest(BaseModel):
    category: str
    name: str
    brief: str
    detail: str


async def _rebuild_single_embedding(
    provider: EmbeddingProvider,
    world_id: str,
    element_id: str,
    element_type: str,
    name: str,
    search_text: str,
    category: str | None = None,
    tier: str | None = None,
) -> None:
    """Background task: create a fresh session for embedding update."""
    try:
        from src.db.session import async_session as _session_factory

        async with _session_factory() as session:
            svc = build_element_retrieval_from_session(session, provider)
            assert svc is not None
            await svc.update_single_embedding(
                world_id=world_id,
                element_id=element_id,
                element_type=element_type,
                name=name,
                search_text=search_text,
                category=category,
                tier=tier,
            )
            await session.commit()
    except Exception:
        logger.warning(
            "element embedding update failed (non-fatal) elem=%s world=%s",
            element_id,
            world_id,
        )


async def _delete_single_embedding(
    provider: EmbeddingProvider, world_id: str, element_id: str
) -> None:
    """Background task: create a fresh session for embedding deletion."""
    try:
        from src.db.repositories.embedding_repo import EmbeddingRepository
        from src.db.session import async_session as _session_factory

        async with _session_factory() as session:
            repo = EmbeddingRepository(session)
            await repo.delete_by_element_id(world_id, element_id)
            await session.commit()
    except Exception:
        logger.warning(
            "element embedding delete failed (non-fatal) elem=%s world=%s",
            element_id,
            world_id,
        )


@router.post("/{world_id}/elements", status_code=201)
async def add_element(
    world_id: str,
    req: AddElementRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    world_service: WorldService = Depends(get_world_service),
    retrieval_service=Depends(get_element_retrieval_service),
    session: AsyncSession = Depends(get_session),
):
    result = await world_service.add_element(
        world_id, category=req.category, name=req.name, brief=req.brief, detail=req.detail
    )
    if result is None:
        raise HTTPException(status_code=404, detail="World not found")

    await bump_generation_sql(world_id, session)
    background_tasks.add_task(publish_snapshot_dirty, request.app.state.redis, world_id, "element")

    # Trigger single embedding creation (non-blocking, fresh session)
    if retrieval_service:
        search_text = f"{result.name}\n{result.brief}\n{result.detail}"
        provider = getattr(request.app.state, "embedding_provider", None)
        if provider:
            background_tasks.add_task(
                _rebuild_single_embedding,
                provider,
                world_id,
                result.id,
                "element",
                result.name,
                search_text,
                result.category,
            )

    return result


@router.put("/{world_id}/elements/{element_id}")
async def update_element(
    world_id: str,
    element_id: str,
    req: UpdateElementRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    world_service: WorldService = Depends(get_world_service),
    retrieval_service=Depends(get_element_retrieval_service),
    session: AsyncSession = Depends(get_session),
):
    result = await world_service.update_element(
        world_id,
        element_id,
        brief=req.brief,
        detail=req.detail,
        name=req.name,
        category=req.category,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Element not found")

    await bump_generation_sql(world_id, session)
    background_tasks.add_task(publish_snapshot_dirty, request.app.state.redis, world_id, "element")

    # Trigger single embedding update (non-blocking, fresh session)
    if retrieval_service:
        search_text = f"{result.name}\n{result.brief}\n{result.detail}"
        provider = getattr(request.app.state, "embedding_provider", None)
        if provider:
            background_tasks.add_task(
                _rebuild_single_embedding,
                provider,
                world_id,
                element_id,
                "element",
                result.name,
                search_text,
                result.category,
            )

    return result


@router.delete("/{world_id}/elements/{element_id}")
async def delete_element(
    world_id: str,
    element_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    world_service: WorldService = Depends(get_world_service),
    retrieval_service=Depends(get_element_retrieval_service),
    session: AsyncSession = Depends(get_session),
):
    deleted = await world_service.delete_element(world_id, element_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Element not found")

    await bump_generation_sql(world_id, session)
    background_tasks.add_task(publish_snapshot_dirty, request.app.state.redis, world_id, "element")

    # Delete the embedding for this element (non-blocking, fresh session)
    if retrieval_service:
        provider = getattr(request.app.state, "embedding_provider", None)
        if provider:
            background_tasks.add_task(_delete_single_embedding, provider, world_id, element_id)

    return {"deleted": True}
