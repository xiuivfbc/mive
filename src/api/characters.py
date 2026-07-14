from __future__ import annotations

import base64
import logging
from copy import copy
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.conditional_cache import check_not_modified, set_cache_headers
from src.api.deps import (
    build_element_retrieval_from_session,
    get_character_service,
    get_element_retrieval_service,
    get_generation_service,
    get_relation_service,
    get_session,
    get_world_service,
)
from src.models.character import Character, CreateCharacterRequest, UpdateCharacterRequest
from src.models.scale import DEFAULT_SCALE
from src.services.character_service import CharacterService
from src.services.generation_service import GenerationService
from src.services.relation_service import RelationService
from src.services.snapshot_sync_service import bump_generation_sql, publish_snapshot_dirty
from src.services.world_service import WorldService

if TYPE_CHECKING:
    from src.llm.embedding_provider import EmbeddingProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worlds/{world_id}/characters", tags=["characters"])


async def _update_character_embedding(
    provider: EmbeddingProvider,
    world_id: str,
    character_id: str,
    name: str,
    search_text: str,
    tier: str | None = None,
) -> None:
    """Background task: create a fresh session for embedding update."""
    try:
        from src.db.session import async_session as _session_factory

        async with _session_factory() as session:
            svc = build_element_retrieval_from_session(session, provider)
            await svc.update_single_embedding(
                world_id=world_id,
                element_id=f"char_{character_id}",
                element_type="character",
                name=name,
                search_text=search_text,
                tier=tier,
            )
            await session.commit()
    except Exception:
        logger.warning(
            "character embedding update failed (non-fatal) char=%s world=%s",
            character_id,
            world_id,
        )


async def _delete_character_embedding(
    provider: EmbeddingProvider, world_id: str, character_id: str
) -> None:
    """Background task: create a fresh session for embedding deletion."""
    try:
        from src.db.repositories.embedding_repo import EmbeddingRepository
        from src.db.session import async_session as _session_factory

        async with _session_factory() as session:
            repo = EmbeddingRepository(session)
            await repo.delete_by_element_id(world_id, f"char_{character_id}")
            await session.commit()
    except Exception:
        logger.warning(
            "character embedding delete failed (non-fatal) char=%s world=%s",
            character_id,
            world_id,
        )


@router.post("", status_code=201, response_model=Character)
async def create_character(
    world_id: str,
    req: CreateCharacterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: CharacterService = Depends(get_character_service),
    session: AsyncSession = Depends(get_session),
):
    result = await service.create(world_id, req)
    await bump_generation_sql(world_id, session)
    background_tasks.add_task(
        publish_snapshot_dirty, request.app.state.redis, world_id, "character"
    )
    return result


@router.get("", response_model=list[Character])
async def list_characters(
    world_id: str,
    request: Request,
    response: Response,
    service: CharacterService = Depends(get_character_service),
):
    last_mod = await service.max_updated_at(world_id)
    not_mod = check_not_modified(request, last_mod)
    if not_mod:
        return not_mod
    if last_mod:
        set_cache_headers(response, last_mod, public=True)
    characters = await service.list_by_world(world_id)
    redact_portrait_urls(characters)
    return characters


def redact_portrait_urls(characters: list) -> None:
    """Replace inline Base64 portrait URLs with /avatar endpoint paths."""
    for i, char in enumerate(characters):
        portrait = getattr(char, "portrait_url", None) or (
            char.get("portrait_url") if isinstance(char, dict) else None
        )
        if portrait and portrait.startswith("data:image"):
            cid = getattr(char, "id", None) or char.get("id") if isinstance(char, dict) else None
            if cid:
                if isinstance(char, dict):
                    char = dict(char)
                    char["portrait_url"] = f"/api/characters/{cid}/avatar"
                else:
                    char = copy(char)
                    char.portrait_url = f"/api/characters/{cid}/avatar"
                characters[i] = char


@router.post("/generate", status_code=201)
async def generate_characters(
    world_id: str,
    scale: str = Query(DEFAULT_SCALE),
    service: GenerationService = Depends(get_generation_service),
):
    try:
        return await service.generate(world_id, scale=scale)
    except ValueError as e:
        if "World not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e)) from e
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{character_id}", response_model=Character)
async def get_character(
    world_id: str,
    character_id: str,
    service: CharacterService = Depends(get_character_service),
):
    result = await service.get(character_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return result


@router.put("/{character_id}", response_model=Character)
async def update_character(
    world_id: str,
    character_id: str,
    req: UpdateCharacterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: CharacterService = Depends(get_character_service),
    retrieval_service=Depends(get_element_retrieval_service),
    world_service: WorldService = Depends(get_world_service),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service.update(character_id, req, fields_set=req.model_fields_set)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if result is None:
        raise HTTPException(status_code=404, detail="Character not found")

    await bump_generation_sql(world_id, session)
    background_tasks.add_task(
        publish_snapshot_dirty, request.app.state.redis, world_id, "character"
    )

    # Trigger single embedding update (non-blocking, fresh session)
    # Skip if this is the user character (user characters don't get embeddings)
    if retrieval_service:
        try:
            world = await world_service.get_world(world_id)
            is_user_char = world and str(world.user_character_id) == character_id
            if not is_user_char:
                profile = result.profile or {}
                search_text = (
                    f"{result.name}\n{profile.get('brief', '')}\n{profile.get('detail', '')}"
                )
                provider = getattr(request.app.state, "embedding_provider", None)
                if provider:
                    background_tasks.add_task(
                        _update_character_embedding,
                        provider,
                        world_id,
                        character_id,
                        result.name,
                        search_text,
                        result.tier,
                    )
        except Exception:
            logger.warning("character embedding check failed (non-fatal) char=%s", character_id)

    return result


@router.get("/{character_id}/avatar")
async def get_character_avatar(
    world_id: str,
    character_id: str,
    service: CharacterService = Depends(get_character_service),
):
    """Return the character's portrait as a binary image (decoded from Base64 storage)."""
    character = await service.get(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    if not character.portrait_url:
        raise HTTPException(status_code=404, detail="No avatar")

    portrait = character.portrait_url
    if portrait.startswith("data:"):
        # format: data:image/png;base64,<data>
        header, _, b64data = portrait.partition(",")
        media_type = header.split(";")[0].split(":")[1]
        image_bytes = base64.b64decode(b64data)
    else:
        raise HTTPException(status_code=404, detail="Avatar not in Base64 format")

    return Response(content=image_bytes, media_type=media_type)


@router.delete("/{character_id}")
async def delete_character(
    world_id: str,
    character_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    service: CharacterService = Depends(get_character_service),
    relation_service: RelationService = Depends(get_relation_service),
    retrieval_service=Depends(get_element_retrieval_service),
    session: AsyncSession = Depends(get_session),
):
    try:
        # 先删除该角色的所有关系，再删除角色本身（与 GraphCommandService 一致）
        await relation_service.delete_by_character(character_id)
        deleted = await service.delete(character_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail="Character not found")

    await bump_generation_sql(world_id, session)
    background_tasks.add_task(
        publish_snapshot_dirty, request.app.state.redis, world_id, "character"
    )

    # Clean up embedding for deleted character (non-blocking)
    if retrieval_service:
        provider = getattr(request.app.state, "embedding_provider", None)
        if provider:
            background_tasks.add_task(_delete_character_embedding, provider, world_id, character_id)

    return {"deleted": True}
