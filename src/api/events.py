import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.api.deps import (
    get_current_user,
    get_event_dialogue_service,
    get_event_service,
    get_session,
)
from src.db.models import M9User
from src.db.repositories.event_index_repo import EventIndexRepository
from src.llm.base import user_language
from src.models.event import (
    EventDiscardRequest,
    EventMarkRequest,
    EventRewindRequest,
    EventStreamRequest,
    EventTrimRequest,
)
from src.services import stream_control as sc
from src.services.event_dialogue_service import EventDialogueService
from src.services.event_service import EventService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worlds/{world_id}/events", tags=["events"])

_PING = "event: ping\ndata: {}\n\n"


async def _with_heartbeat(
    gen: AsyncGenerator[str, None], interval: int = 30
) -> AsyncGenerator[str, None]:
    """在 SSE 生成器外层注入心跳，防止 Cloudflare 100s 空闲超时断连。"""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _produce() -> None:
        try:
            async for chunk in gen:
                await queue.put(chunk)
        finally:
            await queue.put(None)

    async def _ping() -> None:
        while True:
            await asyncio.sleep(interval)
            await queue.put(_PING)

    producer = asyncio.create_task(_produce())
    pinger = asyncio.create_task(_ping())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        pinger.cancel()
        producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer


@router.get("")
async def list_events(
    world_id: str,
    from_time: datetime | None = Query(None),
    to_time: datetime | None = Query(None),
    status: str | None = Query(None),
    event_type: str | None = Query(None),
    service: EventService = Depends(get_event_service),
):
    """获取事件列表"""
    events = await service.list_events(
        world_id,
        from_time=from_time,
        to_time=to_time,
        status=status,
        event_type=event_type,
    )
    return [e.model_dump(mode="json") for e in events]


@router.put("/{event_id}/mark")
async def mark_key_event(
    world_id: str,
    event_id: str,
    req: EventMarkRequest,
    service: EventService = Depends(get_event_service),
):
    """标记/取消关键事件"""
    event = await service.mark_key_event(event_id, req.is_key_event)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event.model_dump(mode="json")


@router.delete("/{event_id}")
async def cancel_event(
    world_id: str,
    event_id: str,
    service: EventService = Depends(get_event_service),
):
    """取消事件（status → cancelled）"""
    try:
        event = await service.cancel_event(event_id)
        return event.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/stream")
async def stream_event_dialogue(
    world_id: str,
    req: EventStreamRequest,
    request: Request,
    service: EventDialogueService = Depends(get_event_dialogue_service),
    current_user: M9User = Depends(get_current_user),
):
    """事件注入 + 角色对话 SSE 流"""
    user_language.set(current_user.preferred_language)

    async def generate():
        try:
            async for chunk in service.stream_dialogue(
                world_id,
                req.raw_input,
                request,
                session_id=req.session_id,
                memories_enabled=req.memories_enabled,
                action_descriptions=req.action_descriptions,
                show_narration=req.show_narration,
                element_rerank=req.element_rerank,
                element_injection_ids=req.element_injection_ids,
                constraint=req.constraint,
            ):
                yield chunk
        except Exception:
            logger.exception("stream_dialogue failed for world %s", world_id)
            yield 'event: error\ndata: {"message": "AI 服务繁忙，请稍后重试"}\n\n'

    return StreamingResponse(
        _with_heartbeat(generate()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/stream/pause")
async def pause_stream(world_id: str):
    ctrl = sc.get_control(world_id)
    if ctrl:
        ctrl.pause()
    return {"ok": True}


@router.post("/stream/resume")
async def resume_stream(world_id: str):
    ctrl = sc.get_control(world_id)
    if ctrl:
        ctrl.resume()
    return {"ok": True}


@router.post("/stream/stop")
async def stop_stream(world_id: str):
    ctrl = sc.get_control(world_id)
    if ctrl:
        ctrl.stop()
    return {"ok": True}


@router.post("/stream/trim")
async def trim_stream_messages(
    world_id: str,
    req: EventTrimRequest,
    service: EventDialogueService = Depends(get_event_dialogue_service),
):
    """丢弃缓冲区中未显示的消息（前端中断后用户未选择继续时调用）"""
    if req.message_ids:
        await service.message_repo.delete_by_ids(req.message_ids)
        await service.event_repo.session.commit()
    return {"ok": True}


@router.post("/stream/rewind")
async def rewind_stream(
    world_id: str,
    req: EventRewindRequest,
    service: EventDialogueService = Depends(get_event_dialogue_service),
):
    try:
        result = await service.rewind_to_event(world_id, req.card_message_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{event_id}/discard")
async def discard_event(
    world_id: str,
    event_id: str,
    req: EventDiscardRequest,
    service: EventDialogueService = Depends(get_event_dialogue_service),
):
    """废弃事件：删除本次产生的消息，将事件标记为 cancelled"""
    await service.discard_event(event_id, req.message_ids)
    return {"ok": True}


@router.get("/event-index")
async def list_event_index(
    world_id: str,
    session=Depends(get_session),
):
    """获取世界事件索引列表"""
    repo = EventIndexRepository(session)
    events = await repo.list_by_world(world_id)
    return [
        {
            "id": str(e.id),
            "event_name": e.event_name,
            "brief": e.brief,
            "dissemination": e.dissemination,
            "core_participants": [str(p) for p in e.core_participants]
            if e.core_participants
            else [],
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
