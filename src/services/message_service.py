from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

from src.db.repositories.chat_session_repo import ChatSessionRepository
from src.db.repositories.message_repo import MessageRepository
from src.models.message import Message, MessageListResponse, SendMessageResponse

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.llm.base import LLMProvider
    from src.models.character import Character
    from src.services.dialogue_generation_service import DialogueGenerationService

logger = logging.getLogger(__name__)

_FLUSH_THRESHOLD = 20
_SELECTION_COUNTER_PREFIX = "selection_counter:"
_SELECTION_COUNTER_TTL = 86400  # 24h
_INERTIA_BASE_PROB = 0.1  # 场景惯性：重选基础概率
_INERTIA_PROB_STEP = 0.05  # 每跳过一次累加的概率
_SEQUENCE_COUNTER_PREFIX = "seq:"
_SEQUENCE_COUNTER_TTL = 86400 * 7  # 7 days
_ACTIVE_SESSIONS_KEY = "active_chat_sessions"
_INACTIVE_THRESHOLD_SECONDS = 600  # 10 minutes


class MessageService:
    def __init__(
        self,
        message_repo,
        dialogue_service: DialogueGenerationService | None = None,
        llm: LLMProvider | None = None,
        session_factory=None,
        chat_session_repo: ChatSessionRepository | None = None,
        redis: Redis | None = None,
        version_repo=None,
        character_repo=None,
        memory_module=None,  # MemoryModule，可选（向后兼容）
        memory_propagation_service=None,  # MemoryPropagationService，可选（向后兼容）
        memory_orchestrator=None,  # MemoryOrchestrator，可选，统一记忆生命周期
    ):
        self.message_repo = message_repo
        self.dialogue_service = dialogue_service
        self.llm = llm
        self.session_factory = session_factory
        self._chat_session_repo = chat_session_repo
        self._redis = redis
        self._version_repo = version_repo
        self._character_repo = character_repo
        self.memory_orchestrator = memory_orchestrator

    def _get_chat_session_repo(self) -> ChatSessionRepository:
        if self._chat_session_repo is not None:
            return self._chat_session_repo
        return ChatSessionRepository(self.message_repo.session)

    async def _get_selection_counter(self, key: str) -> int:
        """读取场景惯性计数器，Redis 不可用或出错返回 -1（视为"始终重选"）。"""
        if self._redis is None:
            return -1
        try:
            value = await self._redis.get(f"{_SELECTION_COUNTER_PREFIX}{key}")
            if value is None:
                return 0
            return int(value)
        except Exception:
            logger.debug("Redis get failed for selection_counter:%s", key)
            return -1

    async def _set_selection_counter(self, key: str, value: int) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                f"{_SELECTION_COUNTER_PREFIX}{key}", value, ex=_SELECTION_COUNTER_TTL
            )
        except Exception:
            logger.debug("Redis set failed for selection_counter:%s", key)

    async def _reset_selection_counter(self, key: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(f"{_SELECTION_COUNTER_PREFIX}{key}")
        except Exception:
            logger.debug("Redis delete failed for selection_counter:%s", key)

    async def _next_sequence(self, session_id: str, message_repo) -> int:
        """Atomically allocate the next sequence number for a session.

        Uses Redis INCR when available; falls back to DB max+1.  The DB unique
        constraint on (session_id, sequence) guards against true duplicates --
        if a concurrent request allocated the same number, the INSERT will fail
        with a unique-violation and the caller can retry.
        """
        if self._redis is not None:
            try:
                key = f"{_SEQUENCE_COUNTER_PREFIX}{session_id}"
                value = await self._redis.incr(key)
                await self._redis.expire(key, _SEQUENCE_COUNTER_TTL)
                return int(value)
            except Exception:
                logger.debug("Redis INCR failed for seq:%s, falling back to DB", session_id)
        # Fallback: read from DB max+1.  Under concurrency two requests may
        # read the same max; the unique constraint on (session_id, sequence)
        # will reject the duplicate INSERT so the caller can retry.
        max_seq = await message_repo.get_max_sequence(session_id)
        return max_seq + 1

    async def _create_chat_session(
        self,
        world_id: str,
        content: str,
        memories_enabled: bool,
        existing_id: str | None = None,
    ) -> str:
        """Create a new chat session and return its id (as string).

        If *existing_id* is given, the new row reuses that UUID so that any
        uncommitted message rows referencing it keep their FK intact after a
        rollback-and-recreate cycle.

        Extracted from send_message so it can be reused in Phase 3 error recovery.
        """
        chat_session_repo = self._get_chat_session_repo()
        if existing_id is not None:
            existing = await chat_session_repo.get_by_id(existing_id)
            if existing is not None:
                return existing_id

            from src.db.models import M4ChatSession

            if self._version_repo is not None:
                version_repo = self._version_repo
            else:
                from src.db.repositories.version_repo import VersionRepository

                version_repo = VersionRepository(self.message_repo.session)
            latest_version = await version_repo.get_latest(world_id)
            current_version_id = latest_version.id if latest_version else None
            row = M4ChatSession(
                id=uuid.UUID(existing_id),
                world_id=uuid.UUID(world_id),
                type="character",
                title=content[:30],
                version_id=uuid.UUID(current_version_id) if current_version_id else None,
                memories_enabled=memories_enabled,
            )
            self.message_repo.session.add(row)
            await self.message_repo.session.flush()
            return existing_id
        if self._version_repo is not None:
            version_repo = self._version_repo
        else:
            from src.db.repositories.version_repo import VersionRepository

            version_repo = VersionRepository(self.message_repo.session)
        latest_version = await version_repo.get_latest(world_id)
        current_version_id = latest_version.id if latest_version else None
        chat_session = await chat_session_repo.create(
            world_id,
            "character",
            title=content[:30],
            version_id=current_version_id,
            memories_enabled=memories_enabled,
        )
        return str(chat_session.id)

    async def send_message(
        self,
        world_id: str,
        content: str,
        participant_mode: Literal["auto", "edit", "include"] = "auto",
        participants: list[dict] | None = None,
        session_id: str | None = None,
        memories_enabled: bool = False,
        action_descriptions: bool = False,
        element_rerank: bool = False,
        idempotency_key: str | None = None,
        show_narration: bool = False,
        user_role: str | None = None,
        element_injection_ids: list[str] | None = None,
        constraint: str | None = None,
    ) -> SendMessageResponse:
        # NOTE: Removed defensive rollback at method start (Issue 1 fix).
        # FastAPI's get_session dependency creates a fresh session per request,
        # so the session is always clean when send_message is entered.
        # Manual rollback conflicted with FastAPI's session lifecycle.

        # ── Idempotency check (atomic via SET NX) ─────────────────────────
        # Issue 3 fix: guarantee lock release via finally block at method end.
        _lock_key = f"idempotency:{idempotency_key}:lock" if idempotency_key else None
        if _lock_key and self._redis is not None:
            try:
                # Check if result already cached
                cached = await self._redis.get(f"idempotency:{idempotency_key}")
                if cached is not None:
                    data = json.loads(cached) if isinstance(cached, (str, bytes)) else cached
                    return SendMessageResponse.model_validate(data)

                # Try to acquire processing lock (SET NX prevents concurrent processing)
                # Lock TTL (600s) exceeds cache TTL (300s) so that polling requests always
                # find the cache during normal processing; the >300s gap is a theoretical
                # edge case (chat generation is typically seconds, not minutes).
                acquired = await self._redis.set(_lock_key, "1", nx=True, ex=600)
                if not acquired:
                    # Another request is processing — poll for the cached result
                    for _ in range(30):  # poll up to ~30s
                        await asyncio.sleep(1)
                        cached = await self._redis.get(f"idempotency:{idempotency_key}")
                        if cached is not None:
                            data = (
                                json.loads(cached) if isinstance(cached, (str, bytes)) else cached
                            )
                            return SendMessageResponse.model_validate(data)
                    # Timed out — fall through to process (lock may have expired)
                    logger.warning(
                        "Idempotency lock timeout for key %s",
                        idempotency_key,
                    )
            except Exception:
                logger.warning(
                    "Idempotency cache read failed for key %s",
                    idempotency_key,
                )

        from sqlalchemy import func as sa_func
        from sqlalchemy import select as sa_select

        from src.db.models import M4ChatSession

        chat_session_id: str | None = session_id

        # ── Phase 1: Read data (read-only on request session) ───────────
        try:
            # Validate session_id exists in DB
            if chat_session_id is not None:
                _check_stmt = (
                    sa_select(sa_func.count())
                    .select_from(M4ChatSession)
                    .where(M4ChatSession.id == uuid.UUID(chat_session_id))
                )
                _check_result = await self.message_repo.session.execute(_check_stmt)
                _exists = (await _check_result.scalar()) > 0
                if not _exists:
                    logger.warning(
                        "Session %s not found in DB, will create new session",
                        chat_session_id,
                    )
                    chat_session_id = None
        except Exception:
            # Issue 8: upgraded from silent pass to WARNING
            logger.warning("Session validation failed, assuming session exists", exc_info=True)

        # ── Track active session in Redis zset ────────────────────────────
        if chat_session_id and self._redis is not None:
            try:
                await self._redis.zadd(
                    _ACTIVE_SESSIONS_KEY,
                    {chat_session_id: datetime.now(UTC).timestamp()},
                )
            except Exception:
                logger.debug("Redis ZADD failed for active session %s", chat_session_id)

        # ── Early return if no dialogue service ─────────────────────────
        if self.dialogue_service is None:
            if chat_session_id is None:
                try:
                    chat_session_id = await self._create_chat_session(
                        world_id, content, memories_enabled,
                    )
                except Exception as e:
                    logger.exception("Failed to create chat session for world %s: %s", world_id, e)
                    raise RuntimeError("会话创建失败，请重试") from None
            user_msg = Message(
                id=str(uuid.uuid4()),
                world_id=world_id,
                session_id=chat_session_id,
                type="user",
                sender_type="user",
                sender_id=user_role,
                content=content,
                user_participated=True,
            )
            user_msg = await self.message_repo.create(user_msg)
            user_msg.status = "failed"
            await self.message_repo.session.commit()
            return SendMessageResponse(
                user_message=user_msg,
                responses=[],
                error="dialogue_generation_failed",
            )

        # edit 模式：加载上次 session 参与者，用于计算 diff
        previous_participants: list[dict] | None = None
        if participant_mode == "edit" and chat_session_id and session_id:
            try:
                chat_session_repo = self._get_chat_session_repo()
                existing_session = await chat_session_repo.get_by_id(chat_session_id)
                if existing_session and existing_session.participants:
                    # Reconstruct {id, name} dicts from stored UUID strings
                    from src.utils.character_name_cache import get_character_names

                    if self._character_repo is not None:
                        char_repo = self._character_repo
                    else:
                        from src.db.repositories.character_repo import CharacterRepository

                        char_repo = CharacterRepository(self.message_repo.session)
                    participant_ids = [
                        p for p in existing_session.participants if isinstance(p, str)
                    ]
                    name_map = await get_character_names(
                        participant_ids, redis=self._redis, character_repo=char_repo
                    )
                    rebuilt: list[dict] = []
                    for p in existing_session.participants:
                        if isinstance(p, str):
                            name = name_map.get(p)
                            if name:
                                rebuilt.append({"id": p, "name": name})
                        elif isinstance(p, dict):
                            rebuilt.append(p)
                    previous_participants = rebuilt
            except Exception:
                # Issue 8: upgraded from silent pass to WARNING
                logger.warning(
                    "Failed to load previous participants for session %s",
                    chat_session_id,
                    exc_info=True,
                )

        session_memories_enabled = memories_enabled
        if session_id is not None and chat_session_id:
            try:
                _sess_repo = self._get_chat_session_repo()
                _existing = await _sess_repo.get_by_id(chat_session_id)
                if _existing is not None and hasattr(_existing, "memories_enabled"):
                    session_memories_enabled = _existing.memories_enabled
            except Exception:
                # Issue 8: upgraded from silent pass to WARNING
                logger.warning(
                    "Failed to read memories_enabled for session %s",
                    chat_session_id,
                    exc_info=True,
                )

        # ── 判断是否需要生成旁白 ──────────────────────────────────────
        # 只在两种情况下生成旁白：① 会话开头（无历史消息） ② 参与角色有变化
        effective_show_narration = show_narration
        if show_narration and chat_session_id:
            try:
                _has_hist = await self.message_repo.has_messages(
                    chat_session_id, exclude_types=("event", "narration")
                )
                if not _has_hist:
                    # 会话开头，生成旁白
                    pass
                else:
                    # 有历史消息，比较参与角色是否有变化
                    _sess_repo = self._get_chat_session_repo()
                    _existing = await _sess_repo.get_by_id(chat_session_id)
                    _stored = _existing.participants if _existing else None
                    if _stored and participants:
                        _stored_ids = {
                            p if isinstance(p, str) else p.get("id", "") for p in _stored
                        }
                        _curr_ids = {
                            p.get("id", "") if isinstance(p, dict) else p for p in participants
                        }
                        if _stored_ids == _curr_ids:
                            effective_show_narration = False
                    else:
                        effective_show_narration = False
            except Exception:
                # Issue 8: upgraded from silent pass to WARNING
                logger.warning(
                    "Failed to check narration conditions for session %s",
                    chat_session_id,
                    exc_info=True,
                )

        # ── 加载事件索引（供 select_participants 选事件） ────────────────
        event_map: dict[str, str] = {}
        try:
            from src.db.repositories.event_index_repo import EventIndexRepository

            ei_repo = EventIndexRepository(self.message_repo.session)
            ei_entries = await ei_repo.list_by_world(world_id)
            event_map = {str(e.id): f"{e.event_name}：{e.brief}" for e in ei_entries}
        except Exception:
            # Issue 8: upgraded from silent pass to WARNING
            logger.warning("Failed to load event index for world %s", world_id, exc_info=True)

        # ── 场景惯性：累计概率计数器 ─────────────────────────────────────
        counter_key = chat_session_id or "__default__"
        if participant_mode == "edit":
            # edit 模式：计数器归零；select_participants 内部有 edit 快捷路径（不调用 LLM，
            # 但仍计算 background 关联角色），因此仍需调用
            await self._reset_selection_counter(counter_key)
            try:
                call1 = await self.dialogue_service.select_participants(
                    world_id=world_id,
                    user_message=content,
                    session_id=chat_session_id,
                    current_participants=participants,
                    previous_participants=previous_participants,
                    participant_mode=participant_mode,
                    show_narration=effective_show_narration,
                    event_map=event_map,
                    user_role=user_role,
                )
            except Exception:
                logger.exception("select_participants failed for world %s", world_id)
                call1 = {
                    "speakers": participants or [],
                    "background": [],
                    "narration": "",
                    "relevant_elements": [],
                    "relevant_event": None,
                }
        elif participant_mode in ("auto", "include"):
            count = await self._get_selection_counter(counter_key)
            has_existing_participants = bool(participants)
            reselect_prob = min(1.0, _INERTIA_BASE_PROB + count * _INERTIA_PROB_STEP)
            should_reselect = count < 0 or random.random() < reselect_prob
            if not should_reselect and has_existing_participants:
                # 未触发重选，延续上一轮参与者，计数器累加
                await self._set_selection_counter(counter_key, count + 1)
                call1 = {
                    "speakers": participants or [],
                    "background": [],
                    "narration": "",
                    "relevant_elements": [],
                    "relevant_event": None,
                }
            else:
                # 触发重选（或无现有参与者），计数器归零
                if count >= 0:
                    await self._set_selection_counter(counter_key, 0)
                try:
                    call1 = await self.dialogue_service.select_participants(
                        world_id=world_id,
                        user_message=content,
                        session_id=chat_session_id,
                        current_participants=participants,
                        previous_participants=previous_participants,
                        participant_mode=participant_mode,
                        show_narration=effective_show_narration,
                        event_map=event_map,
                        user_role=user_role,
                    )
                except Exception:
                    logger.exception("select_participants failed for world %s", world_id)
                    call1 = {
                        "speakers": participants or [],
                        "background": [],
                        "narration": "",
                        "relevant_elements": [],
                        "relevant_event": None,
                    }
        else:
            # 未知 mode，走原逻辑
            try:
                call1 = await self.dialogue_service.select_participants(
                    world_id=world_id,
                    user_message=content,
                    session_id=chat_session_id,
                    current_participants=participants,
                    previous_participants=previous_participants,
                    participant_mode=participant_mode,
                    show_narration=effective_show_narration,
                    event_map=event_map,
                    user_role=user_role,
                )
            except Exception:
                logger.exception("select_participants failed for world %s", world_id)
                call1 = {
                    "speakers": participants or [],
                    "background": [],
                    "narration": "",
                    "relevant_elements": [],
                    "relevant_event": None,
                }

        if participant_mode == "edit" and participants:
            selected_participants = participants
        else:
            selected_participants = call1.get("speakers")
            if selected_participants is None:
                selected_participants = call1.get("participants") or []
        narration_text = call1.get("narration") or ""
        background = call1.get("background") or []
        relevant_elements = call1.get("relevant_elements") or []
        relevant_event = call1.get("relevant_event")

        logger.info(
            "[send_message] participants selected: mode=%s, speakers=%s, narration=%r, session=%s",
            participant_mode,
            [(p.get("name"), p.get("id")) for p in selected_participants],
            narration_text[:60] if narration_text else "",
            chat_session_id,
        )

        # ── Load session-level element injection and constraint settings ──
        _session_elem_ids: list[str] | None = None
        _session_constraint: str = ""
        if chat_session_id is not None:
            _existing = await self._get_chat_session_repo().get_by_id(chat_session_id)
            if _existing is not None:
                # If request already carries element_injection_ids, use them directly
                if element_injection_ids is not None:
                    _session_elem_ids = element_injection_ids
                else:
                    _session_elem_ids = _existing.element_injection_ids
                _session_constraint = constraint or _existing.constraints or ""

        # ── Issue 1 fix: Use a dedicated write session for all DB writes ──
        # This isolates writes from the request session lifecycle. If dialogue
        # generation fails, we can rollback the write session without losing
        # the ability to re-create the user message in error recovery.
        # If session_factory is unavailable (should not happen in production),
        # fall back to the request session with a warning.
        write_session_ctx = None
        original_msg_session = None
        original_chat_session = None
        if self.session_factory is not None:
            write_session_ctx = self.session_factory()
            write_session = await write_session_ctx.__aenter__()
            write_msg_repo = MessageRepository(write_session)
            # Swap the message_repo session so _create_chat_session and
            # dialogue_service.generate_response use the write session
            original_msg_session = self.message_repo.session
            self.message_repo.session = write_session
            # Also swap chat_session_repo session to avoid FK violations
            # when creating new sessions in the write session
            if self._chat_session_repo is not None:
                original_chat_session = self._chat_session_repo.session
                self._chat_session_repo.session = write_session
            if self.dialogue_service and hasattr(self.dialogue_service, "message_repo"):
                self.dialogue_service.message_repo.session = write_session
        else:
            write_session = self.message_repo.session
            write_msg_repo = self.message_repo
            logger.warning("session_factory not available; using request session for writes")

        try:
            # Create or re-create the session row
            if chat_session_id is None:
                try:
                    chat_session_id = await self._create_chat_session(
                        world_id, content, memories_enabled,
                    )
                except Exception as e:
                    logger.exception("Failed to create chat session for world %s: %s", world_id, e)
                    raise RuntimeError("会话创建失败，请重试") from None
            else:
                # Verify the session row exists; re-create if not
                try:
                    _check_stmt = (
                        sa_select(sa_func.count())
                        .select_from(M4ChatSession)
                        .where(M4ChatSession.id == uuid.UUID(chat_session_id))
                    )
                    _check_result = await write_session.execute(_check_stmt)
                    if (await _check_result.scalar()) == 0:
                        chat_session_id = await self._create_chat_session(
                            world_id,
                            content,
                            memories_enabled,
                            existing_id=chat_session_id,
                        )
                except Exception:
                    try:
                        chat_session_id = await self._create_chat_session(
                            world_id,
                            content,
                            memories_enabled,
                            existing_id=chat_session_id,
                        )
                    except Exception:
                        logger.exception("Session recovery failed for world %s", world_id)

            # 写旁白消息
            narration_msg: Message | None = None
            if narration_text:
                narration_msg = Message(
                    id=str(uuid.uuid4()),
                    world_id=world_id,
                    session_id=chat_session_id,
                    type="narration",
                    sender_type="system",
                    content=narration_text,
                    user_participated=False,
                )
                try:
                    narration_msg = await write_msg_repo.create(narration_msg)
                except Exception:
                    logger.exception("Narration creation failed for session %s", chat_session_id)
                    narration_msg = None

            # ── Sequence generation ────────────────────────────────────────
            user_sequence = 1
            if chat_session_id:
                try:
                    user_sequence = await self._next_sequence(chat_session_id, write_msg_repo)
                except Exception:
                    logger.debug("_next_sequence failed, defaulting to 1")

            # 创建用户消息
            user_msg = Message(
                id=str(uuid.uuid4()),
                world_id=world_id,
                session_id=chat_session_id,
                type="user",
                sender_type="user",
                sender_id=user_role,
                content=content,
                user_participated=True,
                sequence=user_sequence,
                idempotency_key=idempotency_key,
            )
            user_msg = await write_msg_repo.create(user_msg)

            # 更新 session 参与者
            # Issue 7 fix: write_session is always fresh (InDoubtError impossible),
            # so begin_nested is safe.
            try:
                async with write_session.begin_nested():
                    chat_session_repo = self._get_chat_session_repo()
                    # Temporarily point chat_session_repo to write_session
                    _orig_cs_session = chat_session_repo.session
                    chat_session_repo.session = write_session
                    try:
                        await chat_session_repo.update_participants(
                            session_id=chat_session_id,
                            participants=selected_participants,
                            participant_mode=participant_mode,
                        )
                    finally:
                        chat_session_repo.session = _orig_cs_session
            except Exception:
                logger.warning(
                    "update_participants failed for session %s",
                    chat_session_id,
                    exc_info=True,
                )

            # Issue 5 fix: commit the write session NOW so user_msg, narration,
            # and chat_session are persisted before attempting dialogue generation.
            # If dialogue fails, these survive and the error response references
            # real DB rows (not rolled-back ghost objects).
            if write_session_ctx is not None:
                await write_session.commit()

            # Persist element injection and constraint settings
            try:
                chat_session_repo = self._get_chat_session_repo()
                _orig_cs_opts = chat_session_repo.session
                chat_session_repo.session = write_session
                try:
                    await chat_session_repo.update_session_options(
                        session_id=chat_session_id,
                        element_injection_ids=element_injection_ids,
                        constraints=constraint or "",
                    )
                finally:
                    chat_session_repo.session = _orig_cs_opts
            except Exception:
                logger.debug("Failed to update session options for session %s", chat_session_id)

            # Update session last_active_at
            try:
                chat_session_repo = self._get_chat_session_repo()
                _orig_cs_session2 = chat_session_repo.session
                chat_session_repo.session = write_session
                try:
                    await chat_session_repo.update_last_active_at(chat_session_id)
                finally:
                    chat_session_repo.session = _orig_cs_session2
            except Exception:
                logger.debug("Failed to update last_active_at for session %s", chat_session_id)

            # Call 2: 生成对话 (dialogue_service writes responses via swapped message_repo)
            try:
                logger.info(
                    "[send_message] calling generate_response: world=%s, session=%s, "
                    "participants=%s, user_msg_seq=%d",
                    world_id,
                    chat_session_id,
                    [p.get("name") for p in selected_participants],
                    user_sequence,
                )
                responses = await self.dialogue_service.generate_response(
                    world_id=world_id,
                    user_message=content,
                    participants=selected_participants,
                    session_id=chat_session_id,
                    background=background,
                    relevant_elements=relevant_elements,
                    relevant_event=relevant_event,
                    action_descriptions=action_descriptions,
                    element_rerank=element_rerank,
                    next_sequence=user_sequence + 1,
                    user_role=user_role,
                    manual_elements=_session_elem_ids,
                    constraint=_session_constraint,
                )
                logger.info(
                    "[send_message] generate_response returned %d responses for session=%s",
                    len(responses),
                    chat_session_id,
                )

                # ── Rollback on zero replies ───────────────────────────────
                if not responses:
                    logger.warning(
                        "[send_message] empty responses for session=%s, "
                        "deleting user message %s (seq=%d). "
                        "This means the inactive flush will find no unrecorded messages.",
                        chat_session_id,
                        user_msg.id,
                        user_sequence,
                    )
                    # Delete user message via write session
                    rollback_ids = [user_msg.id]
                    try:
                        await write_msg_repo.delete_by_ids(rollback_ids)
                        if write_session_ctx is not None:
                            await write_session.commit()
                    except Exception:
                        logger.warning(
                            "Rollback failed for messages %s", rollback_ids, exc_info=True
                        )
                    error_resp = SendMessageResponse(
                        user_message=user_msg,
                        responses=[],
                        narration=narration_msg,
                        error="no_character_replies",
                        session_id=chat_session_id,
                        participants=selected_participants,
                        participant_mode=participant_mode,
                    )
                    return error_resp

                # Commit dialogue responses
                if write_session_ctx is not None:
                    await write_session.commit()

                # ── 同步 Redis sequence 计数器 ──────────────────────────
                if chat_session_id and self._redis and responses:
                    last_seq = responses[-1].sequence
                    if last_seq and last_seq > user_sequence:
                        try:
                            _SYNC_SEQ_LUA = (  # noqa: N806
                                "local cur = tonumber(redis.call('GET', KEYS[1])) "
                                "if not cur or tonumber(ARGV[1]) > cur then "
                                "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]) "
                                "end return 1"
                            )
                            await self._redis.eval(
                                _SYNC_SEQ_LUA,
                                1,
                                f"{_SEQUENCE_COUNTER_PREFIX}{chat_session_id}",
                                last_seq,
                                _SEQUENCE_COUNTER_TTL,
                            )
                        except Exception:
                            logger.debug("Redis set failed for seq sync:%s", chat_session_id)

                # ── auto-trigger 记忆刷新 ──────────────────────────────
                memory_flush_triggered = False
                if (
                    session_memories_enabled
                    and chat_session_id
                    and self.session_factory
                    and self.llm
                ):
                    try:
                        memory_flush_triggered = True
                        task = asyncio.create_task(
                            self._maybe_auto_flush_memories(world_id, chat_session_id)
                        )
                        task.add_done_callback(self._task_exception_logger)
                    except Exception:
                        pass  # 不影响正常响应

                result = SendMessageResponse(
                    user_message=user_msg,
                    responses=responses,
                    narration=narration_msg,
                    session_id=chat_session_id,
                    participants=selected_participants,
                    participant_mode=participant_mode,
                    memory_flush_triggered=memory_flush_triggered,
                )

                # ── Cache successful result ────────────────────────────
                if idempotency_key and self._redis is not None:
                    try:
                        await self._redis.set(
                            f"idempotency:{idempotency_key}",
                            result.model_dump_json(),
                            ex=300,
                        )
                    except Exception:
                        logger.debug("Idempotency cache write failed for key %s", idempotency_key)

                return result
            except Exception as exc:
                logger.exception(
                    "[send_message] Dialogue generation failed for world %s, session=%s: %s",
                    world_id,
                    chat_session_id,
                    exc,
                )
                # Issue 11 fix: expire all objects to prevent stale state
                try:
                    write_session.expire_all()
                except Exception:
                    pass
                # Rollback dialogue writes (user_msg was committed earlier, survives)
                if write_session_ctx is not None:
                    try:
                        await write_session.rollback()
                    except Exception:
                        pass
                # Issue 5 fix: recover user_msg for the error response.
                # The user_msg was committed before dialogue generation, so it
                # survives the rollback.  Re-creating it would violate the
                # unique constraint on (session_id, sequence) -- instead, reload
                # the existing row from DB.  If the ORM object is stale (e.g.
                # expire_all + rollback cleared it), fetch by ID.
                try:
                    # chat_session_id was committed earlier, should still exist.
                    # Re-verify; if gone (unlikely), re-create.
                    _exists_stmt = (
                        sa_select(sa_func.count())
                        .select_from(M4ChatSession)
                        .where(M4ChatSession.id == uuid.UUID(chat_session_id))
                    )
                    _exists_result = await write_session.execute(_exists_stmt)
                    if (await _exists_result.scalar()) == 0:
                        chat_session_id = await self._create_chat_session(
                            world_id, content, memories_enabled,
                        )
                    reloaded = await write_msg_repo.get_by_id(user_msg.id)
                    if reloaded is not None:
                        user_msg = reloaded
                    else:
                        user_msg = Message(
                            id=str(uuid.uuid4()),
                            world_id=world_id,
                            session_id=chat_session_id,
                            type="user",
                            sender_type="user",
                            sender_id=user_role,
                            content=content,
                            user_participated=True,
                            sequence=user_sequence + 1,
                            idempotency_key=idempotency_key,
                        )
                        user_msg = await write_msg_repo.create(user_msg)
                        if write_session_ctx is not None:
                            await write_session.commit()
                except Exception:
                    logger.exception(
                        "Failed to recover session/message after dialogue failure for world %s",
                        world_id,
                    )
                    user_msg = Message(
                        id=str(uuid.uuid4()),
                        world_id=world_id,
                        session_id=chat_session_id,
                        type="user",
                        sender_type="user",
                        sender_id=user_role,
                        content=content,
                        user_participated=True,
                        sequence=user_sequence,
                        idempotency_key=idempotency_key,
                    )
                try:
                    user_msg.status = "failed"
                    if write_session_ctx is not None:
                        await write_session.commit()
                    error_resp = SendMessageResponse(
                        user_message=user_msg,
                        responses=[],
                        narration=None,
                        error="dialogue_generation_failed",
                        session_id=chat_session_id,
                        participants=selected_participants,
                        participant_mode=participant_mode,
                    )
                    # Cache error result
                    if idempotency_key and self._redis is not None:
                        try:
                            await self._redis.set(
                                f"idempotency:{idempotency_key}",
                                error_resp.model_dump_json(),
                                ex=300,
                            )
                        except Exception:
                            logger.debug(
                                "Idempotency cache write failed for key %s", idempotency_key
                            )
                except Exception:
                    logger.exception("Failed to build error response for world %s", world_id)
                    error_resp = SendMessageResponse(
                        user_message=Message(
                            id=str(uuid.uuid4()),
                            world_id=world_id,
                            session_id=chat_session_id,
                            type="user",
                            sender_type="user",
                            sender_id=user_role,
                            content=content,
                            user_participated=True,
                        ),
                        responses=[],
                        error="dialogue_generation_failed",
                    )
                return error_resp
        finally:
            # ── Restore original sessions ──────────────────────────────────
            if original_msg_session is not None:
                self.message_repo.session = original_msg_session
                if self.dialogue_service and hasattr(self.dialogue_service, "message_repo"):
                    self.dialogue_service.message_repo.session = original_msg_session
            if original_chat_session is not None and self._chat_session_repo is not None:
                self._chat_session_repo.session = original_chat_session
            # Close write session context manager
            if write_session_ctx is not None:
                try:
                    await write_session_ctx.__aexit__(None, None, None)
                except Exception:
                    pass
            # Issue 3 fix: always release idempotency lock in finally block
            if _lock_key and self._redis is not None:
                try:
                    await self._redis.delete(_lock_key)
                except Exception:
                    logger.debug("Failed to release idempotency lock %s", _lock_key)

    async def list_messages(
        self,
        world_id: str,
        before_sequence: int | None = None,
        limit: int = 50,
        sender_id: str | None = None,
        type: str | None = None,
        session_id: str | None = None,
    ) -> MessageListResponse:
        messages = await self.message_repo.list_filtered(
            world_id,
            before_sequence=before_sequence,
            limit=limit + 1,
            sender_id=sender_id,
            type=type,
            session_id=session_id,
        )
        has_more = len(messages) > limit
        if has_more:
            messages = messages[:limit]

        # Resolve sender_name for character messages
        from src.utils.character_name_cache import resolve_message_sender_names

        if self._character_repo is not None:
            char_repo = self._character_repo
        else:
            from src.db.repositories.character_repo import CharacterRepository

            char_repo = CharacterRepository(self.message_repo.session)
        await resolve_message_sender_names(messages, redis=self._redis, character_repo=char_repo)

        return MessageListResponse(messages=messages, has_more=has_more)

    @staticmethod
    def _task_exception_logger(task: asyncio.Task) -> None:
        """Callback for fire-and-forget tasks to log unhandled exceptions."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.exception("Background task failed: %s", exc)

    async def _maybe_auto_flush_memories(self, world_id: str, session_id: str) -> None:
        """Auto-trigger: check sequence gap and flush if threshold met.

        Uses sequence-based tracking: compares current_max_sequence against
        last_flushed_sequence stored on the chat session row.
        """
        try:
            # Quick pre-check: read last_flushed_sequence and current max sequence
            # to avoid unnecessary flush attempts.
            if self.session_factory is None:
                logger.debug("_maybe_auto_flush: session_factory is None, skipping")
                return
            async with self.session_factory() as check_session:
                check_repo = ChatSessionRepository(check_session)
                chat_session = await check_repo.get_by_id(session_id)
                if not chat_session:
                    logger.debug("_maybe_auto_flush: session %s not found", session_id)
                    return
                last_flushed = chat_session.last_flushed_sequence or 0

                msg_repo = MessageRepository(check_session)
                current_max = await msg_repo.get_max_sequence(session_id)

            gap = current_max - last_flushed
            logger.info(
                "_maybe_auto_flush: session=%s last_flushed=%d current_max=%d gap=%d threshold=%d",
                session_id,
                last_flushed,
                current_max,
                gap,
                _FLUSH_THRESHOLD,
            )
            if gap < _FLUSH_THRESHOLD:
                return

            result = await self.flush_chat_memories(world_id, session_id)
            if result.get("flushed"):
                logger.info(
                    "Auto-flushed memories for session %s: %s",
                    session_id,
                    result.get("characters_updated"),
                )
        except Exception:
            logger.exception("Auto-flush memories failed for session %s", session_id)

    async def flush_chat_memories(
        self, world_id: str, session_id: str, *, force: bool = False
    ) -> dict:
        """批量生成角色聊天的短期记忆。

        幂等性：基于 sequence 追踪，只处理 last_flushed_sequence 之后的消息。
        使用独立 session 避免与请求主 session 事务冲突。

        Args:
            force: 跳过阈值检查，即使未记录消息数 < _FLUSH_THRESHOLD 也执行刷写。
                   用于不活跃会话的定时清理路径。
        """
        from src.db.repositories.character_memory_repo import CharacterMemoryRepository
        from src.db.repositories.character_repo import CharacterRepository

        async with self.session_factory() as session:
            # ── 查 session 参与角色 ───────────────────────────────────
            chat_session_repo = ChatSessionRepository(session)
            chat_session = await chat_session_repo.get_by_id(session_id)
            if not chat_session:
                return {"flushed": False, "reason": "session_not_found"}

            participants = chat_session.participants or []
            if not participants:
                return {"flushed": False, "reason": "no_participants"}

            # ── 查未记录消息（基于 sequence） ─────────────────────────
            message_repo = MessageRepository(session)
            memory_repo = CharacterMemoryRepository(session)

            last_flushed_seq = getattr(chat_session, "last_flushed_sequence", 0) or 0
            unrecorded = await message_repo.list_messages_after_sequence(
                session_id, last_flushed_seq
            )

            if not unrecorded:
                return {"flushed": False, "reason": "no_new_messages"}

            if len(unrecorded) < _FLUSH_THRESHOLD and not force:
                return {
                    "flushed": False,
                    "reason": "below_threshold",
                    "pending_count": len(unrecorded),
                }

            # ── Load characters ──────────────────────────────────────
            char_repo = CharacterRepository(session)
            char_map: dict[str, Character] = {}
            for p in participants:
                if isinstance(p, str):
                    character = await char_repo.get_by_id(p)
                elif isinstance(p, dict):
                    pid = p.get("id")
                    if pid:
                        character = await char_repo.get_by_id(str(pid))
                    else:
                        continue
                else:
                    continue
                if character:
                    char_map[character.name] = character

            if not char_map:
                return {"flushed": False, "reason": "no_characters_found"}

            # ── Build dialogue text ──────────────────────────────────
            _char_id_to_name = {c.id: name for name, c in char_map.items()}
            _sender_type_names = {"system": "系统", "narrator": "旁白", "user": "用户"}
            dialogue_text = "\n".join(
                f"[{_char_id_to_name.get(m.sender_id or '', '') or _sender_type_names.get(m.sender_type, m.sender_type)}] {m.content}"  # noqa: E501
                for m in unrecorded
                if m.sender_type != "system" or m.type != "event"
            )
            event_description = "角色聊天对话"

            # ── Concurrent recheck: another flush may have advanced last_flushed_sequence ──
            # Re-fetch via repo (Pydantic model can't be session.refresh()'d)
            fresh_session = await chat_session_repo.get_by_id(session_id)
            if fresh_session and (fresh_session.last_flushed_sequence or 0) > last_flushed_seq:
                return {"flushed": False, "reason": "already_flushed_by_concurrent"}

            # ── Generate short-term memories via orchestrator ────────
            if self.memory_orchestrator is None:
                return {"flushed": False, "reason": "memory_orchestrator_not_available"}

            # Get embedding provider from dialogue service for memory vector search
            _emb_provider = None
            if self.dialogue_service and self.dialogue_service.element_retrieval_service:
                _emb_provider = self.dialogue_service.element_retrieval_service.embedding_provider

            newly_written = await self.memory_orchestrator.generate_short_term_memories(
                session=session,
                world_id=world_id,
                char_map=char_map,
                dialogue_text=dialogue_text,
                event_description=event_description,
                memory_repo=memory_repo,
                session_id=uuid.UUID(session_id),
                embedding_provider=_emb_provider,
            )

            logger.info(
                "flush_chat_memories: generated %d short-term memories for session %s",
                len(newly_written),
                session_id,
            )

            # ── Check and promote long-term memories if threshold met ──
            # Always check promotion after flush, regardless of newly_written,
            # because there may be existing short-term memories from previous flushes
            # that haven't been promoted yet.
            from src.db.repositories.relation_repo import RelationRepository
            from src.db.repositories.world_repo import WorldRepository

            world_repo = WorldRepository(session)
            relation_repo = RelationRepository(session)
            await self.memory_orchestrator.check_and_promote(
                session=session,
                world_id=world_id,
                char_map=char_map,
                memory_repo=memory_repo,
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )

            # Recover character names from char_map for the response
            characters_updated = []
            for m in newly_written:
                for name, c in char_map.items():
                    if hasattr(m, "character_id") and str(getattr(m, "character_id", "")) == str(
                        c.id
                    ):
                        characters_updated.append(name)
                        break

            # ── Update last_flushed_sequence（仅记忆写入成功时推进） ────
            max_flushed_seq = unrecorded[-1].sequence if unrecorded else last_flushed_seq
            if newly_written and max_flushed_seq and max_flushed_seq > last_flushed_seq:
                await chat_session_repo.update_last_flushed_sequence(session_id, max_flushed_seq)

            await session.commit()

            # ── Memory propagation (async, independent session) ──────
            if newly_written and self.memory_orchestrator is not None:
                task = asyncio.create_task(
                    self.memory_orchestrator.dispatch_chat_propagation(
                        world_id=world_id,
                        session_id=session_id,
                        participant_names=list(char_map.keys()),
                        newly_written_memories=newly_written,
                        virtual_time=datetime.now(UTC),
                    )
                )
                task.add_done_callback(self._task_exception_logger)

            return {"flushed": True, "characters_updated": characters_updated}

    async def flush_inactive_sessions(self) -> dict:
        """定时任务入口：扫描 Redis zset 中超过 10 分钟未活跃的会话，
        对有未记录消息的会话触发记忆写入，写入成功后从 zset 移除。

        Redis 不可用时静默降级（不做任何操作）。
        """
        if self._redis is None:
            return {"processed": 0, "reason": "redis_unavailable"}

        if self.session_factory is None or self.llm is None:
            return {"processed": 0, "reason": "service_not_ready"}

        try:
            now_ts = datetime.now(UTC).timestamp()
            cutoff_ts = now_ts - _INACTIVE_THRESHOLD_SECONDS
            stale_sessions = cast(
                "list[bytes | str]",
                await self._redis.zrangebyscore(_ACTIVE_SESSIONS_KEY, 0, cutoff_ts),
            )
        except Exception:
            logger.debug("Redis ZRANGEBYSCORE failed for active_chat_sessions")
            return {"processed": 0, "reason": "redis_error"}

        _log_level = logging.DEBUG if not stale_sessions else logging.INFO
        logger.log(
            _log_level,
            "[flush_inactive] now=%.0f cutoff=%.0f threshold=%ds, found %d stale sessions",
            now_ts,
            cutoff_ts,
            _INACTIVE_THRESHOLD_SECONDS,
            len(stale_sessions),
        )

        if not stale_sessions:
            return {"processed": 0, "reason": "no_inactive_sessions"}

        processed = 0
        flushed = 0
        for raw_sid in stale_sessions:
            sid = raw_sid.decode() if isinstance(raw_sid, bytes) else raw_sid
            try:
                # Check if session has memories enabled and unrecorded messages
                async with self.session_factory() as check_session:
                    check_repo = ChatSessionRepository(check_session)
                    chat_session = await check_repo.get_by_id(sid)
                    if not chat_session:
                        # Session gone, remove from zset
                        await self._redis.zrem(_ACTIVE_SESSIONS_KEY, sid)
                        continue
                    if not chat_session.memories_enabled:
                        # Memories not enabled, just remove from zset
                        logger.info(
                            "[flush_inactive] session %s: "
                            "memories_enabled=False, removing from zset",
                            sid,
                        )
                        await self._redis.zrem(_ACTIVE_SESSIONS_KEY, sid)
                        continue

                    msg_repo = MessageRepository(check_session)
                    last_flushed = chat_session.last_flushed_sequence or 0
                    current_max = await msg_repo.get_max_sequence(sid)
                    world_id = str(chat_session.world_id)

                    logger.info(
                        "[flush_inactive] session %s: memories_enabled=True, "
                        "last_flushed=%d, current_max=%d, gap=%d, world=%s",
                        sid,
                        last_flushed,
                        current_max,
                        current_max - last_flushed,
                        world_id,
                    )

                if current_max <= last_flushed:
                    # No unrecorded messages, remove from zset
                    await self._redis.zrem(_ACTIVE_SESSIONS_KEY, sid)
                    continue

                logger.info(
                    "[flush_inactive] session %s: %d unrecorded messages "
                    "(last_flushed=%d, current_max=%d), calling flush_chat_memories(force=True)",
                    sid,
                    current_max - last_flushed,
                    last_flushed,
                    current_max,
                )

                # Has unrecorded messages — trigger flush (force=True to bypass threshold)
                result = await self.flush_chat_memories(world_id, sid, force=True)
                processed += 1
                if result.get("flushed"):
                    flushed += 1
                    logger.info(
                        "Inactive session flush: session %s flushed (%s)",
                        sid,
                        result.get("characters_updated"),
                    )
                else:
                    logger.info(
                        "Inactive session flush: session %s not flushed, reason=%s",
                        sid,
                        result.get("reason"),
                    )

                # Remove from zset regardless of flush outcome
                # (it will be re-added if the user sends another message)
                await self._redis.zrem(_ACTIVE_SESSIONS_KEY, sid)
            except Exception:
                logger.exception("flush_inactive_sessions failed for session %s", sid)
                # Still try to remove from zset to avoid repeated failures
                try:
                    await self._redis.zrem(_ACTIVE_SESSIONS_KEY, sid)
                except Exception:
                    pass

        return {"processed": processed, "flushed": flushed}
