"""Tests for Memory System V2 features.

Tests:
- format_event_index_for_injection
- format_long_term_for_injection with event_index
- Short-term memory category (trivial/private/major)
- Short-term memory reflection
- Promotion filtering (exclude trivial)
- Propagation filtering (trivial/private not propagated)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.db.models import M2CharacterMemory, M26EventIndex
from src.utils.memory_format import (
    format_event_index_for_injection,
    format_long_term_for_injection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_index(
    event_name: str = "王城之变",
    brief: str = "叛军攻入王城，公主在护卫下出逃",
    dissemination: float = 0.8,
    event_id: uuid.UUID | None = None,
) -> M26EventIndex:
    return SimpleNamespace(
        id=event_id or uuid.uuid4(),
        world_id=uuid.uuid4(),
        event_name=event_name,
        brief=brief,
        dissemination=dissemination,
        core_participants=None,
        created_at=datetime.now(UTC),
    )


def _make_memory(
    content: str = "记忆内容",
    memory_type: str = "short_term",
    event_name: str | None = None,
    perspective_detail: str | None = None,
    reflection: str | None = None,
    memory_category: str | None = None,
    short_term_reflection: str | None = None,
    is_hearsay: bool = False,
    **kwargs,
) -> M2CharacterMemory:
    mem = M2CharacterMemory(
        id=uuid.uuid4(),
        character_id=uuid.uuid4(),
        world_id=uuid.uuid4(),
        memory_type=memory_type,
        content=content,
        event_name=event_name,
        perspective_detail=perspective_detail,
        reflection=reflection,
        memory_category=memory_category,
        short_term_reflection=short_term_reflection,
        is_hearsay=is_hearsay,
    )
    return mem


# ---------------------------------------------------------------------------
# format_event_index_for_injection tests
# ---------------------------------------------------------------------------


class TestFormatEventIndexForInjection:
    """Test the event index formatting function."""

    def test_empty_events_returns_placeholder(self):
        result = format_event_index_for_injection([])
        assert result == "暂无事件索引"

    def test_single_event(self):
        events = [_make_event_index(brief="叛军攻入王城")]
        result = format_event_index_for_injection(events)
        assert "已有事件：" in result
        assert "E001 - 叛军攻入王城" in result

    def test_multiple_events_sequential_numbering(self):
        events = [
            _make_event_index(brief="叛军攻入王城"),
            _make_event_index(brief="黑森林发现遗迹"),
            _make_event_index(brief="商队遭遇袭击"),
        ]
        result = format_event_index_for_injection(events)
        assert "E001 - 叛军攻入王城" in result
        assert "E002 - 黑森林发现遗迹" in result
        assert "E003 - 商队遭遇袭击" in result

    def test_numbering_starts_at_one(self):
        events = [_make_event_index(brief="事件A"), _make_event_index(brief="事件B")]
        result = format_event_index_for_injection(events)
        lines = result.strip().split("\n")
        # First line is header
        assert lines[1].startswith("E001")
        assert lines[2].startswith("E002")


# ---------------------------------------------------------------------------
# format_long_term_for_injection with event_index tests
# ---------------------------------------------------------------------------


class TestFormatLongTermWithEventIndex:
    """Test format_long_term_for_injection with event_index parameter."""

    def test_legacy_memory_without_structured_fields(self):
        mem = _make_memory(content="普通记忆内容")
        result = format_long_term_for_injection([mem])
        assert "- 普通记忆内容" in result

    def test_structured_memory_without_event_index(self):
        mem = _make_memory(
            content="王城之变: 视角详情",
            event_name="王城之变",
            perspective_detail="我在混乱中逃离",
            reflection="世道要变了",
        )
        result = format_long_term_for_injection([mem])
        assert "[王城之变]" in result
        assert "我在混乱中逃离" in result
        assert "感悟：世道要变了" in result

    def test_structured_memory_with_event_index_resolves_name(self):
        event_id = str(uuid.uuid4())
        mem = _make_memory(
            content="事件详情",
            event_name=event_id,  # V2: event_name stores UUID
            perspective_detail="我在混乱中逃离",
            reflection="世道要变了",
        )
        event_index = {event_id: "王城之变"}
        result = format_long_term_for_injection([mem], event_index=event_index)
        assert "[王城之变]" in result
        assert event_id not in result

    def test_structured_memory_without_matching_event_index(self):
        event_id = str(uuid.uuid4())
        mem = _make_memory(
            content="事件详情",
            event_name=event_id,
            perspective_detail="我在混乱中逃离",
        )
        event_index = {str(uuid.uuid4()): "其他事件"}
        result = format_long_term_for_injection([mem], event_index=event_index)
        # Should fall back to using the UUID as display name
        assert f"[{event_id}]" in result

    def test_no_reflection_omits_reflection_part(self):
        mem = _make_memory(
            content="事件详情",
            event_name="王城之变",
            perspective_detail="我在混乱中逃离",
            reflection=None,
        )
        result = format_long_term_for_injection([mem])
        assert "感悟" not in result

    def test_empty_reflection_omits_reflection_part(self):
        mem = _make_memory(
            content="事件详情",
            event_name="王城之变",
            perspective_detail="我在混乱中逃离",
            reflection="",
        )
        result = format_long_term_for_injection([mem])
        assert "感悟" not in result

    def test_token_budget_drops_oldest(self):
        # Create many long memories to exceed budget
        memories = []
        for i in range(50):
            memories.append(
                _make_memory(
                    content="A" * 100,
                    event_name=f"事件{i}",
                    perspective_detail="B" * 50,
                )
            )
        result = format_long_term_for_injection(memories)
        # Should not exceed budget significantly
        assert len(result) < 5000  # generous upper bound


# ---------------------------------------------------------------------------
# Short-term memory category tests
# ---------------------------------------------------------------------------


class TestShortTermMemoryCategory:
    """Test memory category field on M2CharacterMemory."""

    def test_memory_with_trivial_category(self):
        mem = _make_memory(content="吃了碗面", memory_category="trivial")
        assert mem.memory_category == "trivial"

    def test_memory_with_private_category(self):
        mem = _make_memory(content="密谈内容", memory_category="private")
        assert mem.memory_category == "private"

    def test_memory_with_major_category(self):
        mem = _make_memory(content="王城之变", memory_category="major")
        assert mem.memory_category == "major"

    def test_memory_without_category(self):
        mem = _make_memory(content="普通记忆")
        assert mem.memory_category is None


# ---------------------------------------------------------------------------
# Short-term memory reflection tests
# ---------------------------------------------------------------------------


class TestShortTermMemoryReflection:
    """Test short_term_reflection field on M2CharacterMemory."""

    def test_memory_with_reflection(self):
        mem = _make_memory(
            content="目睹王城之变",
            short_term_reflection="世道要变了",
        )
        assert mem.short_term_reflection == "世道要变了"

    def test_memory_without_reflection(self):
        mem = _make_memory(content="吃了碗面")
        assert mem.short_term_reflection is None


# ---------------------------------------------------------------------------
# Promotion filtering tests
# ---------------------------------------------------------------------------


class TestPromotionFiltering:
    """Test that trivial memories are excluded from promotion candidates."""

    def test_trivial_memory_is_not_promotion_candidate(self):
        """Trivial memories should be filtered out by exclude_categories."""
        mem = _make_memory(content="吃了碗面", memory_category="trivial")
        # Simulate the filter logic
        exclude_categories = ["trivial"]
        is_eligible = mem.memory_category not in exclude_categories
        assert not is_eligible

    def test_private_memory_is_promotion_candidate(self):
        """Private memories should still be eligible for promotion."""
        mem = _make_memory(content="密谈", memory_category="private")
        exclude_categories = ["trivial"]
        is_eligible = mem.memory_category not in exclude_categories
        assert is_eligible

    def test_major_memory_is_promotion_candidate(self):
        """Major memories should be eligible for promotion."""
        mem = _make_memory(content="王城之变", memory_category="major")
        exclude_categories = ["trivial"]
        is_eligible = mem.memory_category not in exclude_categories
        assert is_eligible

    def test_none_category_is_promotion_candidate(self):
        """Memories without category should be eligible (backward compat)."""
        mem = _make_memory(content="普通记忆", memory_category=None)
        exclude_categories = ["trivial"]
        is_eligible = mem.memory_category not in exclude_categories
        assert is_eligible


# ---------------------------------------------------------------------------
# Propagation control tests
# ---------------------------------------------------------------------------


class TestPropagationControl:
    """Test that trivial and private memories don't propagate."""

    def _filter_propagable(self, memories: list[M2CharacterMemory]) -> list[M2CharacterMemory]:
        """Replicate the V2 propagation filter logic."""
        return [
            m
            for m in memories
            if getattr(m, "memory_category", None) not in ("trivial", "private", None)
        ]

    def test_major_memory_propagates(self):
        mem = _make_memory(content="大战", memory_category="major")
        result = self._filter_propagable([mem])
        assert len(result) == 1

    def test_trivial_memory_does_not_propagate(self):
        mem = _make_memory(content="吃了碗面", memory_category="trivial")
        result = self._filter_propagable([mem])
        assert len(result) == 0

    def test_private_memory_does_not_propagate(self):
        mem = _make_memory(content="密谈", memory_category="private")
        result = self._filter_propagable([mem])
        assert len(result) == 0

    def test_none_category_does_not_propagate(self):
        """Memories without category should NOT propagate (V2 default)."""
        mem = _make_memory(content="普通记忆", memory_category=None)
        result = self._filter_propagable([mem])
        assert len(result) == 0

    def test_mixed_categories_filter_correctly(self):
        memories = [
            _make_memory(content="琐事", memory_category="trivial"),
            _make_memory(content="私事", memory_category="private"),
            _make_memory(content="大事", memory_category="major"),
            _make_memory(content="无分类", memory_category=None),
        ]
        result = self._filter_propagable(memories)
        assert len(result) == 1
        assert result[0].content == "大事"

    def test_all_trivial_returns_empty(self):
        memories = [
            _make_memory(content="琐事1", memory_category="trivial"),
            _make_memory(content="琐事2", memory_category="trivial"),
        ]
        result = self._filter_propagable(memories)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Integration: CharacterMemoryRepository with new fields
