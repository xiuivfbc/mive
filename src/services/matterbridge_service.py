"""Matterbridge 桥接服务

负责：
1. 配置加密存储（AES-256-GCM，复用 ApiKeyService 模式）
2. HTTP 客户端连接 Matterbridge REST API
3. SSE 消息流监听，带指数退避重连
4. 消息发送、接收、历史查询
5. 消息格式转换：Matterbridge 格式 ↔ MIVE 格式
6. 消息去重：基于 message_id

Matterbridge API 参考：https://github.com/42wim/matterbridge/wiki/API
- GET  /api/stream   → SSE 实时消息流
- POST /api/message  → 发送消息
- GET  /api/messages → 获取历史消息（需 ?gateway=xxx）
- GET  /api/health   → 健康检查
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from base64 import b64decode, b64encode
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.db.repositories.matterbridge_repo import MatterbridgeBridgeRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# SSE reconnect backoff
_BACKOFF_INITIAL = 1  # seconds
_BACKOFF_MAX = 60  # seconds
_BACKOFF_MULTIPLIER = 2

# Dedup window: entries older than this are pruned
_DEDUP_TTL = 3600  # 1 hour
_DEDUP_PRUNE_INTERVAL = 300  # prune every 5 minutes

# HTTP timeouts
_HTTP_TIMEOUT = httpx.Timeout(connect=10, read=30, write=10, pool=10)
_SSE_READ_TIMEOUT = None  # no read timeout for SSE streams


# ---------------------------------------------------------------------------
# Encryption helpers (AES-256-GCM, same pattern as ApiKeyService)
# ---------------------------------------------------------------------------


def _parse_key_secret(key_secret: str) -> bytes:
    """Accept a 64-char hex string (32 bytes) or a raw 32-byte key."""
    if len(key_secret) == 64:
        return bytes.fromhex(key_secret)
    encoded = key_secret.encode()
    if len(encoded) == 32:
        return encoded
    raise ValueError("Matterbridge key secret must be 64 hex chars (32 bytes)")


def _encrypt_token(key: bytes, plaintext: str) -> tuple[str, str]:
    """Encrypt a plaintext token. Returns (ciphertext_b64, iv_hex)."""
    iv = os.urandom(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(iv, plaintext.encode(), None)
    return b64encode(ct).decode(), iv.hex()


def _decrypt_token(key: bytes, encrypted_b64: str, iv_hex: str) -> str:
    """Decrypt an encrypted token."""
    iv = bytes.fromhex(iv_hex)
    ct = b64decode(encrypted_b64)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ct, None).decode()


def _mask_token(token: str) -> str:
    """Mask a token for safe display (e.g. 'abcd****efgh')."""
    if len(token) <= 6:
        return "****"
    if len(token) <= 8:
        return token[:2] + "*" * (len(token) - 4) + token[-2:]
    return token[:4] + "*" * (len(token) - 8) + token[-4:]


# ---------------------------------------------------------------------------
# Matterbridge message model (internal)
# ---------------------------------------------------------------------------


class MatterbridgeMessage:
    """Represents a single message from/to the Matterbridge API.

    Matterbridge JSON format:
    {
        "text": "hello",
        "username": "user",
        "gateway": "mygateway",
        "avatar": "",
        "protocol": "discord",
        "id": "msg-unique-id",
        "timestamp": "2024-01-01T00:00:00Z",
        "event": "",       # optional: join/leave/topic/etc
        "parent_id": "",   # optional: thread parent
        "extras": {}       # optional: protocol-specific extras
    }
    """

    __slots__ = (
        "text",
        "username",
        "gateway",
        "avatar",
        "protocol",
        "msg_id",
        "timestamp",
        "event",
        "parent_id",
        "extras",
    )

    def __init__(
        self,
        text: str,
        username: str,
        gateway: str,
        avatar: str = "",
        protocol: str = "",
        msg_id: str = "",
        timestamp: str = "",
        event: str = "",
        parent_id: str = "",
        extras: dict | None = None,
    ) -> None:
        self.text = text
        self.username = username
        self.gateway = gateway
        self.avatar = avatar
        self.protocol = protocol
        self.msg_id = msg_id
        self.timestamp = timestamp
        self.event = event
        self.parent_id = parent_id
        self.extras = extras

    @classmethod
    def from_dict(cls, data: dict) -> MatterbridgeMessage:
        return cls(
            text=data.get("text", ""),
            username=data.get("username", ""),
            gateway=data.get("gateway", ""),
            avatar=data.get("avatar", ""),
            protocol=data.get("protocol", ""),
            msg_id=data.get("id", ""),
            timestamp=data.get("timestamp", ""),
            event=data.get("event", ""),
            parent_id=data.get("parent_id", ""),
            extras=data.get("extras"),
        )

    def to_dict(self) -> dict:
        """Serialize to Matterbridge API format for sending."""
        out: dict[str, Any] = {
            "text": self.text,
            "username": self.username,
            "gateway": self.gateway,
        }
        if self.avatar:
            out["avatar"] = self.avatar
        if self.msg_id:
            out["id"] = self.msg_id
        if self.parent_id:
            out["parent_id"] = self.parent_id
        return out

    def __repr__(self) -> str:
        return (
            f"MatterbridgeMessage(gateway={self.gateway!r}, username={self.username!r}, "
            f"text={self.text[:50]!r}...)"
        )


# ---------------------------------------------------------------------------
# MatterBridgeService
# ---------------------------------------------------------------------------


# Type alias for the inbound message callback
MessageCallback = Callable[[str, MatterbridgeMessage], Coroutine[Any, Any, None]]


class MatterBridgeService:
    """Core service for Matterbridge integration.

    Responsibilities:
    - Encrypted storage of per-world Matterbridge API tokens
    - HTTP client for the Matterbridge REST API
    - SSE stream listener with exponential backoff reconnection
    - Message format conversion (Matterbridge <-> MIVE)
    - Message deduplication based on matterbridge message ID

    Lifecycle:
        service = MatterBridgeService(...)
        await service.start()  # initializes HTTP client
        service.register_callback(my_handler)
        await service.start_stream(world_id)  # starts SSE listener
        ...
        await service.stop()  # stops all streams, closes HTTP client
    """

    def __init__(
        self,
        repo: MatterbridgeBridgeRepository | None = None,
        key_secret: str = "",
        session_factory=None,
    ) -> None:
        self._repo = repo
        self._key = _parse_key_secret(key_secret)
        self._session_factory = session_factory
        if self._repo is None and self._session_factory is None:
            raise ValueError("Either repo or session_factory must be provided")
        # When session_factory is provided, we create a fresh repo per DB call
        # instead of using the injected repo (which may have a stale session).

        # HTTP client (initialized in start())
        self._client: httpx.AsyncClient | None = None

        # Per-world SSE stream tasks
        self._stream_tasks: dict[str, asyncio.Task] = {}  # world_id -> task
        self._stream_cancel_events: dict[str, asyncio.Event] = {}  # world_id -> cancel event

        # Dedup state: gateway -> {msg_id -> timestamp}
        self._seen_messages: dict[str, dict[str, float]] = {}
        self._last_prune: float = time.monotonic()

        # Inbound message callback: (world_id, message) -> None
        self._callback: MessageCallback | None = None

        # Flag to prevent double-start
        self._started = False

    async def _with_repo(self, fn):
        """Execute *fn(repo)* inside a fresh session when session_factory is set.

        When no session_factory is configured the injected repo is reused.
        """
        if self._session_factory is not None:
            async with self._session_factory() as session:
                repo = MatterbridgeBridgeRepository(session)
                result = await fn(repo)
                await session.commit()
                return result
        if self._repo is not None:
            return await fn(self._repo)
        raise RuntimeError("MatterBridgeService: no repo or session_factory available")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize the HTTP client. Call once at app startup."""
        if self._started:
            return
        self._client = httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": "MIVE-Matterbridge/1.0"},
        )
        self._started = True
        logger.info("MatterBridgeService started")

    async def stop(self) -> None:
        """Stop all streams and close the HTTP client. Call at app shutdown."""
        # Cancel all stream tasks
        for world_id in list(self._stream_tasks):
            await self.stop_stream(world_id)

        # Close HTTP client
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

        self._started = False
        logger.info("MatterBridgeService stopped")

    def register_callback(self, callback: MessageCallback) -> None:
        """Register a callback for inbound messages.

        The callback receives (world_id, MatterbridgeMessage) and should
        handle writing the message into the MIVE message system.
        """
        self._callback = callback

    # ------------------------------------------------------------------
    # Binding CRUD (with encrypted token storage)
    # ------------------------------------------------------------------

    async def create_or_update_binding(
        self,
        world_id: str,
        api_url: str,
        api_token: str,
        enabled: bool = True,
        config_json: dict | None = None,
    ) -> dict:
        """Create or update a Matterbridge binding for a world.

        The API token is encrypted before storage.

        Returns a dict with binding info (token is masked).
        """
        encrypted, iv = _encrypt_token(self._key, api_token)

        # Normalize URL: strip trailing slash
        api_url = api_url.rstrip("/")

        async def _do(repo):
            row = await repo.upsert_binding(
                world_id=world_id,
                api_url=api_url,
                api_token_encrypted=encrypted,
                api_token_iv=iv,
                enabled=enabled,
                config_json=config_json,
            )
            return {
                "id": str(row.id),
                "world_id": str(row.world_id),
                "api_url": row.api_url,
                "api_token_preview": _mask_token(api_token),
                "enabled": row.enabled,
                "config_json": row.config_json,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }

        return await self._with_repo(_do)

    async def get_binding(self, world_id: str) -> dict | None:
        """Get a Matterbridge binding for a world (token is masked)."""
        async def _do(repo):
            row = await repo.get_binding(world_id)
            if row is None:
                return None
            try:
                token = _decrypt_token(self._key, row.api_token_encrypted, row.api_token_iv)
                preview = _mask_token(token)
            except Exception:
                preview = "****"
            return {
                "id": str(row.id),
                "world_id": str(row.world_id),
                "api_url": row.api_url,
                "api_token_preview": preview,
                "enabled": row.enabled,
                "config_json": row.config_json,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }

        return await self._with_repo(_do)

    async def delete_binding(self, world_id: str) -> bool:
        """Delete a Matterbridge binding and stop its stream if running."""
        await self.stop_stream(world_id)
        return await self._with_repo(lambda repo: repo.delete_binding(world_id))

    async def update_binding_field(self, world_id: str, **fields) -> dict | None:
        """Update specific fields of a binding.

        If 'api_token' is in fields, it will be encrypted.
        Returns updated binding dict or None if not found.
        """
        # Handle token encryption if present
        if "api_token" in fields:
            token = fields.pop("api_token")
            encrypted, iv = _encrypt_token(self._key, token)
            fields["api_token_encrypted"] = encrypted
            fields["api_token_iv"] = iv

        async def _do(repo):
            row = await repo.update_binding(world_id, **fields)
            if row is None:
                return None
            try:
                dec_token = _decrypt_token(self._key, row.api_token_encrypted, row.api_token_iv)
                preview = _mask_token(dec_token)
            except Exception:
                preview = "****"
            return {
                "id": str(row.id),
                "world_id": str(row.world_id),
                "api_url": row.api_url,
                "api_token_preview": preview,
                "enabled": row.enabled,
                "config_json": row.config_json,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }

        return await self._with_repo(_do)

    async def list_enabled_bindings(self) -> list[dict]:
        """List all enabled bindings."""
        async def _do(repo):
            rows = await repo.list_enabled()
            result = []
            for row in rows:
                try:
                    token = _decrypt_token(self._key, row.api_token_encrypted, row.api_token_iv)
                    preview = _mask_token(token)
                except Exception:
                    preview = "****"
                result.append(
                    {
                        "id": str(row.id),
                        "world_id": str(row.world_id),
                        "api_url": row.api_url,
                        "api_token_preview": preview,
                        "enabled": row.enabled,
                    }
                )
            return result

        return await self._with_repo(_do)

    # ------------------------------------------------------------------
    # Internal: get decrypted credentials for a world
    # ------------------------------------------------------------------

    async def _get_credentials(self, world_id: str) -> tuple[str, str] | None:
        """Return (api_url, api_token) for a world, or None if not configured."""
        async def _do(repo):
            row = await repo.get_binding(world_id)
            if row is None or not row.enabled:
                return None
            try:
                token = _decrypt_token(self._key, row.api_token_encrypted, row.api_token_iv)
                return row.api_url, token
            except Exception:
                logger.error("Failed to decrypt Matterbridge token for world %s", world_id)
                return None

        return await self._with_repo(_do)

    def _auth_headers(self, token: str) -> dict[str, str]:
        """Build authorization headers for the Matterbridge API."""
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # HTTP Client: send message
    # ------------------------------------------------------------------

    async def send_message(
        self,
        world_id: str,
        text: str,
        username: str,
        gateway: str,
        avatar: str = "",
        parent_id: str = "",
    ) -> bool:
        """Send a message to a Matterbridge gateway.

        Args:
            world_id: The MIVE world ID.
            text: Message text content.
            username: Display name of the sender.
            gateway: Target Matterbridge gateway name.
            avatar: Optional avatar URL.
            parent_id: Optional parent message ID for threading.

        Returns:
            True if the message was sent successfully, False otherwise.
        """
        creds = await self._get_credentials(world_id)
        if creds is None:
            logger.warning("No Matterbridge binding for world %s", world_id)
            return False

        api_url, token = creds
        msg = MatterbridgeMessage(
            text=text,
            username=username,
            gateway=gateway,
            avatar=avatar,
            parent_id=parent_id,
        )

        return await self._post_message(api_url, token, msg)

    async def _post_message(
        self, api_url: str, token: str, msg: MatterbridgeMessage
    ) -> bool:
        """POST a message to the Matterbridge /api/message endpoint."""
        if self._client is None:
            logger.error("MatterBridgeService not started; cannot send message")
            return False

        url = f"{api_url}/api/message"
        headers = self._auth_headers(token)
        payload = msg.to_dict()

        try:
            resp = await self._client.post(url, json=payload, headers=headers)
            if resp.status_code in (200, 204):
                logger.debug(
                    "Sent message to Matterbridge gateway=%s username=%s",
                    msg.gateway,
                    msg.username,
                )
                return True
            else:
                logger.warning(
                    "Matterbridge send failed: status=%d body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
        except httpx.RequestError as exc:
            logger.error("Matterbridge send error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # HTTP Client: get history
    # ------------------------------------------------------------------

    async def get_history(
        self, world_id: str, gateway: str, limit: int = 50
    ) -> list[MatterbridgeMessage]:
        """Fetch message history from the Matterbridge API.

        Note: Matterbridge's /api/messages endpoint may not be available in
        all versions. This method gracefully handles 404/405 responses.

        Args:
            world_id: The MIVE world ID.
            gateway: The Matterbridge gateway to query.
            limit: Maximum number of messages to return.

        Returns:
            List of MatterbridgeMessage objects (newest first).
        """
        creds = await self._get_credentials(world_id)
        if creds is None:
            return []

        api_url, token = creds
        if self._client is None:
            return []

        url = f"{api_url}/api/messages"
        headers = self._auth_headers(token)
        params = {"gateway": gateway}

        try:
            resp = await self._client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    messages = [MatterbridgeMessage.from_dict(d) for d in data[:limit]]
                    return messages
                return []
            elif resp.status_code in (404, 405):
                logger.debug(
                    "Matterbridge /api/messages not available (status=%d)",
                    resp.status_code,
                )
                return []
            else:
                logger.warning(
                    "Matterbridge history fetch failed: status=%d", resp.status_code
                )
                return []
        except httpx.RequestError as exc:
            logger.error("Matterbridge history fetch error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # HTTP Client: health check
    # ------------------------------------------------------------------

    async def health_check(self, world_id: str) -> dict:
        """Check connectivity to a Matterbridge instance.

        Returns a dict with 'status' ('ok' or 'error') and optional 'detail'.
        """
        creds = await self._get_credentials(world_id)
        if creds is None:
            return {"status": "error", "detail": "No binding configured"}

        api_url, token = creds
        if self._client is None:
            return {"status": "error", "detail": "Service not started"}

        url = f"{api_url}/api/health"
        headers = self._auth_headers(token)

        try:
            resp = await self._client.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                return {"status": "ok"}
            return {"status": "error", "detail": f"HTTP {resp.status_code}"}
        except httpx.RequestError as exc:
            return {"status": "error", "detail": str(exc)}

    # ------------------------------------------------------------------
    # SSE Stream: start / stop
    # ------------------------------------------------------------------

    async def start_stream(self, world_id: str) -> bool:
        """Start an SSE stream listener for a world.

        Returns True if the stream was started, False if already running
        or no binding exists.
        """
        if world_id in self._stream_tasks:
            task = self._stream_tasks[world_id]
            if not task.done():
                logger.debug("Stream already running for world %s", world_id)
                return True

        creds = await self._get_credentials(world_id)
        if creds is None:
            logger.warning("Cannot start stream: no binding for world %s", world_id)
            return False

        cancel_event = asyncio.Event()
        self._stream_cancel_events[world_id] = cancel_event

        task = asyncio.create_task(
            self._stream_loop(world_id, cancel_event),
            name=f"matterbridge_sse_{world_id}",
        )
        task.add_done_callback(lambda t, wid=world_id: self._on_stream_done(wid, t))
        self._stream_tasks[world_id] = task

        logger.info("Started Matterbridge SSE stream for world %s", world_id)
        return True

    async def stop_stream(self, world_id: str) -> None:
        """Stop the SSE stream listener for a world."""
        cancel_event = self._stream_cancel_events.get(world_id)
        if cancel_event is not None:
            cancel_event.set()

        task = self._stream_tasks.pop(world_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._stream_cancel_events.pop(world_id, None)
        logger.info("Stopped Matterbridge SSE stream for world %s", world_id)

    def is_stream_running(self, world_id: str) -> bool:
        """Check if a stream is currently running for a world."""
        task = self._stream_tasks.get(world_id)
        return task is not None and not task.done()

    def _on_stream_done(self, world_id: str, task: asyncio.Task) -> None:
        """Callback when a stream task finishes (normally or with error)."""
        self._stream_tasks.pop(world_id, None)
        self._stream_cancel_events.pop(world_id, None)

        if task.cancelled():
            logger.debug("Stream task cancelled for world %s", world_id)
            return

        exc = task.exception()
        if exc is not None:
            logger.error("Stream task failed for world %s: %s", world_id, exc)

    # ------------------------------------------------------------------
    # SSE Stream: main loop with exponential backoff
    # ------------------------------------------------------------------

    async def _stream_loop(
        self, world_id: str, cancel_event: asyncio.Event
    ) -> None:
        """SSE stream loop with exponential backoff reconnection.

        Pattern follows snapshot_sync_service.py:
        - On connection success: reset backoff to initial
        - On transient error: sleep with exponential backoff, then retry
        - On CancelledError: exit cleanly
        """
        backoff = _BACKOFF_INITIAL

        while not cancel_event.is_set():
            creds = await self._get_credentials(world_id)
            if creds is None:
                logger.warning(
                    "Stream loop: binding gone for world %s, stopping", world_id
                )
                break

            api_url, token = creds
            url = f"{api_url}/api/stream"
            headers = self._auth_headers(token)

            try:
                await self._connect_and_listen(
                    world_id, url, headers, cancel_event
                )
                # If we get here, the stream ended normally (server closed)
                # Reset backoff and retry immediately
                backoff = _BACKOFF_INITIAL
                logger.debug("Stream ended normally for world %s, reconnecting", world_id)

            except asyncio.CancelledError:
                break

            except Exception as exc:
                if cancel_event.is_set():
                    break
                logger.warning(
                    "Stream error for world %s: %s — reconnecting in %ds",
                    world_id,
                    exc,
                    backoff,
                )
                try:
                    # Wait with backoff, but wake up immediately if cancelled
                    done, _ = await asyncio.wait(
                        [asyncio.create_task(cancel_event.wait())],
                        timeout=backoff,
                    )
                    if done:
                        break
                except asyncio.CancelledError:
                    break
                backoff = min(backoff * _BACKOFF_MULTIPLIER, _BACKOFF_MAX)

        logger.info("Stream loop exited for world %s", world_id)

    async def _connect_and_listen(
        self,
        world_id: str,
        url: str,
        headers: dict[str, str],
        cancel_event: asyncio.Event,
    ) -> None:
        """Connect to the SSE endpoint and process messages.

        Raises on connection errors so the caller can handle reconnection.
        """
        if self._client is None:
            raise RuntimeError("HTTP client not initialized")

        logger.debug("Connecting to Matterbridge SSE: %s", url)

        async with self._client.stream(
            "GET",
            url,
            headers={**headers, "Accept": "text/event-stream"},
            timeout=httpx.Timeout(connect=10, read=_SSE_READ_TIMEOUT, write=10, pool=10),
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"SSE connection failed: HTTP {response.status_code}, "
                    f"body={body[:200]!r}"
                )

            logger.info(
                "Connected to Matterbridge SSE for world %s (status=%d)",
                world_id,
                response.status_code,
            )

            # Process SSE stream line by line
            event_data = ""
            async for line in response.aiter_lines():
                if cancel_event.is_set():
                    break

                # SSE format: lines starting with "data: " contain the payload
                # An empty line signals the end of an event
                if line.startswith("data:"):
                    event_data = line[5:].strip()
                elif line == "" and event_data:
                    # End of event — process it
                    await self._process_sse_event(world_id, event_data)
                    event_data = ""
                elif line.startswith(":"):
                    # SSE comment (often used as keep-alive)
                    pass
                # Other lines (event:, id:, retry:) are ignored for now

    # ------------------------------------------------------------------
    # SSE Event Processing
    # ------------------------------------------------------------------

    async def _process_sse_event(self, world_id: str, data: str) -> None:
        """Parse and process a single SSE event.

        The data is expected to be a JSON object matching the Matterbridge
        message format.
        """
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.debug("Failed to parse SSE event data: %s (data=%r)", exc, data[:200])
            return

        if not isinstance(payload, dict):
            logger.debug("SSE event data is not a dict: %r", type(payload))
            return

        msg = MatterbridgeMessage.from_dict(payload)

        # Skip empty messages and system events (join/leave/topic)
        if not msg.text and not msg.event:
            return

        # Dedup check
        if self._is_duplicate(msg):
            logger.debug(
                "Duplicate message ignored: id=%s gateway=%s",
                msg.msg_id,
                msg.gateway,
            )
            return

        logger.info(
            "Received Matterbridge message: gateway=%s username=%s protocol=%s text=%r",
            msg.gateway,
            msg.username,
            msg.protocol,
            msg.text[:80],
        )

        # Deliver to registered callback
        if self._callback is not None:
            try:
                await self._callback(world_id, msg)
            except Exception:
                logger.exception(
                    "Callback failed for Matterbridge message (world=%s, gateway=%s)",
                    world_id,
                    msg.gateway,
                )

    # ------------------------------------------------------------------
    # Message Deduplication
    # ------------------------------------------------------------------

    def _is_duplicate(self, msg: MatterbridgeMessage) -> bool:
        """Check if a message has already been processed.

        Uses a per-gateway dict of {msg_id: timestamp}. Messages without
        an ID are never considered duplicates.

        Periodically prunes old entries to prevent unbounded growth.
        """
        if not msg.msg_id:
            return False

        self._maybe_prune_dedup()

        gateway = msg.gateway or "__default__"
        seen = self._seen_messages.get(gateway)
        if seen is None:
            seen = {}
            self._seen_messages[gateway] = seen

        now = time.monotonic()
        if msg.msg_id in seen:
            return True

        seen[msg.msg_id] = now
        return False

    def _maybe_prune_dedup(self) -> None:
        """Remove dedup entries older than _DEDUP_TTL."""
        now = time.monotonic()
        if now - self._last_prune < _DEDUP_PRUNE_INTERVAL:
            return

        self._last_prune = now
        cutoff = now - _DEDUP_TTL

        for gateway in list(self._seen_messages):
            seen = self._seen_messages[gateway]
            expired = [mid for mid, ts in seen.items() if ts < cutoff]
            for mid in expired:
                del seen[mid]
            if not seen:
                del self._seen_messages[gateway]

    def clear_dedup(self, gateway: str | None = None) -> None:
        """Clear dedup state for a gateway, or all gateways if None."""
        if gateway is None:
            self._seen_messages.clear()
        else:
            self._seen_messages.pop(gateway, None)

    # ------------------------------------------------------------------
    # Message Format Conversion
    # ------------------------------------------------------------------

    @staticmethod
    def to_mive_message(
        msg: MatterbridgeMessage,
        world_id: str,
        session_id: str | None = None,
    ) -> dict:
        """Convert a Matterbridge message to MIVE internal message format.

        Returns a dict suitable for creating a MIVE Message model instance.
        External messages use sender_type="user" with a synthetic sender_id
        derived from the username + protocol.

        Args:
            msg: The Matterbridge message.
            world_id: The MIVE world ID.
            session_id: Optional chat session ID.

        Returns:
            Dict with MIVE Message fields.
        """
        # Generate a deterministic sender_id from protocol + username
        # This ensures the same external user always maps to the same ID
        sender_seed = f"ext:{msg.protocol}:{msg.username}"
        sender_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, sender_seed))

        # Parse timestamp if available
        real_time = None
        if msg.timestamp:
            try:
                # Matterbridge uses RFC3339 / ISO 8601
                real_time = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00"))
                # Strip timezone for DB storage (naive UTC)
                real_time = real_time.replace(tzinfo=None)
            except (ValueError, TypeError):
                pass

        return {
            "id": str(uuid.uuid4()),
            "world_id": world_id,
            "session_id": session_id,
            "type": "dialogue",
            "sender_type": "user",  # external users are treated as "user" type
            "sender_id": sender_id,
            "sender_name": msg.username,
            "content": msg.text,
            "real_time": real_time,
            "is_key_message": False,
            "user_participated": False,
        }

    @staticmethod
    def from_mive_message(
        mive_msg: dict,
        gateway: str,
    ) -> MatterbridgeMessage:
        """Convert a MIVE message to Matterbridge format for outbound sending.

        Args:
            mive_msg: Dict with MIVE Message fields.
            gateway: Target Matterbridge gateway.

        Returns:
            MatterbridgeMessage ready for sending.
        """
        return MatterbridgeMessage(
            text=mive_msg.get("content", ""),
            username=mive_msg.get("sender_name", "MIVE"),
            gateway=gateway,
            msg_id=mive_msg.get("id", ""),
        )

    # ------------------------------------------------------------------
    # Stream status / diagnostics
    # ------------------------------------------------------------------

    def get_stream_status(self) -> dict[str, dict]:
        """Get status of all active streams."""
        result = {}
        for world_id, task in self._stream_tasks.items():
            result[world_id] = {
                "running": not task.done(),
                "cancelled": task.cancelled(),
                "error": str(task.exception()) if task.done() and not task.cancelled() else None,
            }
        return result

    async def start_all_enabled_streams(self) -> int:
        """Start streams for all enabled bindings. Returns count of started streams."""
        async def _do(repo):
            return await repo.list_enabled()

        bindings = await self._with_repo(_do)
        started = 0
        for binding in bindings:
            wid = str(binding.world_id)
            if await self.start_stream(wid):
                started += 1
        logger.info("Started %d/%d Matterbridge streams", started, len(bindings))
        return started
