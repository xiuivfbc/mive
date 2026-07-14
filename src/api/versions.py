import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import build_element_retrieval_from_session, get_session, get_version_service
from src.models.proposal import UpdateVersionRequest, WorldVersion
from src.services.snapshot_sync_service import publish_snapshot_dirty
from src.services.version_service import VersionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worlds/{world_id}/versions", tags=["versions"])


@router.get("", response_model=list[WorldVersion])
async def list_versions(
    world_id: str,
    service: VersionService = Depends(get_version_service),
):
    return await service.list_by_world(world_id)


@router.post("/{version_id}/rollback", status_code=201, response_model=WorldVersion)
async def rollback_version(
    world_id: str,
    version_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    service: VersionService = Depends(get_version_service),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service.rollback(version_id, world_id)
        # 显式 commit，使 bump_generation_sql 生效，然后发布 dirty 通知
        await session.commit()
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            background_tasks.add_task(publish_snapshot_dirty, redis, world_id, "version")

        # Trigger embedding rebuild after rollback
        embedding_provider = getattr(request.app.state, "embedding_provider", None)
        if embedding_provider:
            import src.db.session as _db_session_mod

            async def _rebuild_after_rollback():
                try:
                    async with _db_session_mod.async_session() as emb_session:
                        retrieval_svc = build_element_retrieval_from_session(
                            emb_session, embedding_provider
                        )
                        assert retrieval_svc is not None
                        await retrieval_svc.delete_by_world(world_id)
                        await retrieval_svc.rebuild_embeddings(world_id)
                        await emb_session.commit()
                except Exception:
                    logger.warning(
                        "rollback embedding rebuild failed (non-fatal) world=%s",
                        world_id,
                        exc_info=True,
                    )

            background_tasks.add_task(_rebuild_after_rollback)

        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch("/{version_id}", response_model=WorldVersion)
async def update_version(
    world_id: str,
    version_id: str,
    payload: UpdateVersionRequest,
    service: VersionService = Depends(get_version_service),
):
    try:
        return await service.update_summary(version_id, payload.summary)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{version_id}")
async def delete_version(
    world_id: str,
    version_id: str,
    service: VersionService = Depends(get_version_service),
):
    try:
        await service.delete_version(version_id, world_id)
        return {"deleted": True}
    except ValueError as e:
        if "current version" in str(e).lower():
            raise HTTPException(status_code=409, detail=str(e)) from e
        raise HTTPException(status_code=404, detail=str(e)) from e
