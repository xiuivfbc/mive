"""Admin endpoints for embedding management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.deps import build_element_retrieval_from_session, get_admin_user
from src.db.models import M1World, M9User
from src.db.session import async_session as _async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RebuildEmbeddingsResponse(BaseModel):
    status: str
    message: str


def _build_retrieval_service(request: Request, session):
    """Build ElementRetrievalService with embedding provider from app.state."""
    embedding_provider = getattr(request.app.state, "embedding_provider", None)
    return build_element_retrieval_from_session(session, embedding_provider)


@router.post("/worlds/{world_id}/rebuild-embeddings", response_model=RebuildEmbeddingsResponse)
async def rebuild_embeddings(
    world_id: str,
    request: Request,
    admin_user: M9User = Depends(get_admin_user),
):
    """Manually rebuild embeddings for a single world."""
    async with _async_session_factory() as session:
        retrieval_service = _build_retrieval_service(request, session)
        if retrieval_service is None:
            raise HTTPException(status_code=503, detail="Embedding provider not configured")

        ok = await retrieval_service.rebuild_embeddings(world_id)
        await session.commit()

    if ok:
        return RebuildEmbeddingsResponse(
            status="ok", message=f"Embeddings rebuilt for world {world_id}"
        )
    return RebuildEmbeddingsResponse(
        status="error", message=f"Embeddings rebuild failed for world {world_id}"
    )


@router.post("/rebuild-all-embeddings", response_model=RebuildEmbeddingsResponse)
async def rebuild_all_embeddings(
    request: Request,
    admin_user: M9User = Depends(get_admin_user),
):
    """Rebuild embeddings for all active worlds."""
    # Get all active worlds
    async with _async_session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(M1World.id).where(M1World.status == "active"))
        world_ids = [str(row[0]) for row in result.all()]

    logger.info("[admin] rebuild-all-embeddings: found %d active worlds", len(world_ids))

    succeeded = 0
    failed = 0
    for wid in world_ids:
        try:
            async with _async_session_factory() as session:
                retrieval_service = _build_retrieval_service(request, session)
                if retrieval_service is None:
                    raise HTTPException(status_code=503, detail="Embedding provider not configured")
                ok = await retrieval_service.rebuild_embeddings(wid)
                await session.commit()
                if ok:
                    succeeded += 1
                else:
                    failed += 1
                    logger.warning("[admin] rebuild-all-embeddings failed for world=%s", wid)
        except Exception:
            failed += 1
            logger.warning("[admin] rebuild-all-embeddings failed for world=%s", wid, exc_info=True)

    msg = (
        f"Rebuilt embeddings: {succeeded} succeeded, {failed} failed out of {len(world_ids)} worlds"
    )
    return RebuildEmbeddingsResponse(status="ok", message=msg)
