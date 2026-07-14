"""Tests for EventDialogueService.stream_dialogue and discard_event."""

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.character import Character
from src.models.event import Event
from src.models.message import Message
from src.services.event_dialogue_service import EventDialogueService

WORLD_ID = str(uuid.uuid4())
CHAR_A_ID = str(uuid.uuid4())
CHAR_B_ID = str(uuid.uuid4())
EVENT_ID = str(uuid.uuid4())
MSG_ID = str(uuid.uuid4())


def _make_character(
    name: str, char_id: str, brief: str = "简介", recent_memory: str = ""
) -> Character:
    return Character(
        id=char_id,
        world_id=WORLD_ID,
        name=name,
        profile={"brief": brief, "recent_memory": recent_memory},
    )


def _make_event(**kwargs) -> Event:
    return Event(
        id=kwargs.get("id", EVENT_ID),
        world_id=WORLD_ID,
        event_type="user_injected",
        name=kwargs.get("name", "暴风雪"),
        description="暴风雪袭来",
        status=kwargs.get("status", "scheduled"),
        created_at=datetime.now(),
    )


def _make_message(content: str, sender_name: str) -> Message:
    return Message(
        id=str(uuid.uuid4()),
        world_id=WORLD_ID,
        type="dialogue",
        sender_type="character",
        sender_id=str(uuid.uuid4()),
        content=content,
    )


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_char_repo():
    repo = AsyncMock()
    repo.session = AsyncMock()
    return repo


@pytest.fixture
def mock_msg_repo():
    repo = AsyncMock()
    repo.session = AsyncMock()
    return repo


@pytest.fixture
def mock_event_repo():
    repo = AsyncMock()
    repo.session = AsyncMock()
    repo.session.commit = AsyncMock()
    return repo


@pytest.fixture
def mock_world_repo():
    return AsyncMock()


@pytest.fixture
def mock_session_factory():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = session
    return factory


@pytest.fixture
def service(
    mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo, mock_session_factory
):
    return EventDialogueService(
        llm=mock_llm,
        character_repo=mock_char_repo,
        message_repo=mock_msg_repo,
        event_repo=mock_event_repo,
        world_repo=mock_world_repo,
        session_factory=mock_session_factory,
    )


def _make_request(disconnected: bool = False):
    req = AsyncMock()
    req.is_disconnected = AsyncMock(return_value=disconnected)
    return req


async def _collect_sse(service, world_id, raw_input, request):
    """Collect all SSE events from stream_dialogue into a list of (event_type, data) tuples."""
    events = []
    async for chunk in service.stream_dialogue(world_id, raw_input, request):
        for line in chunk.strip().split("\n"):
            if line.startswith("event: "):
                events.append({"event": line[7:], "data": None})
            elif line.startswith("data: ") and events:
                try:
                    events[-1]["data"] = json.loads(line[6:])
                except json.JSONDecodeError:
                    events[-1]["data"] = line[6:]
    return events


def _planner_scene(title: str = "暴风雪袭来", location: str = "基地") -> dict:
    """正确的 Planner 响应格式：包含 scenes 列表。"""
    return {
        "event_title": title,
        "scenes": [
            {
                "scene_id": 1,
                "location": location,
                "atmosphere": "紧张",
                "factions": ["基地人员"],
                "purpose": "讨论对策",
            }
        ],
    }


