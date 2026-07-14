from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_chat_session_service
from src.services.chat_session_service import ChatSessionService

router = APIRouter(prefix="/api/worlds/{world_id}/chat-sessions", tags=["chat-sessions"])


@router.get("")
async def list_chat_sessions(
    world_id: str,
    service: ChatSessionService = Depends(get_chat_session_service),
):
    result = await service.list_sessions(world_id)
    return result.model_dump(mode="json")


@router.get("/{session_id}/messages")
async def get_session_messages(
    world_id: str,
    session_id: str,
    service: ChatSessionService = Depends(get_chat_session_service),
):
    messages = await service.get_session_messages(session_id)
    return {"messages": [m.model_dump(mode="json") for m in messages]}


@router.delete("/{session_id}")
async def delete_chat_session(
    world_id: str,
    session_id: str,
    service: ChatSessionService = Depends(get_chat_session_service),
):
    deleted = await service.delete_session(world_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}
