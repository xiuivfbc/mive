import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from src.api.deps import get_current_user, get_message_service
from src.db.models import M9User
from src.llm.base import user_language
from src.models.message import SendMessageRequest
from src.services.message_service import MessageService

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/worlds/{world_id}/messages", tags=["messages"])


def _validate_world_id(world_id: str) -> None:
    """Issue 17: validate world_id is a valid UUID."""
    try:
        uuid.UUID(world_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的世界 ID") from None


@router.get("")
async def get_messages(
    world_id: str,
    before_sequence: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    sender_id: str | None = Query(None),
    type: str | None = Query(None),
    session_id: str | None = Query(None),
    service: MessageService = Depends(get_message_service),
):
    """获取消息历史（游标分页）"""
    _validate_world_id(world_id)
    result = await service.list_messages(
        world_id,
        before_sequence=before_sequence,
        limit=limit,
        sender_id=sender_id,
        type=type,
        session_id=session_id,
    )
    return result.model_dump(mode="json")


@router.post("")
async def send_message(
    world_id: str,
    req: SendMessageRequest,
    service: MessageService = Depends(get_message_service),
    current_user: M9User = Depends(get_current_user),
):
    """发送用户消息，触发角色回复"""
    _validate_world_id(world_id)
    user_language.set(current_user.preferred_language)

    try:
        result = await service.send_message(
            world_id,
            req.content,
            req.participant_mode,
            req.participants,
            req.session_id,
            memories_enabled=req.memories_enabled,
            action_descriptions=req.action_descriptions,
            element_rerank=req.element_rerank,
            idempotency_key=req.idempotency_key,
            show_narration=req.show_narration,
            user_role=req.user_role,
            element_injection_ids=req.element_injection_ids,
            constraint=req.constraint,
        )
    except HTTPException:
        raise
    except TimeoutError:
        logger.warning("send_message timed out for world %s", world_id)
        raise HTTPException(status_code=504, detail="AI 服务响应超时，请稍后重试") from None
    except ValidationError as e:
        logger.warning("send_message validation error for world %s: %s", world_id, e)
        raise HTTPException(status_code=422, detail="请求参数无效") from e
    except RuntimeError as e:
        logger.warning("send_message runtime error for world %s: %s", world_id, e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception:
        logger.exception("send_message failed for world %s", world_id)
        raise HTTPException(status_code=503, detail="AI 服务繁忙，请稍后重试") from None

    return result.model_dump(mode="json")
