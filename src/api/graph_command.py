import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.db.models import M9User
from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.relation_repo import RelationRepository
from src.db.session import get_session
from src.llm.base import user_language
from src.services.graph_command_service import GraphCommandService
from src.services.snapshot_sync_service import bump_generation_sql, publish_snapshot_dirty

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worlds/{world_id}/graph-command", tags=["graph-command"])


def _get_service(request: Request, session: AsyncSession, llm=None) -> GraphCommandService:
    if llm is None:
        llm = getattr(request.app.state, "llm", None)
    if not llm:
        raise HTTPException(status_code=503, detail="LLM not configured")
    return GraphCommandService(
        llm=llm,
        char_repo=CharacterRepository(session),
        rel_repo=RelationRepository(session),
    )


class CommandRequest(BaseModel):
    command: str


class ApplyRequest(BaseModel):
    operations: list[dict]


@router.post("/parse")
async def parse_command(
    world_id: str,
    body: CommandRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: M9User = Depends(get_current_user),
):
    user_language.set(current_user.preferred_language)
    default_llm = getattr(request.app.state, "llm", None)
    svc = _get_service(request, session, llm=default_llm)
    result = await svc.parse(world_id, body.command)
    return result


@router.post("/apply")
async def apply_command(
    world_id: str,
    body: ApplyRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: M9User = Depends(get_current_user),
):
    user_language.set(current_user.preferred_language)
    default_llm = getattr(request.app.state, "llm", None)
    svc = _get_service(request, session, llm=default_llm)
    result = await svc.apply(world_id, body.operations)
    await bump_generation_sql(world_id, session)
    await session.commit()
    background_tasks.add_task(
        publish_snapshot_dirty, request.app.state.redis, world_id, "graph_command"
    )
    return result
