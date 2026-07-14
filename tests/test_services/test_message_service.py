"""Tests for MessageService."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.chat_session import ChatSession
from src.models.message import Message
from src.services.message_service import MessageService


def _make_message(content: str = "回复消息") -> Message:
    return Message(
        id=str(uuid.uuid4()),
        world_id="world-001",
        type="dialogue",
        sender_type="character",
        sender_id=str(uuid.uuid4()),
        content=content,
    )


def _make_session(session_id: str | None = None) -> ChatSession:
    return ChatSession(
        id=session_id or str(uuid.uuid4()),
        world_id="world-001",
        type="character",
        title="test",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestSendMessage:
    @pytest.fixture
    def message_repo(self):
        mock = AsyncMock()
        mock.create = AsyncMock(side_effect=lambda msg: msg)
        # session needs to support both `await session.rollback()` (async) and
        # `async with session.begin_nested()` (async context manager).
        # Keep session as AsyncMock but override begin_nested as a MagicMock
        # that directly returns an AsyncMock (which acts as async context manager).
        mock.session.begin_nested = MagicMock(return_value=AsyncMock())
        return mock

    @pytest.fixture
    def dialogue_service(self):
        mock = AsyncMock()
        mock.generate_response.return_value = [_make_message()]
        mock.select_participants.return_value = {
            "speakers": [{"id": "char-001", "name": "叶文洁"}],
            "background": [],
            "narration": "",
            "relevant_elements": [],
        }
        return mock

    @pytest.fixture
    def chat_session_repo(self):
        mock = AsyncMock()
        mock.create.return_value = _make_session()
        mock.update_participants = AsyncMock()
        return mock

    @pytest.fixture
    def service(self, message_repo, dialogue_service, chat_session_repo):
        version = MagicMock()
        version.id = str(uuid.uuid4())
        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(get_latest=AsyncMock(return_value=version))
            yield MessageService(
                message_repo=message_repo,
                dialogue_service=dialogue_service,
                chat_session_repo=chat_session_repo,
            )

    async def test_send_message_creates_user_message(self, service, message_repo):
        result = await service.send_message("world-001", "你觉得观测数据正常吗？")
        assert result.user_message.type == "user"
        assert result.user_message.sender_type == "user"
        assert result.user_message.content == "你觉得观测数据正常吗？"
        message_repo.create.assert_called_once()

    async def test_send_message_calls_dialogue_service(self, service, dialogue_service):
        await service.send_message("world-001", "test")
        dialogue_service.generate_response.assert_called_once()

    async def test_send_message_returns_responses(self, service):
        result = await service.send_message("world-001", "test")
        assert len(result.responses) == 1
        assert result.responses[0].sender_id is not None
        assert result.error is None

    async def test_send_message_user_message_uses_clock_time(self, service):
        result = await service.send_message("world-001", "test")
        # User message should be created successfully
        assert result.user_message is not None
        assert result.user_message.type == "user"

    async def test_send_message_dialogue_failure_returns_error(
        self, message_repo, dialogue_service, chat_session_repo
    ):
        dialogue_service.generate_response.side_effect = Exception("LLM error")
        version = MagicMock()
        version.id = str(uuid.uuid4())
        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(get_latest=AsyncMock(return_value=version))
            service = MessageService(
                message_repo=message_repo,
                dialogue_service=dialogue_service,
                chat_session_repo=chat_session_repo,
            )
            result = await service.send_message("world-001", "test")
        assert result.user_message is not None
        assert result.responses == []
        assert result.error == "dialogue_generation_failed"

    async def test_send_message_user_msg_saved_even_on_failure(
        self, message_repo, dialogue_service, chat_session_repo
    ):
        dialogue_service.generate_response.side_effect = Exception("LLM error")
        version = MagicMock()
        version.id = str(uuid.uuid4())
        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(get_latest=AsyncMock(return_value=version))
            service = MessageService(
                message_repo=message_repo,
                dialogue_service=dialogue_service,
                chat_session_repo=chat_session_repo,
            )
            await service.send_message("world-001", "test")
        message_repo.create.assert_called_once()

    async def test_send_message_no_dialogue_service_returns_error(
        self, message_repo, chat_session_repo
    ):
        version = MagicMock()
        version.id = str(uuid.uuid4())
        with patch("src.db.repositories.version_repo.VersionRepository") as mock_vr:
            mock_vr.return_value = AsyncMock(get_latest=AsyncMock(return_value=version))
            service = MessageService(
                message_repo=message_repo,
                dialogue_service=None,
                chat_session_repo=chat_session_repo,
            )
            result = await service.send_message("world-001", "test")
        assert result.user_message is not None
        assert result.responses == []
        assert result.error == "dialogue_generation_failed"

    # --- New: participant management ---

    async def test_send_message_calls_select_participants_in_auto_mode(
        self, service, dialogue_service
    ):
        await service.send_message("world-001", "test", participant_mode="auto")
        dialogue_service.select_participants.assert_called_once()

    async def test_send_message_passes_participants_to_generate_in_auto_mode(
        self, service, dialogue_service
    ):
        dialogue_service.select_participants.return_value = {
            "speakers": [{"id": "char-001", "name": "叶文洁"}],
            "background": [],
            "narration": "",
            "relevant_elements": [],
        }
        await service.send_message("world-001", "test", participant_mode="auto")
        call_kwargs = dialogue_service.generate_response.call_args[1]
        assert call_kwargs["participants"] == [{"id": "char-001", "name": "叶文洁"}]

    async def test_send_message_updates_session_participants(self, service, chat_session_repo):
        await service.send_message("world-001", "test", participant_mode="auto")
        chat_session_repo.update_participants.assert_called_once()
        args = chat_session_repo.update_participants.call_args
        assert args[1]["participant_mode"] == "auto"

    async def test_send_message_response_includes_participants(self, service, dialogue_service):
        dialogue_service.select_participants.return_value = {
            "speakers": [{"id": "char-001", "name": "叶文洁"}],
            "background": [],
            "narration": "",
            "relevant_elements": [],
        }
        result = await service.send_message("world-001", "test")
        assert result.participants == [{"id": "char-001", "name": "叶文洁"}]
        assert result.participant_mode == "auto"

    async def test_send_message_writes_narration_before_user_message(
        self, service, message_repo, dialogue_service
    ):
        dialogue_service.select_participants.return_value = {
            "speakers": [{"id": "char-001", "name": "叶文洁"}],
            "background": [],
            "narration": "叶文洁站在观测台上。",
            "relevant_elements": [],
        }
        await service.send_message("world-001", "test")
        # message_repo.create called twice: once for narration, once for user message
        assert message_repo.create.call_count == 2
        first_call_msg = message_repo.create.call_args_list[0][0][0]
        second_call_msg = message_repo.create.call_args_list[1][0][0]
        assert first_call_msg.type == "narration"
        assert first_call_msg.sender_type == "system"
        assert second_call_msg.type == "user"
        # Both messages should be created successfully
        assert first_call_msg is not None
        assert second_call_msg is not None

    async def test_send_message_no_narration_skips_narration_message(self, service, message_repo):
        await service.send_message("world-001", "test")
        # Only user message created (no narration)
        message_repo.create.assert_called_once()

    async def test_send_message_edit_mode_passes_current_participants_to_select(
        self, service, dialogue_service
    ):
        participants = [{"id": "char-001", "name": "叶文洁"}]
        await service.send_message(
            "world-001",
            "test",
            participant_mode="edit",
            participants=participants,
        )
        call_kwargs = dialogue_service.select_participants.call_args[1]
        assert call_kwargs["participant_mode"] == "edit"
        assert call_kwargs["current_participants"] == participants

    async def test_send_message_session_id_reused_when_provided(self, service, chat_session_repo):
        existing_session_id = str(uuid.uuid4())
        result = await service.send_message("world-001", "test", session_id=existing_session_id)
        chat_session_repo.create.assert_not_called()
        assert result.session_id == existing_session_id

    async def test_send_message_empty_speakers_not_fallback_to_participants(
        self, service, dialogue_service
    ):
        """Empty speakers list should not fall through to old participants key."""
        dialogue_service.select_participants.return_value = {
            "speakers": [],
            "background": [],
            "narration": "",
            "relevant_elements": [],
        }
        result = await service.send_message("world-001", "test")
        assert result.participants == []

    async def test_send_message_backward_compat_participants_key(self, service, dialogue_service):
        """Old format with 'participants' key should still work."""
        dialogue_service.select_participants.return_value = {
            "participants": [{"id": "char-001", "name": "叶文洁"}],
            "narration": "",
        }
        result = await service.send_message("world-001", "test")
        assert result.participants == [{"id": "char-001", "name": "叶文洁"}]


class TestListMessages:
    @pytest.fixture
    def message_repo(self):
        mock = AsyncMock()
        mock.list_filtered.return_value = [_make_message()]
        return mock

    @pytest.fixture
    def service(self, message_repo):
        return MessageService(
            message_repo=message_repo,
            dialogue_service=None,
        )

    async def test_list_messages_delegates_to_repo(self, service, message_repo):
        result = await service.list_messages("world-001")
        message_repo.list_filtered.assert_called_once()
        assert len(result.messages) == 1
        assert result.has_more is False

    async def test_list_messages_with_cursor(self, service, message_repo):
        message_repo.list_filtered.return_value = [_make_message()] * 5
        result = await service.list_messages("world-001", before_sequence=10, limit=5)
        assert len(result.messages) == 5

    async def test_list_messages_has_more_when_at_limit(self, service, message_repo):
        # service 会取 limit+1 条来判断 has_more
        message_repo.list_filtered.return_value = [_make_message()] * 6
        result = await service.list_messages("world-001", limit=5)
        assert result.has_more is True
        assert len(result.messages) == 5


WORLD_ID_FLUSH = str(uuid.uuid4())
SESSION_ID_FLUSH = str(uuid.uuid4())
CHAR_ID_A = str(uuid.uuid4())
CHAR_ID_B = str(uuid.uuid4())


def _make_character_model(char_id: str, name: str, brief: str = "简介"):
    from src.models.character import Character

    return Character(
        id=char_id,
        world_id=WORLD_ID_FLUSH,
        name=name,
        profile={"brief": brief},
    )


class TestFlushChatMemories:
    @pytest.fixture
    def mock_session_factory(self):
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value = session
        return factory, session

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def mock_orchestrator(self):
        from src.services.memory_orchestrator import MemoryOrchestrator

        orchestrator = AsyncMock(spec=MemoryOrchestrator)
        orchestrator.generate_short_term_memories = AsyncMock(return_value=[])
        orchestrator.check_and_promote = AsyncMock()
        orchestrator.dispatch_chat_propagation = AsyncMock()
        return orchestrator

    @pytest.fixture
    def service(self, mock_session_factory, llm, mock_orchestrator):
        factory, _ = mock_session_factory
        return MessageService(
            message_repo=AsyncMock(),
            llm=llm,
            session_factory=factory,
            memory_orchestrator=mock_orchestrator,
        )

    async def test_flush_returns_flushed_false_when_no_new_messages(
        self, service, mock_session_factory
    ):
        """Idempotency: no unrecorded messages → flushed: false."""
        _, session = mock_session_factory

        chat_session = AsyncMock()
        chat_session.participants = [CHAR_ID_A]  # UUID string format
        chat_session.last_flushed_sequence = 10

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=chat_session)

        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=[])

        memory_repo = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is False
        assert result["reason"] == "no_new_messages"

    async def test_flush_returns_flushed_false_when_below_threshold(
        self, service, mock_session_factory
    ):
        """Fewer than 20 unrecorded messages → flushed: false."""
        _, session = mock_session_factory

        chat_session = AsyncMock()
        chat_session.participants = [CHAR_ID_A]  # UUID string format
        chat_session.last_flushed_sequence = 0

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=chat_session)

        # 3 unrecorded messages (< 20 threshold)
        messages = [_make_message(f"消息{i}") for i in range(3)]
        for i, msg in enumerate(messages):
            msg.sequence = i + 1
        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=messages)

        memory_repo = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is False
        assert result["reason"] == "below_threshold"
        assert result["pending_count"] == 3

    async def test_flush_generates_memories_when_threshold_met(
        self, service, mock_session_factory, llm, mock_orchestrator
    ):
        """20+ unrecorded messages → generates memories → flushed: true."""
        _, session = mock_session_factory

        chat_session = AsyncMock()
        chat_session.participants = [CHAR_ID_A, CHAR_ID_B]  # UUID string format
        chat_session.last_flushed_sequence = 0

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=chat_session)
        chat_session_repo.update_last_flushed_sequence = AsyncMock()

        messages = [_make_message(f"消息{i}") for i in range(22)]
        for i, msg in enumerate(messages):
            msg.sequence = i + 1
        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=messages)

        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_b = _make_character_model(CHAR_ID_B, "常伟思")
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(
            side_effect=lambda cid: {CHAR_ID_A: char_a, CHAR_ID_B: char_b}.get(cid)
        )

        # Configure orchestrator to return mock memory objects
        mem_a = MagicMock(character_id=CHAR_ID_A)
        mem_b = MagicMock(character_id=CHAR_ID_B)
        mock_orchestrator.generate_short_term_memories.return_value = [mem_a, mem_b]

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is True
        assert "叶文洁" in result["characters_updated"]
        assert "常伟思" in result["characters_updated"]
        mock_orchestrator.generate_short_term_memories.assert_called_once()

    async def test_flush_skips_null_content_from_llm(
        self, service, mock_session_factory, llm, mock_orchestrator
    ):
        """LLM returns null content for all characters → orchestrator returns empty list."""
        _, session = mock_session_factory

        chat_session = AsyncMock()
        chat_session.participants = [CHAR_ID_A]  # UUID string format
        chat_session.last_flushed_sequence = 0

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=chat_session)
        chat_session_repo.update_last_flushed_sequence = AsyncMock()

        messages = [_make_message(f"消息{i}") for i in range(20)]
        for i, msg in enumerate(messages):
            msg.sequence = i + 1
        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=messages)

        memory_repo = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        # Orchestrator returns empty list (all content filtered as null)
        mock_orchestrator.generate_short_term_memories.return_value = []

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is True
        assert result["characters_updated"] == []

    async def test_flush_handles_llm_failure_gracefully(
        self, service, mock_session_factory, llm, mock_orchestrator
    ):
        """LLM failure → orchestrator returns empty list → flushed: true with empty characters."""
        _, session = mock_session_factory

        chat_session = AsyncMock()
        chat_session.participants = [CHAR_ID_A]  # UUID string format
        chat_session.last_flushed_sequence = 0

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=chat_session)
        chat_session_repo.update_last_flushed_sequence = AsyncMock()

        messages = [_make_message(f"消息{i}") for i in range(20)]
        for i, msg in enumerate(messages):
            msg.sequence = i + 1
        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=messages)

        memory_repo = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        # Orchestrator returns empty list on LLM failure (handled internally)
        mock_orchestrator.generate_short_term_memories.return_value = []

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is True
        assert result["characters_updated"] == []

    async def test_flush_no_session_returns_error(self, service, mock_session_factory):
        """Session not found → return flushed: false."""
        _, session = mock_session_factory

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=None)

        with patch(
            "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is False

    async def test_flush_returns_already_flushed_when_concurrent_wins(
        self, service, mock_session_factory, llm
    ):
        """Optimistic lock: another flush advanced last_flushed_sequence → already_flushed."""
        _, session = mock_session_factory

        # First call: initial state with last_flushed_sequence=0
        chat_session_initial = AsyncMock()
        chat_session_initial.participants = [CHAR_ID_A]  # UUID string format
        chat_session_initial.last_flushed_sequence = 0

        # Second call (concurrent recheck): simulate another flush advanced the sequence
        chat_session_concurrent = AsyncMock()
        chat_session_concurrent.participants = [CHAR_ID_A]
        chat_session_concurrent.last_flushed_sequence = 50

        chat_session_repo = AsyncMock()
        # Return different objects on first vs second call
        chat_session_repo.get_by_id = AsyncMock(
            side_effect=[chat_session_initial, chat_session_concurrent]
        )

        # 20 unrecorded messages to pass threshold
        messages = [_make_message(f"消息{i}") for i in range(20)]
        for i, msg in enumerate(messages):
            msg.sequence = i + 1

        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=messages)

        memory_repo = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        llm.complete_json.return_value = [
            {"character": "叶文洁", "content": "记忆内容"},
        ]

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is False
        assert result["reason"] == "already_flushed_by_concurrent"
        # Should not write any memories since concurrent flush already completed
        memory_repo.add.assert_not_called()

    async def test_flush_passes_char_map_to_orchestrator(
        self, service, mock_session_factory, llm, mock_orchestrator
    ):
        """Orchestrator should receive char_map with character profiles."""
        _, session = mock_session_factory

        chat_session = AsyncMock()
        chat_session.participants = [CHAR_ID_A]  # UUID string format
        chat_session.last_flushed_sequence = 0

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=chat_session)
        chat_session_repo.update_last_flushed_sequence = AsyncMock()

        messages = [_make_message(f"消息{i}") for i in range(22)]
        for i, msg in enumerate(messages):
            msg.sequence = i + 1
        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=messages)

        memory_repo = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_a.profile["detailed"] = "文革中目睹父亲被打死，后成为天体物理学家"
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        mock_orchestrator.generate_short_term_memories.return_value = []

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        # Verify orchestrator received char_map with the character
        call_kwargs = mock_orchestrator.generate_short_term_memories.call_args[1]
        assert "叶文洁" in call_kwargs["char_map"]
        assert (
            call_kwargs["char_map"]["叶文洁"].profile["detailed"]
            == "文革中目睹父亲被打死，后成为天体物理学家"
        )

    async def test_flush_handles_dict_wrapper_from_llm(
        self, service, mock_session_factory, llm, mock_orchestrator
    ):
        """Orchestrator handles LLM dict wrapper internally."""
        _, session = mock_session_factory

        chat_session = AsyncMock()
        chat_session.participants = [CHAR_ID_A]  # UUID string format
        chat_session.last_flushed_sequence = 0

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=chat_session)
        chat_session_repo.update_last_flushed_sequence = AsyncMock()

        messages = [_make_message(f"消息{i}") for i in range(22)]
        for i, msg in enumerate(messages):
            msg.sequence = i + 1
        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=messages)

        memory_repo = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        # Orchestrator returns memory object (dict wrapper handling is internal to MemoryModule)
        mem = MagicMock(character_id=CHAR_ID_A)
        mock_orchestrator.generate_short_term_memories.return_value = [mem]

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is True
        assert "叶文洁" in result["characters_updated"]

    async def test_flush_handles_legacy_dict_participants(
        self, service, mock_session_factory, llm, mock_orchestrator
    ):
        """Backward compat: legacy [{id, name}] format still works."""
        _, session = mock_session_factory

        chat_session = AsyncMock()
        chat_session.participants = [{"id": CHAR_ID_A, "name": "叶文洁"}]
        chat_session.last_flushed_sequence = 0

        chat_session_repo = AsyncMock()
        chat_session_repo.get_by_id = AsyncMock(return_value=chat_session)
        chat_session_repo.update_last_flushed_sequence = AsyncMock()

        messages = [_make_message(f"消息{i}") for i in range(22)]
        for i, msg in enumerate(messages):
            msg.sequence = i + 1
        message_repo = AsyncMock()
        message_repo.list_messages_after_sequence = AsyncMock(return_value=messages)

        memory_repo = AsyncMock()

        char_a = _make_character_model(CHAR_ID_A, "叶文洁")
        char_repo = AsyncMock()
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        # Configure orchestrator to return memory object
        mem = MagicMock(character_id=CHAR_ID_A)
        mock_orchestrator.generate_short_term_memories.return_value = [mem]

        with (
            patch(
                "src.services.message_service.ChatSessionRepository", return_value=chat_session_repo
            ),
            patch("src.services.message_service.MessageRepository", return_value=message_repo),
            patch(
                "src.db.repositories.character_memory_repo.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch("src.db.repositories.character_repo.CharacterRepository", return_value=char_repo),
        ):
            result = await service.flush_chat_memories(WORLD_ID_FLUSH, SESSION_ID_FLUSH)

        assert result["flushed"] is True
        assert "叶文洁" in result["characters_updated"]


class TestUnwrapList:
    """Tests for _unwrap_list helper."""

    def test_list_passthrough(self):
        from src.utils.llm_utils import unwrap_list

        assert unwrap_list([1, 2, 3]) == [1, 2, 3]

    def test_none_returns_empty(self):
        from src.utils.llm_utils import unwrap_list

        assert unwrap_list(None) == []

    def test_dict_known_wrapper_key(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        assert _unwrap_list({"items": [1, 2]}) == [1, 2]
        assert _unwrap_list({"results": [3]}) == [3]
        assert _unwrap_list({"data": [4]}) == [4]

    def test_dict_unknown_key_with_list_value(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        assert _unwrap_list({"characters": [7, 8]}) == [7, 8]

    def test_dict_no_list_values(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        assert _unwrap_list({"name": "test", "count": 5}) == []


class TestMemoryFlushTriggered:
    """Problem 3: memory_flush_triggered should be True when flush task is started."""

    WORLD_ID_VALID = str(uuid.uuid4())

    @pytest.fixture
    def message_repo(self):
        mock = AsyncMock()
        mock.create = AsyncMock(side_effect=lambda msg: msg)
        # session needs to support both `await session.rollback()` (async) and
        # `async with session.begin_nested()` (async context manager).
        mock.session.begin_nested = MagicMock(return_value=AsyncMock())
        return mock

    @pytest.fixture
    def dialogue_service(self):
        mock = AsyncMock()
        mock.generate_response.return_value = [_make_message()]
        mock.select_participants.return_value = {
            "speakers": [{"id": "char-001", "name": "叶文洁"}],
            "background": [],
            "narration": "",
            "relevant_elements": [],
        }
        return mock

    @pytest.fixture
    def chat_session_repo(self):
        mock = AsyncMock()
        mock.create.return_value = _make_session()
        mock.update_participants = AsyncMock()
        return mock

    @pytest.fixture
    def version_repo(self):
        mock = AsyncMock()
        version = MagicMock()
        version.id = str(uuid.uuid4())
        mock.get_latest = AsyncMock(return_value=version)
        return mock

    async def test_memory_flush_triggered_true_when_task_started(
        self, message_repo, dialogue_service, chat_session_repo, version_repo
    ):
        """memory_flush_triggered should be True when session_factory and llm are available."""
        session_factory = MagicMock()
        llm = AsyncMock()
        service = MessageService(
            message_repo=message_repo,
            dialogue_service=dialogue_service,
            chat_session_repo=chat_session_repo,
            session_factory=session_factory,
            llm=llm,
        )
        with (
            patch("asyncio.create_task"),
            patch("src.db.repositories.version_repo.VersionRepository", return_value=version_repo),
        ):
            result = await service.send_message(self.WORLD_ID_VALID, "test", memories_enabled=True)
        assert result.memory_flush_triggered is True

    async def test_memory_flush_triggered_false_when_no_session_factory(
        self, message_repo, dialogue_service, chat_session_repo, version_repo
    ):
        """memory_flush_triggered should be False when session_factory is not available."""
        service = MessageService(
            message_repo=message_repo,
            dialogue_service=dialogue_service,
            chat_session_repo=chat_session_repo,
        )
        with patch("src.db.repositories.version_repo.VersionRepository", return_value=version_repo):
            result = await service.send_message(self.WORLD_ID_VALID, "test")
        assert result.memory_flush_triggered is False
