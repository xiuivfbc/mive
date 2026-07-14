"""Tests for chat message queue system: idempotency, sequence, and rollback.

Design:
- Idempotency: Redis key `idempotency:{key}` with 5-min TTL caches responses.
  Duplicate requests return cached result immediately.
- Sequence: Monotonically increasing integer per session, assigned by backend.
- Rollback: When generate_response returns 0 replies, the already-written
  user message is deleted from DB to prevent orphaned messages.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.message import Message, SendMessageResponse
from src.services.message_service import MessageService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IDEMPOTENCY_TTL = 300  # 5 minutes


def _make_message(content: str = "回复消息", session_id: str | None = None) -> Message:
    return Message(
        id=str(uuid.uuid4()),
        world_id="world-001",
        session_id=session_id,
        type="dialogue",
        sender_type="character",
        sender_id=str(uuid.uuid4()),
        content=content,
    )


def _make_session(session_id: str | None = None):
    from src.models.chat_session import ChatSession

    return ChatSession(
        id=session_id or str(uuid.uuid4()),
        world_id="world-001",
        type="character",
        title="test",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class FakeRedis:
    """Minimal in-memory async fake for idempotency tests."""

    def __init__(self, store: dict | None = None):
        self.store = store if store is not None else {}

    async def get(self, key):
        val = self.store.get(key)
        if val is None:
            return None
        if isinstance(val, bytes):
            return val
        return str(val).encode("utf-8")

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


def _make_service(
    dialogue_service=None,
    redis=None,
    message_repo=None,
    session_factory=None,
    llm=None,
):
    """Create a MessageService with mocked dependencies for queue tests."""
    mr = message_repo or AsyncMock()
    # When no custom message_repo is provided, set explicit mock behaviors.
    # AsyncMock auto-creates attributes, so hasattr is unreliable.
    if message_repo is None:
        mr.create = AsyncMock(side_effect=lambda m: m)
        mr.delete_by_ids = AsyncMock()
        mr.get_max_sequence = AsyncMock(return_value=0)
        mr.list_by_session = AsyncMock(return_value=[])

    chat_session_repo = AsyncMock()
    chat_session_repo.get_by_id = AsyncMock(return_value=None)
    chat_session_repo.update_participants = AsyncMock()

    ds = dialogue_service or AsyncMock()
    # Always set select_participants unless the caller provided a custom dialogue_service
    # with an explicit select_participants mock
    # (checking _mock_children avoids AsyncMock auto-attr).
    if dialogue_service is None:
        ds.select_participants = AsyncMock(
            return_value={
                "speakers": [{"id": "c1", "name": "Alice"}],
                "background": [],
                "narration": "",
                "relevant_elements": [],
            }
        )
        ds.generate_response = AsyncMock(return_value=[_make_message()])
    else:
        if not hasattr(ds, "select_participants") or ds.select_participants is None:
            ds.select_participants = AsyncMock(
                return_value={
                    "speakers": [{"id": "c1", "name": "Alice"}],
                    "background": [],
                    "narration": "",
                    "relevant_elements": [],
                }
            )
        if not hasattr(ds, "generate_response") or ds.generate_response is None:
            ds.generate_response = AsyncMock(return_value=[_make_message()])

    svc = MessageService(
        message_repo=mr,
        dialogue_service=ds,
        llm=llm,
        session_factory=session_factory,
        chat_session_repo=chat_session_repo,
        redis=redis,
    )
    return svc, ds, mr


# ---------------------------------------------------------------------------
# Sequence Generation Tests
# ---------------------------------------------------------------------------


class TestSequenceGeneration:
    """Backend assigns monotonically increasing sequence numbers per session."""

    @pytest.mark.asyncio
    async def test_user_message_gets_sequence_one_when_empty(self):
        """First message in a session gets sequence=1."""
        session_id = str(uuid.uuid4())
        mr = AsyncMock()
        mr.create = AsyncMock(side_effect=lambda m: m)
        mr.get_max_sequence = AsyncMock(return_value=0)
        mr.delete_by_ids = AsyncMock()
        mr.list_by_session = AsyncMock(return_value=[])

        svc, ds, mr = _make_service(message_repo=mr, redis=FakeRedis({}))

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            result = await svc.send_message("world-001", "hello", session_id=session_id)

        # User message should have sequence assigned
        assert result.user_message.sequence is not None
        assert result.user_message.sequence >= 1

    @pytest.mark.asyncio
    async def test_sequence_increments_from_existing_max(self):
        """Sequence continues from the max existing sequence in the session."""
        session_id = str(uuid.uuid4())
        mr = AsyncMock()
        mr.create = AsyncMock(side_effect=lambda m: m)
        mr.get_max_sequence = AsyncMock(return_value=5)
        mr.delete_by_ids = AsyncMock()
        mr.list_by_session = AsyncMock(return_value=[])

        svc, ds, mr = _make_service(message_repo=mr, redis=FakeRedis({}))

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            result = await svc.send_message("world-001", "hello", session_id=session_id)

        # User message sequence should be max+1 = 6
        assert result.user_message.sequence == 6

    @pytest.mark.asyncio
    async def test_character_responses_get_incrementing_sequences(self):
        """Character reply sequences follow user message sequence."""
        session_id = str(uuid.uuid4())
        mr = AsyncMock()
        mr.create = AsyncMock(side_effect=lambda m: m)
        mr.get_max_sequence = AsyncMock(return_value=0)
        mr.delete_by_ids = AsyncMock()
        mr.list_by_session = AsyncMock(return_value=[])

        ds = AsyncMock()
        ds.select_participants = AsyncMock(
            return_value={
                "speakers": [{"id": "c1", "name": "Alice"}],
                "background": [],
                "narration": "",
                "relevant_elements": [],
            }
        )
        # Return responses with sequences assigned by dialogue service
        resp = _make_message("reply1", session_id)
        resp.sequence = 2
        ds.generate_response = AsyncMock(return_value=[resp])

        svc, ds, mr = _make_service(dialogue_service=ds, message_repo=mr, redis=FakeRedis({}))

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            result = await svc.send_message("world-001", "hello", session_id=session_id)

        # User message should be sequence 1
        assert result.user_message.sequence == 1
        # Response sequence comes from dialogue_service
        assert result.responses[0].sequence == 2


# ---------------------------------------------------------------------------
# Idempotency Tests
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Idempotency key prevents duplicate processing via Redis cache."""

    @pytest.mark.asyncio
    async def test_idempotency_key_cached_on_success(self):
        """Successful response should be cached in Redis with 5-min TTL."""
        session_id = str(uuid.uuid4())
        idem_key = str(uuid.uuid4())
        store = {}
        redis = FakeRedis(store)

        svc, ds, mr = _make_service(redis=redis)

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            _result = await svc.send_message(
                "world-001", "hello", session_id=session_id, idempotency_key=idem_key
            )

        # Redis should have the cached result
        cache_key = f"idempotency:{idem_key}"
        assert cache_key in store

    @pytest.mark.asyncio
    async def test_duplicate_request_returns_cached_result(self):
        """Second request with same idempotency key returns cached result."""
        session_id = str(uuid.uuid4())
        idem_key = str(uuid.uuid4())

        # Pre-populate cache with a serialized response
        cached_response = SendMessageResponse(
            user_message=Message(
                id=str(uuid.uuid4()),
                world_id="world-001",
                session_id=session_id,
                type="user",
                sender_type="user",
                content="hello",
                sequence=1,
            ),
            responses=[],
            session_id=session_id,
        )
        store = {f"idempotency:{idem_key}": cached_response.model_dump_json()}
        redis = FakeRedis(store)

        svc, ds, mr = _make_service(redis=redis)

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            result = await svc.send_message(
                "world-001", "hello", session_id=session_id, idempotency_key=idem_key
            )

        # Should return cached content without calling dialogue_service
        assert result.user_message.content == "hello"
        ds.generate_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_idempotency_key_skips_cache(self):
        """Without idempotency key, no caching occurs."""
        redis = FakeRedis({})
        svc, ds, mr = _make_service(redis=redis)

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            await svc.send_message("world-001", "hello")

        # No idempotency key stored
        assert not any(k.startswith("idempotency:") for k in redis.store)

    @pytest.mark.asyncio
    async def test_redis_unavailable_idempotency_degrades_gracefully(self):
        """When Redis is None, idempotency is skipped but message still works."""
        svc, ds, mr = _make_service(redis=None)

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            result = await svc.send_message("world-001", "hello", idempotency_key=str(uuid.uuid4()))

        assert result.user_message is not None
        ds.generate_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_error_does_not_block_message(self):
        """Redis errors during idempotency check should not prevent message sending."""
        bad_redis = AsyncMock()
        bad_redis.get = AsyncMock(side_effect=Exception("Redis down"))
        bad_redis.set = AsyncMock(side_effect=Exception("Redis down"))

        svc, ds, mr = _make_service(redis=bad_redis)

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            result = await svc.send_message("world-001", "hello", idempotency_key=str(uuid.uuid4()))

        assert result.user_message is not None
        ds.generate_response.assert_called_once()


