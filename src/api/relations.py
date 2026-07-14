from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_relation_service
from src.db.session import get_session
from src.models.relation import CreateRelationRequest, Relation, UpdateRelationRequest
from src.services.relation_service import RelationService
from src.services.snapshot_sync_service import bump_generation_sql, publish_snapshot_dirty

router = APIRouter(prefix="/api/worlds/{world_id}/relations", tags=["relations"])


@router.post("", status_code=201, response_model=Relation)
async def create_relation(
    world_id: str,
    req: CreateRelationRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: RelationService = Depends(get_relation_service),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service.create(world_id, req)
        await bump_generation_sql(world_id, session)
        background_tasks.add_task(
            publish_snapshot_dirty, request.app.state.redis, world_id, "relation"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("", response_model=list[Relation])
async def list_relations(
    world_id: str,
    character_id: str | None = None,
    service: RelationService = Depends(get_relation_service),
):
    return await service.list_by_world(world_id, character_id)


@router.get("/{relation_id}", response_model=Relation)
async def get_relation(
    world_id: str,
    relation_id: str,
    service: RelationService = Depends(get_relation_service),
):
    result = await service.get(relation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Relation not found")
    return result


@router.put("/{relation_id}", response_model=Relation)
async def update_relation(
    world_id: str,
    relation_id: str,
    req: UpdateRelationRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: RelationService = Depends(get_relation_service),
    session: AsyncSession = Depends(get_session),
):
    result = await service.update(relation_id, req)
    if result is None:
        raise HTTPException(status_code=404, detail="Relation not found")
    await bump_generation_sql(world_id, session)
    background_tasks.add_task(publish_snapshot_dirty, request.app.state.redis, world_id, "relation")
    return result


@router.delete("/{relation_id}")
async def delete_relation(
    world_id: str,
    relation_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    service: RelationService = Depends(get_relation_service),
    session: AsyncSession = Depends(get_session),
):
    deleted = await service.delete(relation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Relation not found")
    await bump_generation_sql(world_id, session)
    background_tasks.add_task(publish_snapshot_dirty, request.app.state.redis, world_id, "relation")
    return {"deleted": True}
