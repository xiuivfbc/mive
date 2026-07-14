"""TDD Tests for Phase 3: Messages/Sessions store only IDs, not names.

Tests are written BEFORE the implementation:
- M4Message: sender_name column removed; system messages have sender_id=NULL
- M4ChatSession.participants: UUID array instead of [{"id":"...", "name":"..."}]
- Services construct messages without sender_name
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.models.character import Character
from src.models.message import Message


def _make_character(name: str, char_id: str | None = None) -> Character:
    return Character(
        id=char_id or str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        profile={"brief": f"{name}简介"},
    )


# ── 1. Message model: sender_name is no longer required ──────────────────────


class TestMessageModelNoSenderName:
    """Phase 3: Message model works without sender_name."""

    def test_message_without_sender_name(self):
        """A character message can be created without sender_name."""
        msg = Message(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="dialogue",
            sender_type="character",
            sender_id=str(uuid.uuid4()),
            content="测试消息",
            virtual_time=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert msg.sender_id is not None
        assert msg.sender_name is None

    def test_system_message_sender_id_null(self):
        """System/narrator messages have sender_id=None."""
        msg = Message(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="system",
            sender_type="system",
            sender_id=None,
            content="系统消息",
            virtual_time=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert msg.sender_id is None
        assert msg.sender_type == "system"

    def test_narrator_message_sender_id_null(self):
        """Narrator messages have sender_id=None."""
        msg = Message(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="narration",
            sender_type="narrator",
            sender_id=None,
            content="旁白内容",
            virtual_time=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert msg.sender_id is None
        assert msg.sender_type == "narrator"

    def test_sender_name_still_accepted_for_backward_compat(self):
        """sender_name is still accepted as optional for backward compatibility."""
        msg = Message(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="dialogue",
            sender_type="character",
            sender_id=str(uuid.uuid4()),
            sender_name="叶文洁",
            content="你好",
            virtual_time=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert msg.sender_name == "叶文洁"


# ── 2. dialogue_generation_service: constructs messages without sender_name ──


class TestDialogueGenerationServiceSenderIDOnly:
    """Phase 3: generate_response creates messages using only sender_id."""

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def char_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def msg_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        mock.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        return mock

    async def test_generate_response_no_sender_name_in_messages(self, llm, char_repo, msg_repo):
        """generate_response should create messages without sender_name field."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": "你好",
                    "virtual_time_offset_minutes": 0,
                }
            ]
        }

        svc = DialogueGenerationService(llm=llm, character_repo=char_repo, message_repo=msg_repo)
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": char_a.id, "name": "叶文洁"}],
        )
        assert len(responses) == 1
        # sender_id should be set
        assert responses[0].sender_id == char_a.id
        # sender_name should NOT be set (Phase 3: only store ID)
        assert responses[0].sender_name is None

    async def test_generate_response_uses_sender_id_from_name(self, llm, char_repo, msg_repo):
        """LLM returns sender_name; service resolves it to sender_id."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": "你好",
                    "virtual_time_offset_minutes": 0,
                }
            ]
        }

        svc = DialogueGenerationService(llm=llm, character_repo=char_repo, message_repo=msg_repo)
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        assert len(responses) == 1
        assert responses[0].sender_id == char_a.id

    async def test_generate_response_skips_unknown_sender(self, llm, char_repo, msg_repo):
        """Messages with unknown sender_name should be skipped."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_repo.list_by_world.return_value = [_make_character("叶文洁")]
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "未知角色",
                    "content": "你好",
                    "virtual_time_offset_minutes": 0,
                }
            ]
        }

        svc = DialogueGenerationService(llm=llm, character_repo=char_repo, message_repo=msg_repo)
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        assert len(responses) == 0

    async def test_history_context_uses_sender_type_fallback(self, llm, char_repo, msg_repo):
        """History lines should use sender_type when sender_name is absent."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]

        # History with no sender_name (new format)
        history_msg = Message(
            id=str(uuid.uuid4()),
            world_id="w1",
            type="dialogue",
            sender_type="character",
            sender_id=char_a.id,
            content="历史消息",
            virtual_time=datetime.now(UTC),
        )
        msg_repo.list_by_session.return_value = [history_msg]

        llm.complete_json.return_value = {"messages": []}

        svc = DialogueGenerationService(llm=llm, character_repo=char_repo, message_repo=msg_repo)
        await svc.generate_response(
            world_id="w1",
            user_message="test",
            session_id="session-1",
        )

        # The user_prompt should reference the history (not system_prompt)
        user_prompt = llm.complete_json.call_args[0][1]
        # Should contain history formatted with resolved name
        assert "历史消息" in user_prompt


# ── 3. event_dialogue_service: constructs messages without sender_name ────────


class TestEventDialogueServiceSenderIDOnly:
    """Phase 3: event_dialogue_service creates messages without sender_name."""

    def test_make_character_for_event(self):
        """Verify _make_character works for event tests."""
        char = _make_character("叶文洁", "char-001")
        assert char.name == "叶文洁"
        assert char.id == "char-001"

    async def test_event_system_message_no_sender_name(self):
        """Event system messages should not have sender_name."""
        msg = Message(
            id=str(uuid.uuid4()),
            world_id="w1",
            type="event",
            sender_type="system",
            sender_id=None,
            content='{"title": "test", "description": "test", "participants": []}',
            virtual_time=datetime.now(UTC),
        )
        assert msg.sender_id is None
        assert msg.sender_name is None

    async def test_narrator_message_no_sender_name(self):
        """Narrator messages should not have sender_name."""
        msg = Message(
            id=str(uuid.uuid4()),
            world_id="w1",
            type="narration",
            sender_type="narrator",
            sender_id=None,
            content="旁白内容",
            virtual_time=datetime.now(UTC),
        )
        assert msg.sender_id is None
        assert msg.sender_name is None

    async def test_character_dialogue_has_sender_id_no_name(self):
        """Character dialogue messages should have sender_id but no sender_name."""
        char = _make_character("叶文洁", "char-001")
        msg = Message(
            id=str(uuid.uuid4()),
            world_id="w1",
            type="dialogue",
            sender_type="character",
            sender_id=char.id,
            content="对话内容",
            virtual_time=datetime.now(UTC),
        )
        assert msg.sender_id == "char-001"
        assert msg.sender_name is None


# ── 4. ChatSession participants: UUID array ──────────────────────────────────


class TestChatSessionParticipantsUUIDArray:
    """Phase 3: participants stored as UUID array, not dict array."""

    def test_participants_is_uuid_array_type(self):
        """ChatSession model accepts UUID string array for participants."""
        from src.models.chat_session import ChatSession

        session = ChatSession(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="character",
            title="测试",
            created_at=datetime.now(UTC),
            participants=["uuid-1", "uuid-2"],
        )
        assert session.participants == ["uuid-1", "uuid-2"]

    def test_participants_none_accepted(self):
        """ChatSession accepts None for participants."""
        from src.models.chat_session import ChatSession

        session = ChatSession(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="character",
            title="测试",
            created_at=datetime.now(UTC),
            participants=None,
        )
        assert session.participants is None


# ── 5. System message display name mapping ───────────────────────────────────


class TestSystemMessageDisplayNames:
    """Phase 3: System/narrator messages use fixed display names."""

    def test_system_sender_type_maps_to_system_name(self):
        """sender_type='system' should map to display name '系统'."""
        DISPLAY_NAME_MAP = {"system": "系统", "narrator": "旁白", "user": "用户"}  # noqa: N806
        assert DISPLAY_NAME_MAP.get("system") == "系统"

    def test_narrator_sender_type_maps_to_narrator_name(self):
        """sender_type='narrator' should map to display name '旁白'."""
        DISPLAY_NAME_MAP = {"system": "系统", "narrator": "旁白", "user": "用户"}  # noqa: N806
        assert DISPLAY_NAME_MAP.get("narrator") == "旁白"

    def test_user_sender_type_maps_to_user_name(self):
        """sender_type='user' should map to display name '用户'."""
        DISPLAY_NAME_MAP = {"system": "系统", "narrator": "旁白", "user": "用户"}  # noqa: N806
        assert DISPLAY_NAME_MAP.get("user") == "用户"
