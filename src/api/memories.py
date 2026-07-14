from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_message_service, get_session
from src.db.models import M9User
from src.db.repositories.character_memory_repo import _UNSET, CharacterMemoryRepository
from src.db.repositories.world_repo import WorldRepository
from src.services.message_service import MessageService

router = APIRouter(tags=["memories"])


def _serialize_memory(m):
    base = {
        "id": str(m.id),
        "content": m.content,
        "session_id": str(m.session_id) if m.session_id else None,
        "created_at": m.created_at.isoformat(),
    }
    memory_type = getattr(m, "memory_type", None)
    base["memory_type"] = memory_type
    if memory_type == "short_term":
        base["memory_category"] = getattr(m, "memory_category", None)
        base["short_term_reflection"] = getattr(m, "short_term_reflection", None)
    elif memory_type == "long_term":
        base["perspective_detail"] = getattr(m, "perspective_detail", None)
        base["reflection"] = getattr(m, "reflection", None)
        base["event_name"] = getattr(m, "event_name", None)
        raw_chars = getattr(m, "involved_characters", None)
        base["involved_characters"] = [str(c) for c in raw_chars] if raw_chars else None
        raw_prop = getattr(m, "propagated_from", None)
        base["propagated_from"] = str(raw_prop) if raw_prop else None
        base["is_hearsay"] = getattr(m, "is_hearsay", False)
    return base


class CreateMemoryRequest(BaseModel):
    memory_type: str  # "short_term" or "long_term"
    content: str
    # short-term only
    memory_category: str | None = None  # "trivial"/"private"/"major"
    short_term_reflection: str | None = None
    # long-term only
    perspective_detail: str | None = None
    reflection: str | None = None
    event_name: str | None = None
    involved_characters: list[str] | None = None  # list of character UUID strings


class UpdateMemoryRequest(BaseModel):
    content: str | None = None
    memory_category: str | None = None
    short_term_reflection: str | None = None
    perspective_detail: str | None = None
    reflection: str | None = None
    event_name: str | None = None
    involved_characters: list[str] | None = None  # list of character UUID strings


@router.get("/api/worlds/{world_id}/characters/{character_id}/memories")
async def get_character_memories(
    world_id: str,
    character_id: str,
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    world_repo = WorldRepository(session)
    world = await world_repo.get_by_id(world_id)
    if not world or str(world.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="World not found")

    repo = CharacterMemoryRepository(session)
    char_id = UUID(character_id)
    short = await repo.list_short_term(char_id, limit=100)
    long = await repo.list_long_term(char_id)

    return {
        "short_term": [_serialize_memory(m) for m in reversed(short)],
        "long_term": [_serialize_memory(m) for m in long],
    }


@router.post("/api/worlds/{world_id}/characters/{character_id}/memories")
async def create_character_memory(
    world_id: str,
    character_id: str,
    body: CreateMemoryRequest,
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    world_repo = WorldRepository(session)
    world = await world_repo.get_by_id(world_id)
    if not world or str(world.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="World not found")

    if body.memory_type not in ("short_term", "long_term"):
        raise HTTPException(
            status_code=400, detail="memory_type must be 'short_term' or 'long_term'"
        )

    repo = CharacterMemoryRepository(session)
    char_id = UUID(character_id)
    world_uuid = UUID(world_id)

    if body.memory_type == "short_term":
        mem = await repo.add(
            character_id=char_id,
            world_id=world_uuid,
            session_id=None,
            memory_type="short_term",
            content=body.content,
            memory_category=body.memory_category,
            short_term_reflection=body.short_term_reflection,
        )
    else:
        try:
            involved = (
                [UUID(c) for c in body.involved_characters] if body.involved_characters else None
            )
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid UUID in involved_characters"
            ) from None
        mem = await repo.add_structured_long_term(
            character_id=char_id,
            world_id=world_uuid,
            event_name=body.event_name or "",
            perspective_detail=body.perspective_detail or "",
            reflection=body.reflection,
            involved_characters=involved or None,
        )

    await session.commit()

    return _serialize_memory(mem)


@router.patch("/api/worlds/{world_id}/characters/{character_id}/memories/{memory_id}")
async def update_character_memory(
    world_id: str,
    character_id: str,
    memory_id: str,
    body: UpdateMemoryRequest,
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    world_repo = WorldRepository(session)
    world = await world_repo.get_by_id(world_id)
    if not world or str(world.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="World not found")

    repo = CharacterMemoryRepository(session)
    mem = await repo.get_by_id(UUID(memory_id))
    if not mem or str(mem.character_id) != character_id:
        raise HTTPException(status_code=404, detail="Memory not found")

    involved: list[UUID] | object = _UNSET
    if body.involved_characters is not None:
        try:
            involved = [UUID(c) for c in body.involved_characters]
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid UUID in involved_characters"
            ) from None
    updated = await repo.update_memory(
        memory_id=UUID(memory_id),
        content=body.content,
        memory_category=body.memory_category,
        short_term_reflection=body.short_term_reflection,
        perspective_detail=body.perspective_detail,
        reflection=body.reflection,
        event_name=body.event_name,
        involved_characters=involved,
    )
    await session.commit()

    return _serialize_memory(updated)


@router.delete("/api/worlds/{world_id}/characters/{character_id}/memories/{memory_id}")
async def delete_character_memory(
    world_id: str,
    character_id: str,
    memory_id: str,
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    world_repo = WorldRepository(session)
    world = await world_repo.get_by_id(world_id)
    if not world or str(world.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="World not found")

    repo = CharacterMemoryRepository(session)
    mem = await repo.get_by_id(UUID(memory_id))
    if not mem or str(mem.character_id) != character_id:
        raise HTTPException(status_code=404, detail="Memory not found")
    await repo.delete_by_ids([mem.id])
    await session.commit()
    return {"ok": True}


@router.delete("/api/worlds/{world_id}/sessions/{session_id}/memories")
async def delete_session_memories(
    world_id: str,
    session_id: str,
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    world_repo = WorldRepository(session)
    world = await world_repo.get_by_id(world_id)
    if not world or str(world.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="World not found")

    repo = CharacterMemoryRepository(session)
    await repo.delete_by_session(UUID(session_id))
    await session.commit()
    return {"ok": True}


@router.post("/api/worlds/{world_id}/sessions/{session_id}/flush-memories")
async def flush_session_memories(
    world_id: str,
    session_id: str,
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    message_service: MessageService = Depends(get_message_service),
):
    world_repo = WorldRepository(session)
    world = await world_repo.get_by_id(world_id)
    if not world or str(world.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="World not found")

    result = await message_service.flush_chat_memories(world_id, session_id)
    return result
