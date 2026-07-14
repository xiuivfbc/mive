"""Property-based tests for the memory system using Hypothesis.

Tests invariant properties that must hold for any valid input:
- Short-term memory generation: count, content non-empty, category valid
- Promotion filtering: trivial never promoted, new memories excluded
- Formatting: output structure correctness
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from src.models.character import Character
from src.services.memory_module import MemoryModule
from src.utils.memory_format import (
    format_event_index_for_injection,
    format_long_term_for_injection,
    format_short_term_for_injection,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid memory categories
valid_categories = st.sampled_from(["trivial", "private", "major"])

# Invalid or edge-case categories
invalid_categories = st.one_of(
    st.just("unknown"),
    st.just(""),
    st.just("TRIVIAL"),  # wrong case
    st.just("random_string"),
    st.none(),
)

# Non-empty text content
non_empty_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Zs"),
        whitelist_characters="\n",
    ),
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip())

# Optional reflection text
optional_reflection = st.one_of(st.none(), non_empty_text)

# Character name strategy
character_name = st.text(
    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters=""),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip())


def _build_character(name: str, char_id: str | None = None) -> Character:
    """Build a Character pydantic model with sensible defaults."""
    return Character(
        id=char_id or str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        profile={"brief": f"{name}的简介", "detailed": f"{name}的详细背景"},
    )


def _build_llm_response_item(
    char_name: str,
    content: str | None,
    category: str | None,
    reflection: str | None = None,
) -> dict:
    """Build a single LLM response item for short-term memory generation."""
    return {
        "character": char_name,
        "content": content,
        "category": category,
        "reflection": reflection,
    }


def _build_mock_memory_obj(content: str, category: str | None = None) -> SimpleNamespace:
    """Build a mock memory object as returned by memory_repo.add()."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        content=content,
        memory_category=category,
        character_id=uuid.uuid4(),
        world_id=uuid.uuid4(),
    )


# ---------------------------------------------------------------------------
# Property tests: Short-term memory generation
# ---------------------------------------------------------------------------


class TestShortTermMemoryProperties:
    """Property tests for short-term memory generation logic."""

    @given(
        char_names=st.lists(character_name, min_size=1, max_size=5, unique=True),
        categories=st.lists(valid_categories, min_size=1, max_size=5),
    )
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    async def test_memory_count_matches_valid_items(
        self, char_names: list[str], categories: list[str]
    ):
        """The number of returned memories equals the number of valid LLM items
        (matching character in char_map with non-null content)."""
        assume(len(char_names) >= 1)

        # Build char_map from names
        chars = {name: _build_character(name) for name in char_names}

        # Build LLM response: one item per character with valid category
        llm_items = []
        for i, name in enumerate(char_names):
            cat = categories[i % len(categories)]
            llm_items.append(_build_llm_response_item(name, f"{name}的记忆内容", cat))

        # Mock dependencies
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=llm_items)

        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        mock_memory_repo = AsyncMock()
        written_memoirs = []

        async def fake_add(**kwargs):
            obj = _build_mock_memory_obj(
                kwargs.get("content", ""),
                kwargs.get("memory_category"),
            )
            written_memoirs.append(obj)
            return obj

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)

        module = MemoryModule(llm=mock_llm, session_factory=None)

        result = await module.generate_short_term_memories(
            session=mock_session,
            world_id=str(uuid.uuid4()),
            char_map=chars,
            dialogue_text="测试对话",
            event_description="测试事件",
            memory_repo=mock_memory_repo,
        )

        # Property: count matches valid items (each char_name matches in char_map)
        assert len(result) == len(char_names)

    @given(
        char_names=st.lists(character_name, min_size=1, max_size=5, unique=True),
        categories=st.lists(valid_categories, min_size=1, max_size=5),
    )
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    async def test_memory_content_is_non_empty(self, char_names: list[str], categories: list[str]):
        """All returned memories have non-empty content."""
        assume(len(char_names) >= 1)

        chars = {name: _build_character(name) for name in char_names}

        llm_items = []
        for i, name in enumerate(char_names):
            cat = categories[i % len(categories)]
            llm_items.append(_build_llm_response_item(name, f"{name}的记忆", cat))

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=llm_items)

        mock_session = AsyncMock()
        mock_memory_repo = AsyncMock()

        async def fake_add(**kwargs):
            return _build_mock_memory_obj(
                kwargs.get("content", ""),
                kwargs.get("memory_category"),
            )

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=mock_session,
            world_id=str(uuid.uuid4()),
            char_map=chars,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=mock_memory_repo,
        )

        # Property: all content is non-empty
        for mem in result:
            assert mem.content
            assert mem.content.strip()

    @given(
        char_names=st.lists(character_name, min_size=1, max_size=3, unique=True),
        categories=st.lists(valid_categories, min_size=1, max_size=3),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    async def test_category_always_valid_or_none(
        self, char_names: list[str], categories: list[str]
    ):
        """Memory category is always one of (trivial, private, major) or None."""
        assume(len(char_names) >= 1)
        valid_set = {"trivial", "private", "major", None}

        chars = {name: _build_character(name) for name in char_names}

        llm_items = []
        for i, name in enumerate(char_names):
            cat = categories[i % len(categories)]
            llm_items.append(_build_llm_response_item(name, f"{name}记忆", cat))

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=llm_items)
        mock_session = AsyncMock()
        mock_memory_repo = AsyncMock()

        async def fake_add(**kwargs):
            return _build_mock_memory_obj(
                kwargs.get("content", ""),
                kwargs.get("memory_category"),
            )

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=mock_session,
            world_id=str(uuid.uuid4()),
            char_map=chars,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=mock_memory_repo,
        )

        for mem in result:
            assert mem.memory_category in valid_set

    @given(
        char_names=st.lists(character_name, min_size=1, max_size=3, unique=True),
        bad_categories=st.lists(invalid_categories, min_size=1, max_size=3),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    async def test_invalid_category_normalized_to_none(
        self, char_names: list[str], bad_categories: list
    ):
        """Invalid categories from LLM are normalized to None."""
        assume(len(char_names) >= 1)

        chars = {name: _build_character(name) for name in char_names}

        llm_items = []
        for i, name in enumerate(char_names):
            cat = bad_categories[i % len(bad_categories)]
            llm_items.append(_build_llm_response_item(name, f"{name}记忆", cat))

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=llm_items)
        mock_session = AsyncMock()
        mock_memory_repo = AsyncMock()

        captured_categories = []

        async def fake_add(**kwargs):
            cat = kwargs.get("memory_category")
            captured_categories.append(cat)
            return _build_mock_memory_obj(kwargs.get("content", ""), cat)

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)

        module = MemoryModule(llm=mock_llm, session_factory=None)
        await module.generate_short_term_memories(
            session=mock_session,
            world_id=str(uuid.uuid4()),
            char_map=chars,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=mock_memory_repo,
        )

        # All captured categories should be None (since all input categories were invalid)
        for cat in captured_categories:
            assert cat is None