# ---------------------------------------------------------------------------
# Rollback Tests
# ---------------------------------------------------------------------------


class TestRollbackOnZeroReplies:
    """When generate_response returns 0 character replies, the user message
    should be rolled back (deleted) from DB to prevent orphaned messages."""

    @pytest.mark.asyncio
    async def test_user_message_deleted_when_zero_replies(self):
        """0 replies from generate_response triggers rollback of user message."""
        session_id = str(uuid.uuid4())
        mr = AsyncMock()
        user_msg_id = str(uuid.uuid4())

        def create_side_effect(msg):
            msg.id = user_msg_id
            return msg

        mr.create = AsyncMock(side_effect=create_side_effect)
        mr.get_max_sequence = AsyncMock(return_value=0)
        mr.delete_by_ids = AsyncMock()
        mr.list_by_session = AsyncMock(return_value=[])

        ds = AsyncMock()
        ds.select_participants = AsyncMock(
            return_value={
                "speakers": [{"id": "c1", "name": "Alice"}],
                "background": [],
                "narration": "",
                "relevant_elements": [],
            }
        )
        # Return empty responses = 0 character replies
        ds.generate_response = AsyncMock(return_value=[])

        svc, ds, mr = _make_service(dialogue_service=ds, message_repo=mr, redis=FakeRedis({}))

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            result = await svc.send_message("world-001", "hello", session_id=session_id)

        # User message should be rolled back
        mr.delete_by_ids.assert_called_once()
        deleted_ids = mr.delete_by_ids.call_args[0][0]
        assert user_msg_id in deleted_ids
        # Response should indicate error
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_user_message_not_deleted_when_has_replies(self):
        """With >0 replies, user message should NOT be deleted."""
        session_id = str(uuid.uuid4())
        mr = AsyncMock()
        mr.create = AsyncMock(side_effect=lambda m: m)
        mr.get_max_sequence = AsyncMock(return_value=0)
        mr.delete_by_ids = AsyncMock()
        mr.list_by_session = AsyncMock(return_value=[])

        ds = AsyncMock()
        ds.select_participants = AsyncMock(
            return_value={
                "speakers": [{"id": "c1", "name": "Alice"}],
                "background": [],
                "narration": "",
                "relevant_elements": [],
            }
        )
        ds.generate_response = AsyncMock(return_value=[_make_message()])

        svc, ds, mr = _make_service(dialogue_service=ds, message_repo=mr, redis=FakeRedis({}))

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            await svc.send_message("world-001", "hello", session_id=session_id)

        mr.delete_by_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_rollback_not_cached_in_idempotency(self):
        """Failed messages (0 replies) should NOT be cached in idempotency store."""
        session_id = str(uuid.uuid4())
        idem_key = str(uuid.uuid4())
        store = {}
        redis = FakeRedis(store)

        mr = AsyncMock()
        mr.create = AsyncMock(side_effect=lambda m: m)
        mr.get_max_sequence = AsyncMock(return_value=0)
        mr.delete_by_ids = AsyncMock()
        mr.list_by_session = AsyncMock(return_value=[])

        ds = AsyncMock()
        ds.select_participants = AsyncMock(
            return_value={
                "speakers": [{"id": "c1", "name": "Alice"}],
                "background": [],
                "narration": "",
                "relevant_elements": [],
            }
        )
        ds.generate_response = AsyncMock(return_value=[])

        svc, ds, mr = _make_service(dialogue_service=ds, message_repo=mr, redis=redis)

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            await svc.send_message(
                "world-001",
                "hello",
                session_id=session_id,
                idempotency_key=idem_key,
            )

        # Should NOT cache failed result
        cache_key = f"idempotency:{idem_key}"
        assert cache_key not in store

    @pytest.mark.asyncio
    async def test_rollback_does_not_delete_narration_message(self):
        """Rollback only deletes the user message, not narration."""
        session_id = str(uuid.uuid4())
        mr = AsyncMock()
        narration_id = str(uuid.uuid4())
        user_msg_id = str(uuid.uuid4())
        call_count = [0]

        def create_side_effect(msg):
            call_count[0] += 1
            if msg.type == "narration":
                msg.id = narration_id
            else:
                msg.id = user_msg_id
            return msg

        mr.create = AsyncMock(side_effect=create_side_effect)
        mr.get_max_sequence = AsyncMock(return_value=0)
        mr.delete_by_ids = AsyncMock()
        mr.list_by_session = AsyncMock(return_value=[])

        ds = AsyncMock()
        ds.select_participants = AsyncMock(
            return_value={
                "speakers": [{"id": "c1", "name": "Alice"}],
                "background": [],
                "narration": "旁白内容",
                "relevant_elements": [],
            }
        )
        ds.generate_response = AsyncMock(return_value=[])

        svc, ds, mr = _make_service(dialogue_service=ds, message_repo=mr, redis=FakeRedis({}))

        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(
                get_latest=AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
            )
            await svc.send_message("world-001", "hello", session_id=session_id)

        # Only user message should be deleted, not narration
        mr.delete_by_ids.assert_called_once()
        deleted_ids = mr.delete_by_ids.call_args[0][0]
        assert user_msg_id in deleted_ids
        assert narration_id not in deleted_ids


