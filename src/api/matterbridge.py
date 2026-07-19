"""Matterbridge API routes

Prefix: /api/worlds/{world_id}/matterbridge

Endpoints:
  GET    /          — Get binding status (masked token)
  POST   /          — Create or update binding
  DELETE /          — Delete binding
  POST   /message   — Send a message via Matterbridge
  GET    /messages  — Fetch message history from Matterbridge
  GET    /stream    — SSE stream of inbound Matterbridge messages
  GET    /status    — Stream/connection diagnostics
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.deps import get_current_user, get_matterbridge_service
from src.db.models import M9User
from src.models.matterbridge import (
    MatterbridgeBinding,
    MatterbridgeBindingCreate,
    MatterbridgeBindingUpdate,
)
from src.services.matterbridge_service import MatterBridgeService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/worlds/{world_id}/matterbridge",
    tags=["matterbridge"],
)


def _validate_world_id(world_id: str) -> None:
    try:
        uuid.UUID(world_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid world ID") from None


# ---------------------------------------------------------------------------
# GET / — binding status
# ---------------------------------------------------------------------------


@router.get("", response_model=MatterbridgeBinding | None)
async def get_binding(
    world_id: str,
    current_user: M9User = Depends(get_current_user),
    svc: MatterBridgeService = Depends(get_matterbridge_service),
):
    """Get the Matterbridge binding for a world (token is masked)."""
    _validate_world_id(world_id)
    binding = await svc.get_binding(world_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="No Matterbridge binding")
    return MatterbridgeBinding(
        id=binding["id"],
        world_id=binding["world_id"],
        api_url=binding["api_url"],
        api_token_preview=binding["api_token_preview"],
        enabled=binding["enabled"],
        config_json=binding.get("config_json"),
        created_at=binding["created_at"],
        updated_at=binding["updated_at"],
    )


# ---------------------------------------------------------------------------
# POST / — create or update binding
# ---------------------------------------------------------------------------


@router.post("", response_model=MatterbridgeBinding, status_code=201)
async def create_or_update_binding(
    world_id: str,
    body: MatterbridgeBindingCreate,
    current_user: M9User = Depends(get_current_user),
    svc: MatterBridgeService = Depends(get_matterbridge_service),
):
    """Create or update a Matterbridge binding for a world.

    The API token is encrypted before storage.
    """
    _validate_world_id(world_id)
    result = await svc.create_or_update_binding(
        world_id=world_id,
        api_url=body.api_url,
        api_token=body.api_token,
        enabled=True,
        config_json=body.config_json,
    )
    return MatterbridgeBinding(
        id=result["id"],
        world_id=result["world_id"],
        api_url=result["api_url"],
        api_token_preview=result["api_token_preview"],
        enabled=result["enabled"],
        config_json=result.get("config_json"),
        created_at=result["created_at"],
        updated_at=result["updated_at"],
    )


# ---------------------------------------------------------------------------
# PATCH / — partial update
# ---------------------------------------------------------------------------


@router.patch("", response_model=MatterbridgeBinding)
async def update_binding(
    world_id: str,
    body: MatterbridgeBindingUpdate,
    current_user: M9User = Depends(get_current_user),
    svc: MatterBridgeService = Depends(get_matterbridge_service),
):
    """Partially update a Matterbridge binding."""
    _validate_world_id(world_id)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await svc.update_binding_field(world_id, **fields)
    if result is None:
        raise HTTPException(status_code=404, detail="No Matterbridge binding")
    return MatterbridgeBinding(
        id=result["id"],
        world_id=result["world_id"],
        api_url=result["api_url"],
        api_token_preview=result["api_token_preview"],
        enabled=result["enabled"],
        config_json=result.get("config_json"),
        created_at=result["created_at"],
        updated_at=result["updated_at"],
    )


# ---------------------------------------------------------------------------
# DELETE / — remove binding
# ---------------------------------------------------------------------------


@router.delete("", status_code=204)
async def delete_binding(
    world_id: str,
    current_user: M9User = Depends(get_current_user),
    svc: MatterBridgeService = Depends(get_matterbridge_service),
):
    """Delete a Matterbridge binding and stop its stream."""
    _validate_world_id(world_id)
    deleted = await svc.delete_binding(world_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No Matterbridge binding")


# ---------------------------------------------------------------------------
# POST /message — send a message via Matterbridge
# ---------------------------------------------------------------------------


class _SendMessageBody(BaseModel):
    text: str
    username: str
    gateway: str
    avatar: str = ""
    parent_id: str = ""


@router.post("/message")
async def send_message(
    world_id: str,
    body: _SendMessageBody,
    current_user: M9User = Depends(get_current_user),
    svc: MatterBridgeService = Depends(get_matterbridge_service),
):
    """Send a message to a Matterbridge gateway."""
    _validate_world_id(world_id)
    ok = await svc.send_message(
        world_id=world_id,
        text=body.text,
        username=body.username,
        gateway=body.gateway,
        avatar=body.avatar,
        parent_id=body.parent_id,
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send message via Matterbridge")
    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /messages — fetch message history
# ---------------------------------------------------------------------------


@router.get("/messages")
async def get_messages(
    world_id: str,
    gateway: str = Query(..., description="Matterbridge gateway name"),
    limit: int = Query(50, ge=1, le=200),
    current_user: M9User = Depends(get_current_user),
    svc: MatterBridgeService = Depends(get_matterbridge_service),
):
    """Fetch message history from the Matterbridge API."""
    _validate_world_id(world_id)
    messages = await svc.get_history(world_id, gateway=gateway, limit=limit)
    return [
        {
            "text": m.text,
            "username": m.username,
            "gateway": m.gateway,
            "avatar": m.avatar,
            "protocol": m.protocol,
            "id": m.msg_id,
            "timestamp": m.timestamp,
            "event": m.event,
            "parent_id": m.parent_id,
        }
        for m in messages
    ]


# ---------------------------------------------------------------------------
# GET /stream — SSE relay of inbound Matterbridge messages
# ---------------------------------------------------------------------------

# Per-world queues for SSE relay: world_id -> set of asyncio.Queue
_stream_queues: dict[str, set[asyncio.Queue]] = {}


def _register_stream_queue(world_id: str) -> asyncio.Queue:
    """Register a new SSE client queue for a world."""
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _stream_queues.setdefault(world_id, set()).add(q)
    return q


def _unregister_stream_queue(world_id: str, q: asyncio.Queue) -> None:
    """Remove an SSE client queue."""
    qs = _stream_queues.get(world_id)
    if qs is not None:
        qs.discard(q)
        if not qs:
            del _stream_queues[world_id]


def push_to_stream_queues(world_id: str, data: dict) -> None:
    """Push a message to all connected SSE clients for a world.

    Called by the MatterBridgeService callback.
    Non-blocking: drops the message if a queue is full.
    """
    qs = _stream_queues.get(world_id)
    if not qs:
        return
    for q in list(qs):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


@router.get("/stream")
async def stream_messages(
    world_id: str,
    request: Request,
    current_user: M9User = Depends(get_current_user),
    svc: MatterBridgeService = Depends(get_matterbridge_service),
):
    """SSE endpoint: relay inbound Matterbridge messages to the client.

    The stream keeps running until the client disconnects.
    A heartbeat is sent every 30 seconds to keep the connection alive.
    """
    _validate_world_id(world_id)

    # Ensure the SSE listener is running for this world
    await svc.start_stream(world_id)

    q = _register_stream_queue(world_id)

    async def _generate():
        try:
            while True:
                # Check client disconnect
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    # Heartbeat
                    yield "event: ping\ndata: {}\n\n"
        finally:
            _unregister_stream_queue(world_id, q)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# GET /status — diagnostics
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_status(
    world_id: str,
    current_user: M9User = Depends(get_current_user),
    svc: MatterBridgeService = Depends(get_matterbridge_service),
):
    """Get Matterbridge connection/stream status for a world."""
    _validate_world_id(world_id)

    binding = await svc.get_binding(world_id)
    stream_running = svc.is_stream_running(world_id)
    health = (
        {"status": "error", "detail": "No binding"}
        if not binding
        else await svc.health_check(world_id)
    )

    connected_clients = len(_stream_queues.get(world_id, set()))

    return {
        "world_id": world_id,
        "binding_configured": binding is not None,
        "enabled": binding.get("enabled", False) if binding else False,
        "stream_running": stream_running,
        "matterbridge_health": health,
        "connected_sse_clients": connected_clients,
    }