class TestStreamDialogueHappyPath:
    async def test_yields_event_injected_then_speaker_turns_then_done(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """Full happy path: planner→orchestrator→2 speaker turns→summarizer→done."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")
        char_b = _make_character("常伟思", CHAR_B_ID, brief="将军")
        mock_char_repo.list_by_world.return_value = [char_a, char_b]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("...", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            # 1. Planner → scenes
            _planner_scene("暴风雪袭来"),
            # 2. Orchestrator → participants
            {"participants": ["叶文洁", "常伟思"], "first_speaker": "叶文洁"},
            # 3-4. Speaker turns
            {"content": "常将军，外面情况很糟！", "next_speaker": "常伟思"},
            {"content": "所有人留在室内。", "next_speaker": None},
            # 5. Summarizer
            {"summary": "讨论了暴风雪应对方案"},
            # 无更多场景，不调 Reviser
            # Memory updates 是 asyncio.create_task 异步执行，不在此列
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪突然袭来", _make_request())

        event_types = [e["event"] for e in events]
        assert "event_injected" in event_types
        assert event_types.count("speaker_turn") == 2
        assert "memory_updating" in event_types
        assert "done" in event_types
        assert "error" not in event_types

    async def test_event_injected_payload_has_title(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """event_injected 应包含 Planner 生成的 event_title。
        注意：participants 始终为 []，由前端从 speaker_turn 累积。"""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("...", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            {"content": "暴风雪来了！", "next_speaker": None},
            {"summary": "目睹了暴风雪"},
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        injected = next(e for e in events if e["event"] == "event_injected")
        assert injected["data"]["title"] == "暴风雪"
        assert injected["data"]["participants"] == []  # 前端从 speaker_turn 累积

    async def test_speaker_turn_payload_has_content_and_sender(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        msg = _make_message("暴风雪！", "叶文洁")
        msg.sender_id = CHAR_A_ID
        mock_msg_repo.create.return_value = msg
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            {"content": "暴风雪！", "next_speaker": None},
            {"summary": "暴风雪袭来"},
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        turn = next(e for e in events if e["event"] == "speaker_turn")
        assert turn["data"]["sender_name"] == "叶文洁"
        assert turn["data"]["content"] == "暴风雪！"


class TestStreamDialogueErrorCases:
    async def test_orchestrator_llm_failure_yields_error(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        mock_char_repo.list_by_world.return_value = []
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_llm.complete_json.side_effect = RuntimeError("LLM 超时")

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        event_types = [e["event"] for e in events]
        assert "error" in event_types
        assert "done" not in event_types

    async def test_no_participants_yields_error(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        mock_char_repo.list_by_world.return_value = []
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        # Orchestrator returns no participants
        mock_llm.complete_json.return_value = {
            "event_title": "暴风雪",
            "participants": [],
            "first_speaker": None,
        }

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        event_types = [e["event"] for e in events]
        assert "error" in event_types

    async def test_hallucinated_participant_names_are_filtered(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """Orchestrator 返回不存在的角色名应被过滤，不能引发错误。"""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            # Orchestrator 返回幻觉角色 → 被过滤，只保留叶文洁
            {"participants": ["叶文洁", "虚构角色X"], "first_speaker": "叶文洁"},
            {"content": "测试", "next_speaker": None},
            {"summary": "暴风雪袭来"},
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        # 正常完成，无 error；幻觉角色不出现在任何 speaker_turn
        event_types = [e["event"] for e in events]
        assert "error" not in event_types
        assert "done" in event_types
        speaker_names = [e["data"]["sender_name"] for e in events if e["event"] == "speaker_turn"]
        assert "虚构角色X" not in speaker_names


class TestStreamDialogueDisconnect:
    async def test_disconnected_client_stops_generation(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """用户打断（is_disconnected=True）应在第一轮发言前 break。"""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        # Planner 正确返回 scenes
        mock_llm.complete_json.return_value = _planner_scene("暴风雪")

        mock_msg_repo.create.return_value = _make_message("...", "叶文洁")

        # Client is already disconnected — 场景循环入口检查后立即 break
        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request(disconnected=True))

        event_types = [e["event"] for e in events]
        assert "event_injected" in event_types
        assert "speaker_turn" not in event_types


class TestDiscardEvent:
    async def test_discard_deletes_messages_and_cancels_event(
        self, service, mock_msg_repo, mock_event_repo
    ):
        msg_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        await service.discard_event(EVENT_ID, msg_ids)

        mock_msg_repo.delete_by_ids.assert_called_once_with(msg_ids)
        mock_event_repo.update_status.assert_called_once_with(EVENT_ID, "cancelled")

    async def test_discard_with_empty_message_ids(self, service, mock_msg_repo, mock_event_repo):
        await service.discard_event(EVENT_ID, [])
        mock_msg_repo.delete_by_ids.assert_called_once_with([])
        mock_event_repo.update_status.assert_called_once_with(EVENT_ID, "cancelled")


class TestCleanupOldMessages:
    async def test_cleanup_deletes_within_3_days(self, service, mock_msg_repo, mock_event_repo):
        mock_event_repo.count_by_world.return_value = 5
        await service._cleanup_old_messages(WORLD_ID)
        mock_msg_repo.delete_before_real_time.assert_called_once()

    async def test_cleanup_uses_event_cutoff_when_over_50(
        self, service, mock_msg_repo, mock_event_repo
    ):
        mock_event_repo.count_by_world.return_value = 60
        cutoff = datetime(2024, 1, 1)
        mock_event_repo.get_nth_event_time.return_value = cutoff

        # Patch _utcnow so cutoff_by_event is always > three_days_ago
        with patch("src.services.event_dialogue_service._utcnow") as mock_now:
            mock_now.return_value = datetime(2024, 1, 2)  # only 1 day later
            await service._cleanup_old_messages(WORLD_ID)

        mock_event_repo.get_nth_event_time.assert_called_once_with(WORLD_ID, n=50)
        mock_msg_repo.delete_before_real_time.assert_called_once()


class TestUnwrapList:
    """Tests for _unwrap_list helper."""

    def test_list_passthrough(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        assert _unwrap_list([1, 2, 3]) == [1, 2, 3]

    def test_none_returns_empty(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        assert _unwrap_list(None) == []

    def test_dict_known_wrapper_key(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        assert _unwrap_list({"items": [1, 2]}) == [1, 2]
        assert _unwrap_list({"results": [3]}) == [3]
        assert _unwrap_list({"data": [4]}) == [4]
        assert _unwrap_list({"memories": [5]}) == [5]
        assert _unwrap_list({"elements": [6]}) == [6]

    def test_dict_unknown_key_with_list_value(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        assert _unwrap_list({"characters": [7, 8]}) == [7, 8]

    def test_dict_no_list_values(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        assert _unwrap_list({"name": "test", "count": 5}) == []

    def test_dict_first_list_value(self):
        from src.utils.llm_utils import unwrap_list as _unwrap_list

        result = _unwrap_list({"a": "not list", "b": [1, 2], "c": [3]})
        assert result == [1, 2]


class TestUpdateMemoriesBatch:
    """Tests for the rewritten _update_memories with batch short-term generation
    and two-phase long-term promotion."""

    @pytest.fixture
    def mock_memory_repo(self):
        repo = AsyncMock()
        repo.add = AsyncMock()
        repo.list_short_term = AsyncMock(return_value=[])
        repo.list_long_term = AsyncMock(return_value=[])
        repo.list_characters_needing_promotion = AsyncMock(return_value=set())
        repo.get_oldest_short_term = AsyncMock(return_value=[])
        repo.delete_by_ids = AsyncMock()
        return repo

    @pytest.fixture
    def mock_relation_repo(self):
        repo = AsyncMock()
        repo.list_by_world = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def service_with_memory(
        self,
        mock_llm,
        mock_char_repo,
        mock_msg_repo,
        mock_event_repo,
        mock_world_repo,
        mock_session_factory,
    ):
        from src.services.memory_module import MemoryModule
        from src.services.memory_orchestrator import MemoryOrchestrator

        memory_module = MemoryModule(llm=mock_llm, session_factory=mock_session_factory)
        orchestrator = MemoryOrchestrator(memory_module=memory_module)
        return EventDialogueService(
            llm=mock_llm,
            character_repo=mock_char_repo,
            message_repo=mock_msg_repo,
            event_repo=mock_event_repo,
            world_repo=mock_world_repo,
            session_factory=mock_session_factory,
            memory_orchestrator=orchestrator,
        )

    async def test_batch_short_term_memory_generation(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Batch: one LLM call generates memories for all participants."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")
        char_b = _make_character("常伟思", CHAR_B_ID, brief="将军")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(
            side_effect=lambda wid, name: {"叶文洁": char_a, "常伟思": char_b}.get(name)
        )
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value=set())
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        # Patch repos created inside the method
        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
        ):
            # LLM returns array for batch memory generation
            mock_llm.complete_json.return_value = [
                {"character": "叶文洁", "content": "我经历了暴风雪"},
                {"character": "常伟思", "content": "我下令封闭基地"},
            ]

            messages = [_make_message("暴风雪来了", "叶文洁"), _make_message("封闭基地", "常伟思")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁", "常伟思"], "暴风雪袭来", messages, str(uuid.uuid4())
            )

        # Should call LLM once for batch generation
        assert mock_llm.complete_json.call_count >= 1
        # Should add memories for both characters
        assert memory_repo.add.call_count == 2

    async def test_batch_memory_skips_null_content(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Batch: null content entries are skipped, not written to DB."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")
        char_b = _make_character("常伟思", CHAR_B_ID, brief="将军")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(
            side_effect=lambda wid, name: {"叶文洁": char_a, "常伟思": char_b}.get(name)
        )
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value=set())
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
        ):
            # LLM returns null content for 常伟思
            mock_llm.complete_json.return_value = [
                {"character": "叶文洁", "content": "我经历了暴风雪"},
                {"character": "常伟思", "content": None},
            ]

            messages = [_make_message("暴风雪来了", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁", "常伟思"], "暴风雪袭来", messages, str(uuid.uuid4())
            )

        # Only one memory should be added (叶文洁), 常伟思's null content skipped
        assert memory_repo.add.call_count == 1

    async def test_batch_memory_skips_empty_content(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Batch: empty string content entries are skipped."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value=set())
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
        ):
            mock_llm.complete_json.return_value = [
                {"character": "叶文洁", "content": ""},
            ]

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        assert memory_repo.add.call_count == 0

    async def test_promotion_threshold_is_40(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Promotion should trigger at 40 short-term memories."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        char_repo.list_by_world = AsyncMock(return_value=[char_a])
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.add_structured_long_term = AsyncMock()
        memory_repo.list_characters_needing_promotion = AsyncMock(
            return_value={uuid.UUID(CHAR_A_ID)}
        )
        old_mems = [AsyncMock(id=uuid.uuid4(), content=f"记忆{i}") for i in range(30)]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=old_mems)
        memory_repo.delete_by_ids = AsyncMock()
        memory_repo.list_long_term_structured = AsyncMock(return_value=[])
        memory_repo.get_by_event_name = AsyncMock(return_value=None)
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        world_doc = MagicMock()
        world_doc.source = MagicMock()
        world_doc.source.title = "三体"
        world_doc.source.author = "刘慈欣"
        elem = MagicMock()
        elem.name = "红岸基地"
        elem.brief = "射电望远镜基地"
        elem.detailed = "位于内蒙古"
        world_doc.elements = [elem]

        event_index_repo = AsyncMock()
        event_index_repo.list_by_world = AsyncMock(return_value=[])
        new_event_id = uuid.uuid4()
        new_event_entry = MagicMock()
        new_event_entry.id = new_event_id
        event_index_repo.add = AsyncMock(return_value=new_event_entry)

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=event_index_repo,
            ),
        ):
            # Batch short-term
            mock_llm.complete_json.side_effect = [
                [{"character": "叶文洁", "content": "新记忆"}],
                # Phase 1: select elements
                ["红岸基地"],
                # Phase 2: promote (structured format)
                {
                    "promote": [
                        {
                            "event_name": "重大事件",
                            "event_code": "new",
                            "event_brief": "重大事件描述",
                            "perspective_detail": "某次重大事件",
                            "reflection": "深刻感悟",
                            "involved_characters": ["C1"],
                        }
                    ]
                },
            ]

            service_with_memory.world_repo.get = AsyncMock(return_value=world_doc)

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Should trigger promotion (batch query returns the char)
        memory_repo.get_oldest_short_term.assert_called_once_with(
            char_a.id, limit=30, exclude_categories=["trivial"]
        )
        # Should delete the 30 oldest short-term memories after promotion
        memory_repo.delete_by_ids.assert_called_once()
        # Verify structured long-term memory was written
        memory_repo.add_structured_long_term.assert_called_once()
        call_kwargs = memory_repo.add_structured_long_term.call_args[1]
        # V2: event_name stores event ID (UUID string), not display name
        assert call_kwargs["event_name"] == str(new_event_id)
        assert call_kwargs["perspective_detail"] == "某次重大事件"
        assert call_kwargs["character_id"] == char_a.id

    async def test_promotion_at_exactly_40_with_new_write(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Promotion triggers when a character has exactly 40 short-term memories
        and one new memory is written (total 41, but promotion checks >= 40)."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        char_repo.list_by_world = AsyncMock(return_value=[char_a])
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.add_structured_long_term = AsyncMock()
        # Batch query indicates this character needs promotion (count >= 40)
        memory_repo.list_characters_needing_promotion = AsyncMock(
            return_value={uuid.UUID(CHAR_A_ID)}
        )
        old_mems = [AsyncMock(id=uuid.uuid4(), content=f"记忆{i}") for i in range(30)]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=old_mems)
        memory_repo.delete_by_ids = AsyncMock()
        memory_repo.list_long_term_structured = AsyncMock(return_value=[])
        memory_repo.get_by_event_name = AsyncMock(return_value=None)
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])
        char_repo.get_by_id = AsyncMock(return_value=None)

        world_doc = MagicMock()
        world_doc.source = MagicMock()
        world_doc.source.title = "三体"
        world_doc.source.author = "刘慈欣"
        world_doc.elements = []

        event_index_repo = AsyncMock()
        event_index_repo.list_by_world = AsyncMock(return_value=[])
        new_event_id = uuid.uuid4()
        new_event_entry = MagicMock()
        new_event_entry.id = new_event_id
        event_index_repo.add = AsyncMock(return_value=new_event_entry)

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=event_index_repo,
            ),
        ):
            # Batch short-term + Phase 1 + Phase 2
            mock_llm.complete_json.side_effect = [
                [{"character": "叶文洁", "content": "第41条记忆"}],
                [],  # Phase 1: no relevant elements
                {
                    "promote": [
                        {
                            "event_name": "震撼经历",
                            "event_code": "new",
                            "event_brief": "震撼经历描述",
                            "perspective_detail": "某次震撼经历",
                            "reflection": None,
                            "involved_characters": [],
                        }
                    ]
                },
            ]
            service_with_memory.world_repo.get = AsyncMock(return_value=world_doc)

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Promotion should have been triggered
        memory_repo.get_oldest_short_term.assert_called_once_with(
            char_a.id, limit=30, exclude_categories=["trivial"]
        )
        memory_repo.delete_by_ids.assert_called_once()
        # Structured long-term memory written
        memory_repo.add_structured_long_term.assert_called_once()
        call_kwargs = memory_repo.add_structured_long_term.call_args[1]
        # V2: event_name stores event ID (UUID string)
        assert call_kwargs["event_name"] == str(new_event_id)
        assert call_kwargs["perspective_detail"] == "某次震撼经历"

    async def test_no_promotion_below_threshold(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """No promotion when count < 40."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        # Batch query returns empty set (no chars need promotion)
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value=set())
        memory_repo.get_oldest_short_term = AsyncMock()
        memory_repo.delete_by_ids = AsyncMock()
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
        ):
            mock_llm.complete_json.return_value = [
                {"character": "叶文洁", "content": "新记忆"},
            ]

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Should NOT trigger promotion
        memory_repo.get_oldest_short_term.assert_not_called()
        memory_repo.delete_by_ids.assert_not_called()

    async def test_llm_failure_in_batch_does_not_crash(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """LLM failure in batch generation should skip gracefully."""
        char_a = _make_character("叶文洁", CHAR_A_ID)

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        memory_repo = AsyncMock()
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value=set())
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
        ):
            mock_llm.complete_json.side_effect = RuntimeError("LLM timeout")

            messages = [_make_message("测试", "叶文洁")]
            # Should not raise
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        memory_repo.add.assert_not_called()

    async def test_user_prompt_includes_detailed_profiles(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Problem 1: user_prompt should include detailed character profiles."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")
        char_a.profile["detail"] = "文革中目睹父亲被打死，后成为天体物理学家"

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value=set())
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
        ):
            mock_llm.complete_json.return_value = [
                {"character": "叶文洁", "content": "我经历了暴风雪"},
            ]

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Check the user_prompt passed to LLM includes detailed profile
        llm_call_args = mock_llm.complete_json.call_args
        user_prompt = llm_call_args[0][1]  # second positional arg
        assert "详细背景" in user_prompt
        assert "文革中目睹父亲被打死" in user_prompt

    async def test_update_memories_handles_dict_wrapper(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Problem 3: _update_memories should handle LLM returning dict wrapper."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value=set())
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
        ):
            # LLM returns dict wrapper instead of bare list
            mock_llm.complete_json.return_value = {
                "items": [{"character": "叶文洁", "content": "我经历了暴风雪"}]
            }

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Should still write the memory despite dict wrapper
        assert memory_repo.add.call_count == 1

    async def test_promote_phase1_handles_dict_wrapper(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Phase 1 should handle dict wrapper for element names."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        char_repo.list_by_world = AsyncMock(return_value=[char_a])
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.add_structured_long_term = AsyncMock()
        old_mems = [AsyncMock(id=uuid.uuid4(), content=f"记忆{i}") for i in range(30)]
        memory_repo.list_characters_needing_promotion = AsyncMock(
            return_value={uuid.UUID(CHAR_A_ID)}
        )
        memory_repo.get_oldest_short_term = AsyncMock(return_value=old_mems)
        memory_repo.delete_by_ids = AsyncMock()
        memory_repo.list_long_term_structured = AsyncMock(return_value=[])
        memory_repo.get_by_event_name = AsyncMock(return_value=None)
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        world_doc = MagicMock()
        world_doc.source = MagicMock()
        world_doc.source.title = "三体"
        world_doc.source.author = "刘慈欣"
        elem = MagicMock()
        elem.name = "红岸基地"
        elem.brief = "射电望远镜基地"
        elem.detailed = "位于内蒙古"
        world_doc.elements = [elem]

        event_index_repo = AsyncMock()
        event_index_repo.list_by_world = AsyncMock(return_value=[])
        new_event_id = uuid.uuid4()
        new_event_entry = MagicMock()
        new_event_entry.id = new_event_id
        event_index_repo.add = AsyncMock(return_value=new_event_entry)

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=event_index_repo,
            ),
        ):
            mock_llm.complete_json.side_effect = [
                # Batch short-term
                [{"character": "叶文洁", "content": "新记忆"}],
                # Phase 1: dict wrapper instead of bare list
                {"elements": ["红岸基地"]},
                # Phase 2: promote (structured format)
                {
                    "promote": [
                        {
                            "event_name": "重大事件",
                            "event_code": "new",
                            "event_brief": "重大事件描述",
                            "perspective_detail": "某次重大事件",
                            "reflection": None,
                            "involved_characters": [],
                        }
                    ]
                },
            ]
            service_with_memory.world_repo.get = AsyncMock(return_value=world_doc)

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Should have matched the element and triggered promotion
        memory_repo.get_oldest_short_term.assert_called_once()
        # Should have written a structured long-term memory
        memory_repo.add_structured_long_term.assert_called_once()

    async def test_relation_text_uses_character_names_not_uuids(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """Problem 4: relation text should use character names, not UUIDs."""
        from src.models.relation import Relation

        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")
        char_b = _make_character("常伟思", str(uuid.uuid4()), brief="将军")
        char_b_id = char_b.id

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        char_repo.get_by_id = AsyncMock(
            side_effect=lambda cid: char_b if cid == char_b_id else None
        )
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        old_mems = [AsyncMock(id=uuid.uuid4(), content=f"记忆{i}") for i in range(30)]
        memory_repo.list_characters_needing_promotion = AsyncMock(
            return_value={uuid.UUID(CHAR_A_ID)}
        )
        memory_repo.get_oldest_short_term = AsyncMock(return_value=old_mems)
        memory_repo.delete_by_ids = AsyncMock()
        relation_repo = AsyncMock()
        relation = Relation(
            id=str(uuid.uuid4()),
            world_id=WORLD_ID,
            character_a=CHAR_A_ID,
            character_b=char_b_id,
            type="同事",
            description="共同研究",
        )
        relation_repo.list_by_world = AsyncMock(return_value=[relation])

        world_doc = MagicMock()
        world_doc.source = MagicMock()
        world_doc.source.title = "三体"
        world_doc.source.author = "刘慈欣"
        world_doc.elements = []

        event_index_repo = AsyncMock()
        event_index_repo.list_by_world = AsyncMock(return_value=[])
        new_event_id = uuid.uuid4()
        new_event_entry = MagicMock()
        new_event_entry.id = new_event_id
        event_index_repo.add = AsyncMock(return_value=new_event_entry)

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=event_index_repo,
            ),
        ):
            mock_llm.complete_json.side_effect = [
                [{"character": "叶文洁", "content": "新记忆"}],
                ["红岸基地"],
                {"promote": [{"content": "某次重大事件"}], "discard_count": 20},
            ]
            service_with_memory.world_repo.get = AsyncMock(return_value=world_doc)

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Check that the system prompt for phase 1 uses character name, not UUID
        # Find the call that contains relation text
        found_name_in_prompt = False
        for call in mock_llm.complete_json.call_args_list:
            system_prompt = call[0][0]
            if "关系" in system_prompt:
                assert "常伟思" in system_prompt
                assert char_b_id not in system_prompt
                found_name_in_prompt = True
        assert found_name_in_prompt, "Expected relation text in at least one LLM call"

    async def test_phase2_list_response_preserves_short_term_memories(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """When phase 2 returns a list (format error), short-term memories are preserved
        (no deletion, no long-term write). This prevents data loss on LLM format anomalies."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        old_mems = [AsyncMock(id=uuid.uuid4(), content=f"记忆{i}") for i in range(30)]
        memory_repo.list_characters_needing_promotion = AsyncMock(
            return_value={uuid.UUID(CHAR_A_ID)}
        )
        memory_repo.get_oldest_short_term = AsyncMock(return_value=old_mems)
        memory_repo.delete_by_ids = AsyncMock()
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        world_doc = MagicMock()
        world_doc.source = MagicMock()
        world_doc.source.title = "三体"
        world_doc.source.author = "刘慈欣"
        world_doc.elements = []

        event_index_repo = AsyncMock()
        event_index_repo.list_by_world = AsyncMock(return_value=[])
        new_event_id = uuid.uuid4()
        new_event_entry = MagicMock()
        new_event_entry.id = new_event_id
        event_index_repo.add = AsyncMock(return_value=new_event_entry)

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=event_index_repo,
            ),
        ):
            mock_llm.complete_json.side_effect = [
                # Batch short-term
                [{"character": "叶文洁", "content": "新记忆"}],
                # Phase 1: select elements
                ["红岸基地"],
                # Phase 2: returns list (format error)
                [{"unexpected": "format"}],
            ]
            service_with_memory.world_repo.get = AsyncMock(return_value=world_doc)

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Should NOT delete short-term memories on format error
        memory_repo.delete_by_ids.assert_not_called()
        # Should NOT have written any long-term memories
        # memory_repo.add was called once for the batch short-term, not for long-term
        assert memory_repo.add.call_count == 1

    async def test_phase1_empty_list_still_runs_phase2(
        self, service_with_memory, mock_llm, mock_session_factory
    ):
        """When Phase 1 returns empty list [], Phase 2 should still execute
        (elements_detailed is empty string), and promotion completes normally."""
        char_a = _make_character("叶文洁", CHAR_A_ID, brief="天体物理学家")

        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        char_repo.list_by_world = AsyncMock(return_value=[char_a])
        memory_repo = AsyncMock()
        memory_repo.add = AsyncMock()
        memory_repo.add_structured_long_term = AsyncMock()
        old_mems = [AsyncMock(id=uuid.uuid4(), content=f"记忆{i}") for i in range(30)]
        memory_repo.list_characters_needing_promotion = AsyncMock(
            return_value={uuid.UUID(CHAR_A_ID)}
        )
        memory_repo.get_oldest_short_term = AsyncMock(return_value=old_mems)
        memory_repo.delete_by_ids = AsyncMock()
        memory_repo.list_long_term_structured = AsyncMock(return_value=[])
        memory_repo.get_by_event_name = AsyncMock(return_value=None)
        relation_repo = AsyncMock()
        relation_repo.list_by_world = AsyncMock(return_value=[])

        world_doc = MagicMock()
        world_doc.source = MagicMock()
        world_doc.source.title = "三体"
        world_doc.source.author = "刘慈欣"
        world_doc.elements = []

        event_index_repo = AsyncMock()
        event_index_repo.list_by_world = AsyncMock(return_value=[])
        new_event_id = uuid.uuid4()
        new_event_entry = MagicMock()
        new_event_entry.id = new_event_id
        event_index_repo.add = AsyncMock(return_value=new_event_entry)

        with (
            patch(
                "src.services.event_dialogue_service.CharacterRepository", return_value=char_repo
            ),
            patch(
                "src.services.event_dialogue_service.CharacterMemoryRepository",
                return_value=memory_repo,
            ),
            patch(
                "src.services.event_dialogue_service.RelationRepository", return_value=relation_repo
            ),
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=event_index_repo,
            ),
        ):
            mock_llm.complete_json.side_effect = [
                # Batch short-term
                [{"character": "叶文洁", "content": "新记忆"}],
                # Phase 1: returns empty list (no relevant elements)
                [],
                # Phase 2: promote succeeds (structured format)
                {
                    "promote": [
                        {
                            "event_name": "震撼经历",
                            "event_code": "new",
                            "event_brief": "震撼经历描述",
                            "perspective_detail": "某次震撼经历",
                            "reflection": None,
                            "involved_characters": [],
                        }
                    ]
                },
            ]
            service_with_memory.world_repo.get = AsyncMock(return_value=world_doc)

            messages = [_make_message("测试", "叶文洁")]
            await service_with_memory._update_memories(
                WORLD_ID, ["叶文洁"], "测试事件", messages, str(uuid.uuid4())
            )

        # Structured long-term memory should be written (Phase 2 ran successfully)
        memory_repo.add_structured_long_term.assert_called_once()
        call_kwargs = memory_repo.add_structured_long_term.call_args[1]
        # V2: event_name stores the event ID (UUID string), not the display name
        assert call_kwargs["event_name"] == str(new_event_id)
        assert call_kwargs["perspective_detail"] == "某次震撼经历"
        # The 30 oldest short-term memories should be deleted
        memory_repo.delete_by_ids.assert_called_once()