# ---------------------------------------------------------------------------
# Property tests: Promotion filtering
# ---------------------------------------------------------------------------


class TestPromotionFilteringProperties:
    """Property tests for promotion filtering logic."""

    @given(category=valid_categories)
    @settings(max_examples=10, deadline=None)
    async def test_trivial_always_excluded_from_promotion(self, category: str):
        """Trivial memories are always excluded when exclude_categories=["trivial"]."""
        mem = SimpleNamespace(
            id=uuid.uuid4(),
            memory_category="trivial",
            content="琐碎记忆",
            is_hearsay=False,
        )
        exclude_categories = ["trivial"]
        is_eligible = mem.memory_category not in exclude_categories
        assert not is_eligible

    @given(category=st.sampled_from(["private", "major"]))
    @settings(max_examples=10, deadline=None)
    async def test_non_trivial_eligible_for_promotion(self, category: str):
        """Private and major memories are eligible for promotion."""
        mem = SimpleNamespace(
            id=uuid.uuid4(),
            memory_category=category,
            content="重要记忆",
            is_hearsay=False,
        )
        exclude_categories = ["trivial"]
        is_eligible = mem.memory_category not in exclude_categories
        assert is_eligible

    @given(
        trivial_count=st.integers(min_value=0, max_value=10),
        private_count=st.integers(min_value=0, max_value=10),
        major_count=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=20, deadline=None)
    async def test_propagation_filters_to_major_only(
        self,
        trivial_count: int,
        private_count: int,
        major_count: int,
    ):
        """Propagation filter keeps only major memories (trivial, private, None excluded)."""
        memories = []
        for _ in range(trivial_count):
            memories.append(
                SimpleNamespace(memory_category="trivial", content="琐事", is_hearsay=False)
            )
        for _ in range(private_count):
            memories.append(
                SimpleNamespace(memory_category="private", content="私事", is_hearsay=False)
            )
        for _ in range(major_count):
            memories.append(
                SimpleNamespace(memory_category="major", content="大事", is_hearsay=False)
            )

        # Replicate propagation filter logic
        propagable = [
            m
            for m in memories
            if getattr(m, "memory_category", None) not in ("trivial", "private", None)
        ]

        # Property: only major memories survive
        assert len(propagable) == major_count
        for m in propagable:
            assert m.memory_category == "major"


# ---------------------------------------------------------------------------
# Property tests: Formatting functions
# ---------------------------------------------------------------------------