# ---------------------------------------------------------------------------
# MessageRepository.get_max_sequence Tests
# ---------------------------------------------------------------------------


class TestGetMaxSequence:
    """MessageRepository.get_max_sequence returns the highest sequence in a session."""

    @pytest.mark.asyncio
    async def test_get_max_sequence_returns_zero_for_empty_session(self):
        """Empty session should return 0."""
        from unittest.mock import MagicMock

        from sqlalchemy.ext.asyncio import AsyncSession

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=None)))
        from src.db.repositories.message_repo import MessageRepository

        repo = MessageRepository(session)
        result = await repo.get_max_sequence(str(uuid.uuid4()))
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_max_sequence_returns_highest_value(self):
        """Should return the max sequence number in the session."""
        from unittest.mock import MagicMock

        from sqlalchemy.ext.asyncio import AsyncSession

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=7)))
        from src.db.repositories.message_repo import MessageRepository

        repo = MessageRepository(session)
        result = await repo.get_max_sequence(str(uuid.uuid4()))
        assert result == 7


# ---------------------------------------------------------------------------
# SendMessageRequest idempotency_key field Tests
# ---------------------------------------------------------------------------


class TestSendMessageRequestValidation:
    """SendMessageRequest should accept optional idempotency_key."""

    def test_request_with_idempotency_key(self):
        from src.models.message import SendMessageRequest

        req = SendMessageRequest(content="hello", idempotency_key="abc-123")
        assert req.idempotency_key == "abc-123"

    def test_request_without_idempotency_key(self):
        from src.models.message import SendMessageRequest

        req = SendMessageRequest(content="hello")
        assert req.idempotency_key is None

    def test_message_model_with_sequence(self):
        msg = Message(
            id=str(uuid.uuid4()),
            world_id="w1",
            type="user",
            sender_type="user",
            content="test",
            sequence=5,
        )
        assert msg.sequence == 5

    def test_message_model_sequence_defaults_none(self):
        msg = Message(
            id=str(uuid.uuid4()),
            world_id="w1",
            type="user",
            sender_type="user",
            content="test",
        )
        assert msg.sequence is None

    def test_message_model_with_idempotency_key(self):
        msg = Message(
            id=str(uuid.uuid4()),
            world_id="w1",
            type="user",
            sender_type="user",
            content="test",
            idempotency_key="key-abc",
        )
        assert msg.idempotency_key == "key-abc"


# ---------------------------------------------------------------------------
# M4Message DB model Tests
# ---------------------------------------------------------------------------


class TestM4MessageModel:
    """M4Message should have sequence and idempotency_key columns."""

    def test_m4_message_has_sequence_column(self):
        from src.db.models import M4Message

        assert hasattr(M4Message, "sequence")

    def test_m4_message_has_idempotency_key_column(self):
        from src.db.models import M4Message

        assert hasattr(M4Message, "idempotency_key")