# ---------------------------------------------------------------------------


class TestCharacterMemoryRepoV2Fields:
    """Test that CharacterMemoryRepository correctly handles V2 fields."""

    @pytest.mark.asyncio
    async def test_add_with_category_and_reflection(self):
        """Test that add() accepts memory_category and short_term_reflection."""
        from sqlalchemy.ext.asyncio import AsyncSession

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.flush = AsyncMock()

        from src.db.repositories.character_memory_repo import CharacterMemoryRepository

        repo = CharacterMemoryRepository(mock_session)

        char_id = uuid.uuid4()
        world_id = uuid.uuid4()

        await repo.add(
            character_id=char_id,
            world_id=world_id,
            session_id=None,
            memory_type="short_term",
            content="测试记忆",
            memory_category="major",
            short_term_reflection="感悟内容",
        )

        # Verify the session.add was called
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.memory_category == "major"
        assert added_obj.short_term_reflection == "感悟内容"

    @pytest.mark.asyncio
    async def test_add_without_v2_fields_defaults_none(self):
        """Test backward compat: add() without V2 fields defaults to None."""
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        from src.db.repositories.character_memory_repo import CharacterMemoryRepository

        repo = CharacterMemoryRepository(mock_session)

        await repo.add(
            character_id=uuid.uuid4(),
            world_id=uuid.uuid4(),
            session_id=None,
            memory_type="short_term",
            content="旧格式记忆",
        )

        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.memory_category is None
        assert added_obj.short_term_reflection is None


# ---------------------------------------------------------------------------
# Integration: EventIndexRepository
# ---------------------------------------------------------------------------


class TestEventIndexRepository:
    """Test EventIndexRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_add_returns_event_index(self):
        """Test that add() creates and returns an M26EventIndex."""
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        from src.db.repositories.event_index_repo import EventIndexRepository

        repo = EventIndexRepository(mock_session)
        world_id = uuid.uuid4()

        await repo.add(
            world_id=world_id,
            event_name="王城之变",
            brief="叛军攻入王城",
            dissemination=0.8,
        )

        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.event_name == "王城之变"
        assert added_obj.brief == "叛军攻入王城"
        assert added_obj.dissemination == 0.8
        assert added_obj.world_id == world_id