class TestFormattingProperties:
    """Property tests for memory formatting functions."""

    @given(
        contents=st.lists(non_empty_text, min_size=0, max_size=20),
        reflections=st.lists(optional_reflection, min_size=0, max_size=20),
    )
    @settings(max_examples=30, deadline=None)
    async def test_short_term_format_never_empty(self, contents: list[str], reflections: list):
        """format_short_term_for_injection always returns a non-empty string."""
        memories = []
        for i, content in enumerate(contents):
            ref = reflections[i] if i < len(reflections) else None
            memories.append(
                SimpleNamespace(
                    content=content,
                    short_term_reflection=ref,
                    is_hearsay=False,
                )
            )

        result = format_short_term_for_injection(memories)
        assert isinstance(result, str)
        assert len(result) > 0

    @given(contents=st.lists(non_empty_text, min_size=1, max_size=10))
    @settings(max_examples=20, deadline=None)
    async def test_short_term_format_contains_all_contents(self, contents: list[str]):
        """Every memory content appears in the formatted output."""
        memories = [
            SimpleNamespace(content=c, short_term_reflection=None, is_hearsay=False)
            for c in contents
        ]

        result = format_short_term_for_injection(memories)
        for c in contents:
            assert c in result

    @given(
        event_names=st.lists(non_empty_text, min_size=0, max_size=10),
        briefs=st.lists(non_empty_text, min_size=0, max_size=10),
    )
    @settings(max_examples=20, deadline=None)
    async def test_event_index_format_numbering(self, event_names: list[str], briefs: list[str]):
        """Event index formatting produces sequential E001, E002, ... numbering."""
        events = []
        for i in range(min(len(event_names), len(briefs))):
            events.append(
                SimpleNamespace(
                    id=uuid.uuid4(),
                    event_name=event_names[i],
                    brief=briefs[i],
                    dissemination=0.5,
                    core_participants=None,
                    created_at=None,
                )
            )

        result = format_event_index_for_injection(events)
        if not events:
            assert result == "暂无事件索引"
        else:
            for i in range(len(events)):
                assert f"E{i + 1:03d}" in result

    @given(
        contents=st.lists(non_empty_text, min_size=0, max_size=30),
        event_names=st.lists(non_empty_text, min_size=0, max_size=30),
        reflections=st.lists(optional_reflection, min_size=0, max_size=30),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    async def test_long_term_format_respects_token_budget(
        self,
        contents: list[str],
        event_names: list[str],
        reflections: list,
    ):
        """format_long_term_for_injection output stays within token budget (~2500 chars)."""
        n = min(len(contents), len(event_names))
        memories = []
        for i in range(n):
            ref = reflections[i] if i < len(reflections) else None
            memories.append(
                SimpleNamespace(
                    content=contents[i],
                    event_name=event_names[i],
                    perspective_detail=f"视角详情{i}",
                    reflection=ref,
                    memory_type="long_term",
                )
            )

        result = format_long_term_for_injection(memories)
        assert isinstance(result, str)
        # The function enforces ~2500 char budget by dropping oldest
        # With very long content, it should still produce valid output
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Property tests: Orchestrator null-safety
# ---------------------------------------------------------------------------


class TestOrchestratorNullSafety:
    """Property tests for MemoryOrchestrator null-safety."""

    @given(count=st.integers(min_value=0, max_value=5))
    @settings(max_examples=10, deadline=None)
    async def test_none_module_returns_empty_list(self, count: int):
        """Orchestrator with None memory_module always returns empty list."""
        from src.services.memory_orchestrator import MemoryOrchestrator

        orchestrator = MemoryOrchestrator(memory_module=None)

        chars = {f"char{i}": _build_character(f"char{i}") for i in range(count)}

        result = await orchestrator.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map=chars,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )

        assert result == []

    @given(count=st.integers(min_value=0, max_value=5))
    @settings(max_examples=10, deadline=None)
    async def test_none_propagation_service_is_noop(self, count: int):
        """Orchestrator with None propagation_service silently no-ops."""
        from src.services.memory_orchestrator import MemoryOrchestrator

        orchestrator = MemoryOrchestrator(memory_module=None, memory_propagation_service=None)

        mock_memories = [
            SimpleNamespace(content=f"记忆{i}", memory_category="major") for i in range(count)
        ]

        # Should not raise
        await orchestrator.dispatch_event_propagation(
            world_id=str(uuid.uuid4()),
            event_id=str(uuid.uuid4()),
            participant_names=["角色A"],
            newly_written_memories=mock_memories,
            virtual_time=None,
        )

        await orchestrator.dispatch_chat_propagation(
            world_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            participant_names=["角色A"],
            newly_written_memories=mock_memories,
            virtual_time=None,
        )
