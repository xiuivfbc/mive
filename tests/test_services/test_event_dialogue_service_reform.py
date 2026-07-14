"""Tests for the Chat System Reform Plan — Steps 7-8 (event SSE side).

Tests for:
- Step 7: MAX_TOTAL_SCENES 6→10, revise frequency every 2 scenes, purpose→goal, participants_count
- Step 8: Batch dialogue generation with dialogues array
"""

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.character import Character
from src.models.event import Event
from src.models.message import Message
from src.services.event_dialogue_service import EventDialogueService

WORLD_ID = str(uuid.uuid4())
CHAR_A_ID = str(uuid.uuid4())
CHAR_B_ID = str(uuid.uuid4())
EVENT_ID = str(uuid.uuid4())


def _make_character(name: str, char_id: str, brief: str = "简介") -> Character:
    return Character(
        id=char_id,
        world_id=WORLD_ID,
        name=name,
        profile={"brief": brief},
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
    return AsyncMock()


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


def _planner_scene(
    title: str = "暴风雪袭来",
    location: str = "基地",
    goal: str = "讨论对策",
    participants_count: int = 3,
) -> dict:
    """正确的 Planner 响应格式（使用 goal 而非 purpose）。"""
    return {
        "event_title": title,
        "scenes": [
            {
                "scene_id": 1,
                "location": location,
                "atmosphere": "紧张",
                "factions": ["基地人员"],
                "goal": goal,
                "participants_count": participants_count,
            }
        ],
    }


# ── Step 7: MAX_TOTAL_SCENES ─────────────────────────────────────────────────


class TestMaxTotalScenes:
    """Step 7.1: MAX_TOTAL_SCENES should be 10."""

    def test_max_total_scenes_is_10(self):

        # Check the constant is defined in the module or class
        import src.services.event_dialogue_service as eds

        assert eds.MAX_TOTAL_SCENES == 10


# ── Step 7: purpose → goal ────────────────────────────────────────────────────


class TestPurposeToGoalRename:
    """Step 7.2: purpose should be renamed to goal with backward compatibility."""

    async def test_goal_field_in_planner_output(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """Planner output should use goal field."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            {"content": "测试", "next_speaker": None},
            {"summary": "暴风雪袭来"},
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        event_types = [e["event"] for e in events]
        assert "error" not in event_types
        assert "done" in event_types

    async def test_backward_compat_purpose_field(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """Planner returning 'purpose' instead of 'goal' should still work (backward compat)."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        # Planner returns 'purpose' instead of 'goal'
        mock_llm.complete_json.side_effect = [
            {
                "event_title": "暴风雪",
                "scenes": [
                    {
                        "scene_id": 1,
                        "location": "基地",
                        "atmosphere": "紧张",
                        "factions": ["基地人员"],
                        "purpose": "讨论对策",
                    }
                ],
            },
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            {"content": "测试", "next_speaker": None},
            {"summary": "暴风雪袭来"},
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        event_types = [e["event"] for e in events]
        assert "error" not in event_types
        assert "done" in event_types


# ── Step 7: participants_count ────────────────────────────────────────────────


class TestParticipantsCount:
    """Step 7.3: participants_count hint in planner output."""

    async def test_participants_count_passed_to_orchestrator(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """participants_count should be passed to orchestrator user prompt."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        char_b = _make_character("常伟思", CHAR_B_ID)
        mock_char_repo.list_by_world.return_value = [char_a, char_b]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪", participants_count=5),
            {"participants": ["叶文洁", "常伟思"], "first_speaker": "叶文洁"},
            {"content": "测试", "next_speaker": None},
            {"summary": "暴风雪袭来"},
        ]

        await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        # Check orchestrator call includes participants_count hint
        orch_call = mock_llm.complete_json.call_args_list[1]
        orch_user = orch_call[0][1]
        assert "建议参与人数" in orch_user


# ── Step 8: Batch dialogue generation ─────────────────────────────────────────


class TestBatchDialogueGeneration:
    """Step 8: Batch dialogues array with SSE per-line push."""

    async def test_batch_dialogues_array_format(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """Speaker returns dialogues array — should emit multiple speaker_turn SSE events."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        char_b = _make_character("常伟思", CHAR_B_ID)
        mock_char_repo.list_by_world.return_value = [char_a, char_b]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            {"participants": ["叶文洁", "常伟思"], "first_speaker": "叶文洁"},
            # Batch dialogues: 3 messages in one LLM call
            {
                "dialogues": [
                    {"content": "*看向窗外* 暴风雪来了！", "next_speaker": "常伟思"},
                    {"content": "所有人留在室内。", "next_speaker": "叶文洁"},
                    {"content": "好的，我去检查设备。", "next_speaker": None},
                ]
            },
            {"summary": "暴风雪袭来"},
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        speaker_turns = [e for e in events if e["event"] == "speaker_turn"]
        assert len(speaker_turns) == 3
        assert speaker_turns[0]["data"]["content"] == "*看向窗外* 暴风雪来了！"
        assert speaker_turns[1]["data"]["content"] == "所有人留在室内。"
        assert speaker_turns[2]["data"]["content"] == "好的，我去检查设备。"

    async def test_batch_dialogues_backward_compat_single_content(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """Speaker returns old format (content + next_speaker) — should work as single dialogue."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            # Old format: single content + next_speaker
            {"content": "暴风雪来了！", "next_speaker": None},
            {"summary": "暴风雪袭来"},
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        speaker_turns = [e for e in events if e["event"] == "speaker_turn"]
        assert len(speaker_turns) == 1
        assert speaker_turns[0]["data"]["content"] == "暴风雪来了！"

    async def test_batch_dialogues_hallucinated_next_speaker_filtered(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """Hallucinated next_speaker in dialogues array should be filtered to None."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            {
                "dialogues": [
                    {"content": "暴风雪来了！", "next_speaker": "虚构角色X"},
                ]
            },
            {"summary": "暴风雪袭来"},
        ]

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        speaker_turns = [e for e in events if e["event"] == "speaker_turn"]
        # Should still emit the content, but next_speaker is filtered
        assert len(speaker_turns) == 1
        assert speaker_turns[0]["data"]["content"] == "暴风雪来了！"

    async def test_batch_dialogues_error_returns_empty(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """LLM error in batch dialogue should gracefully degrade (empty dialogues)."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        # Speaker LLM calls fail — _generate_batch_dialogues catches and
        # returns empty. The loop should end the scene immediately.
        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
        ] + [RuntimeError("LLM timeout")] * 10  # All speaker calls fail

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        event_types = [e["event"] for e in events]
        # Should complete without crashing
        assert "done" in event_types
        assert "error" not in event_types

    async def test_batch_dialogues_error_does_not_create_empty_messages(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """When LLM fails, no empty-content messages should be created."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        mock_llm.complete_json.side_effect = [
            _planner_scene("暴风雪"),
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
        ] + [RuntimeError("LLM timeout")] * 10

        events = await _collect_sse(service, WORLD_ID, "暴风雪", _make_request())

        speaker_turns = [e for e in events if e["event"] == "speaker_turn"]
        # No empty messages should be sent
        assert len(speaker_turns) == 0


# ── Step 7: Revise frequency ──────────────────────────────────────────────────


class TestReviseFrequency:
    """Step 7.1: Revise should happen every 2 scenes, not every scene."""

    async def test_revise_every_two_scenes(
        self, service, mock_llm, mock_char_repo, mock_msg_repo, mock_event_repo, mock_world_repo
    ):
        """With 3 scenes, revise should happen after scene 2 (not after scene 1)."""
        char_a = _make_character("叶文洁", CHAR_A_ID)
        mock_char_repo.list_by_world.return_value = [char_a]
        mock_world_repo.get.return_value = None
        mock_event_repo.create.return_value = _make_event()
        mock_event_repo.count_by_world.return_value = 0

        mock_msg_repo.create.return_value = _make_message("测试", "叶文洁")
        mock_msg_repo.list_recent.return_value = []

        # 3 scenes plan
        three_scenes = {
            "event_title": "复杂事件",
            "scenes": [
                {
                    "scene_id": 1,
                    "location": "基地A",
                    "atmosphere": "紧张",
                    "factions": ["A组"],
                    "goal": "讨论",
                },
                {
                    "scene_id": 2,
                    "location": "基地B",
                    "atmosphere": "平静",
                    "factions": ["B组"],
                    "goal": "汇报",
                },
                {
                    "scene_id": 3,
                    "location": "基地C",
                    "atmosphere": "混乱",
                    "factions": ["C组"],
                    "goal": "撤离",
                },
            ],
        }

        mock_llm.complete_json.side_effect = [
            # Planner: 3 scenes
            three_scenes,
            # Scene 1: orchestrator + speaker
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            {"content": "场景1对话", "next_speaker": None},
            # Scene 1 summary (always happens when pending_scenes remain)
            {"summary": "场景1摘要"},
            # Scene 1 revise (scene_index=1, 1 % 2 == 1 → skip revise when condition checks)
            # Actually let me check the condition:
            # should_revise = (
            #     pending_scenes and scene_messages
            #     and (scene_index % 2 == 0 or len(pending_scenes) <= 1)
            # )
            # scene_index after scene 1 = 1, 1 % 2 == 1, len(pending_scenes) = 2 → skip
            # Scene 2: orchestrator + speaker
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            {"content": "场景2对话", "next_speaker": None},
            # Scene 2 summary
            {"summary": "场景2摘要"},
            # Scene 2 revise (scene_index=2, 2 % 2 == 0 → revise)
            {
                "changes": "none",
                "reasoning": "无需调整",
                "updated_scenes": [
                    {
                        "scene_id": 3,
                        "location": "基地C",
                        "atmosphere": "混乱",
                        "factions": ["C组"],
                        "goal": "撤离",
                    }
                ],
            },
            # Scene 3: orchestrator + speaker
            {"participants": ["叶文洁"], "first_speaker": "叶文洁"},
            {"content": "场景3对话", "next_speaker": None},
            # No more pending scenes after scene 3, no summary/revise
        ]

        events = await _collect_sse(service, WORLD_ID, "复杂事件", _make_request())

        event_types = [e["event"] for e in events]
        speaker_turns = [e for e in events if e["event"] == "speaker_turn"]
        assert len(speaker_turns) == 3
        assert "done" in event_types


# ── Round 3: _generate_batch_dialogues defensive checks ────────────────────


class TestGenerateBatchDialogues:
    """Round 3: _generate_batch_dialogues handles malformed LLM output."""

    @pytest.fixture
    def service_for_batch(self):
        return EventDialogueService(
            llm=AsyncMock(),
            character_repo=AsyncMock(),
            message_repo=AsyncMock(),
            event_repo=AsyncMock(),
            world_repo=AsyncMock(),
            session_factory=MagicMock(),
        )

    async def test_returns_empty_dialogues_on_list_result(self, service_for_batch):
        """When complete_json returns a list, return empty dialogues."""
        service_for_batch.llm.complete_json.return_value = [{"content": "test"}]
        result = await service_for_batch._generate_batch_dialogues("sys", "usr", "")
        assert result == {"dialogues": []}

    async def test_returns_empty_dialogues_on_non_list_dialogues_key(self, service_for_batch):
        """When dialogues value is not a list, return empty dialogues."""
        service_for_batch.llm.complete_json.return_value = {"dialogues": "not a list"}
        result = await service_for_batch._generate_batch_dialogues("sys", "usr", "")
        assert result == {"dialogues": []}

    async def test_wraps_old_format_content(self, service_for_batch):
        """Old format (content + next_speaker) should be wrapped in dialogues array."""
        service_for_batch.llm.complete_json.return_value = {
            "content": "你好",
            "next_speaker": "常伟思",
        }
        result = await service_for_batch._generate_batch_dialogues("sys", "usr", "")
        assert result == {"dialogues": [{"content": "你好", "next_speaker": "常伟思"}]}

    async def test_passes_through_valid_dialogues(self, service_for_batch):
        """Valid dialogues array should be returned as-is."""
        expected = {"dialogues": [{"content": "你好", "next_speaker": None}]}
        service_for_batch.llm.complete_json.return_value = expected
        result = await service_for_batch._generate_batch_dialogues("sys", "usr", "")
        assert result == expected

    async def test_returns_empty_on_none_result(self, service_for_batch):
        """When complete_json returns None (shouldn't happen but defensive), return empty."""
        service_for_batch.llm.complete_json.return_value = None
        result = await service_for_batch._generate_batch_dialogues("sys", "usr", "")
        assert result == {"dialogues": []}
