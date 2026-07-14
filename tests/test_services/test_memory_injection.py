"""Tests for improved memory injection (P0: forced recent + vector search).

Tests the actual format functions from src.utils.memory_format:
- format_short_term_for_injection: forced recent 1-2 + hint
- format_long_term_for_injection: structured fields + token budget
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.db.models import M2CharacterMemory
from src.utils.memory_format import (
    _FORCE_RECENT_COUNT,
    _LONG_TERM_TOKEN_BUDGET,
    _RECENT_HINT,
    format_long_term_for_injection,
    format_short_term_for_injection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(
    content: str = "记忆内容",
    memory_type: str = "short_term",
    created_at: datetime | None = None,
    is_hearsay: bool = False,
    event_name: str | None = None,
    perspective_detail: str | None = None,
    reflection: str | None = None,
    **kwargs,
) -> M2CharacterMemory:
    """Build an in-memory M2CharacterMemory."""
    mem = M2CharacterMemory(
        id=uuid.uuid4(),
        character_id=uuid.uuid4(),
        world_id=uuid.uuid4(),
        memory_type=memory_type,
        content=content,
        created_at=created_at or datetime.now(UTC).replace(tzinfo=None),
        is_hearsay=is_hearsay,
        event_name=event_name,
        perspective_detail=perspective_detail,
        reflection=reflection,
    )
    for k, v in kwargs.items():
        object.__setattr__(mem, k, v)
    return mem


# ---------------------------------------------------------------------------
# format_short_term_for_injection tests
# ---------------------------------------------------------------------------


class TestFormatShortTerm:
    """Test format_short_term_for_injection with actual function."""

    def test_empty_memories_returns_placeholder(self):
        result = format_short_term_for_injection([])
        assert result == "暂无"

    def test_single_memory_gets_hint(self):
        mem = _make_memory("唯一记忆")
        result = format_short_term_for_injection([mem])
        assert _RECENT_HINT in result
        assert "唯一记忆" in result

    def test_two_memories_both_get_hint(self):
        m1 = _make_memory("新记忆")
        m2 = _make_memory("次新记忆")
        result = format_short_term_for_injection([m1, m2])
        assert _RECENT_HINT in result
        assert "新记忆" in result
        assert "次新记忆" in result

    def test_three_memories_only_first_two_get_hint(self):
        m1 = _make_memory("最新")
        m2 = _make_memory("次新")
        m3 = _make_memory("最旧")
        result = format_short_term_for_injection([m1, m2, m3])
        lines = result.split("\n")
        # First line is the hint
        assert _RECENT_HINT in lines[0]
        assert "最新" in lines[1]
        assert "次新" in lines[2]
        assert "最旧" in lines[3]
        # Only one hint line
        hint_count = sum(1 for line in lines if _RECENT_HINT in line)
        assert hint_count == 1

    def test_newest_first_ordering(self):
        """Format function expects newest first (index 0 = most recent)."""
        now = datetime.now(UTC).replace(tzinfo=None)
        m_new = _make_memory("新记忆", created_at=now)
        m_old = _make_memory("旧记忆", created_at=now - timedelta(hours=2))
        result = format_short_term_for_injection([m_new, m_old])
        lines = result.split("\n")
        # Hint + newest first
        assert "新记忆" in lines[1]
        assert "旧记忆" in lines[2]

    def test_five_memories(self):
        """With 5 memories, only first 2 get forced injection with hint."""
        mems = [_make_memory(f"记忆{i}") for i in range(5)]
        result = format_short_term_for_injection(mems)
        lines = result.split("\n")
        # 1 hint + 5 content lines
        assert len(lines) == 6
        assert _RECENT_HINT in lines[0]


# ---------------------------------------------------------------------------
# format_long_term_for_injection tests
# ---------------------------------------------------------------------------


class TestFormatLongTerm:
    """Test format_long_term_for_injection with actual function."""

    def test_empty_memories_returns_placeholder(self):
        result = format_long_term_for_injection([])
        assert result == "暂无"

    def test_structured_memory_format(self):
        mem = _make_memory(
            memory_type="long_term",
            content="旧内容",
            event_name="王城之变",
            perspective_detail="我亲眼目睹了政变",
            reflection="权力斗争的残酷",
        )
        result = format_long_term_for_injection([mem])
        assert "[王城之变]" in result
        assert "我亲眼目睹了政变" in result
        assert "感悟：权力斗争的残酷" in result

    def test_structured_memory_no_reflection(self):
        mem = _make_memory(
            memory_type="long_term",
            content="旧内容",
            event_name="王城之变",
            perspective_detail="我亲眼目睹了政变",
            reflection=None,
        )
        result = format_long_term_for_injection([mem])
        assert "[王城之变]" in result
        assert "感悟：" not in result

    def test_legacy_memory_uses_content(self):
        """Legacy memories without event_name fall back to content."""
        mem = _make_memory(
            memory_type="long_term",
            content="旧格式记忆文本",
            event_name=None,
        )
        result = format_long_term_for_injection([mem])
        assert "旧格式记忆文本" in result
        assert "[" not in result  # No event_name brackets

    def test_mixed_structured_and_legacy(self):
        structured = _make_memory(
            memory_type="long_term",
            content="结构化内容",
            event_name="结构化事件",
            perspective_detail="详情",
        )
        legacy = _make_memory(
            memory_type="long_term",
            content="旧格式记忆",
            event_name=None,
        )
        result = format_long_term_for_injection([structured, legacy])
        assert "[结构化事件]" in result
        assert "旧格式记忆" in result

    def test_token_budget_truncates_oldest(self):
        """When over budget, oldest memories are dropped."""
        now = datetime.now(UTC).replace(tzinfo=None)
        # Create a very long old memory (perspective_detail = 3000 chars > 2500 budget)
        old_mem = _make_memory(
            memory_type="long_term",
            content="旧" * 3000,
            event_name="旧事件",
            perspective_detail="旧" * 3000,
            created_at=now - timedelta(days=30),
        )
        new_mem = _make_memory(
            memory_type="long_term",
            content="新记忆",
            event_name="新事件",
            perspective_detail="新详情",
            created_at=now,
        )
        result = format_long_term_for_injection([old_mem, new_mem])
        # Old memory should be dropped, new one kept
        assert "[新事件]" in result
        assert "[旧事件]" not in result

    def test_single_oversized_memory_preserved(self):
        """Even if a single memory exceeds budget, it's preserved."""
        mem = _make_memory(
            memory_type="long_term",
            content="超" * 3000,
            event_name="超大事件",
            perspective_detail="超" * 3000,
        )
        result = format_long_term_for_injection([mem])
        assert "[超大事件]" in result

    def test_budget_constant_value(self):
        assert _LONG_TERM_TOKEN_BUDGET == 2500

    def test_force_recent_count_value(self):
        assert _FORCE_RECENT_COUNT == 2


# ---------------------------------------------------------------------------
# Hearsay exclusion
# ---------------------------------------------------------------------------


class TestHearsayExclusion:
    """Verify hearsay memories are excluded from forced injection."""

    def test_hearsay_excluded_by_caller(self):
        """The format function receives whatever the caller provides.
        Exclusion is the caller's responsibility (list_short_term
        already excludes hearsay by default)."""
        now = datetime.now(UTC).replace(tzinfo=None)
        m1 = _make_memory("真实记忆", created_at=now, is_hearsay=False)
        m2 = _make_memory("传闻记忆", created_at=now, is_hearsay=True)
        # Caller should filter: only pass non-hearsay
        non_hearsay = [m for m in [m1, m2] if not m.is_hearsay]
        result = format_short_term_for_injection(non_hearsay)
        assert "真实记忆" in result
        assert "传闻记忆" not in result
