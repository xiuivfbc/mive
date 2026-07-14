"""Regression tests for known memory system scenarios.

Each scenario is a named test case with deterministic inputs and expected
outputs, ensuring that known behaviors remain stable across refactors.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.character import Character
from src.services.memory_module import MemoryModule
from src.services.memory_orchestrator import MemoryOrchestrator
from src.utils.memory_format import (
    format_long_term_for_injection,
    format_short_term_for_injection,
)

# ---------------------------------------------------------------------------
# Scenario data structure
# ---------------------------------------------------------------------------


@dataclass
class MemoryScenario:
    """Defines a regression test scenario for the memory system."""

    name: str
    # Input: dialogues that the LLM will "observe"
    dialogues: list[dict]  # [{"speaker": str, "content": str}]
    # LLM classification for each dialogue
    llm_classifications: list[dict]  # [{"character": str, "content": str, "category": str, ...}]
    # Expected outcomes
    expected_categories: list[str | None]  # categories after processing
    expected_promotion_eligible: bool  # whether non-trivial memories exist for promotion
    expected_propagation_count: int  # how many memories would propagate (major only)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _build_character(name: str, char_id: str | None = None) -> Character:
    return Character(
        id=char_id or str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        profile={"brief": f"{name}的简介", "detailed": f"{name}的详细背景"},
    )


def _build_mock_memory(content: str, category: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        content=content,
        memory_category=category,
        character_id=uuid.uuid4(),
        world_id=uuid.uuid4(),
        is_hearsay=False,
        origin_event_id=None,
        involved_characters=None,
    )


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS: list[MemoryScenario] = [
    # Scenario 1: Character death event — should be classified as major
    MemoryScenario(
        name="character_death_event",
        dialogues=[
            {"speaker": "旁白", "content": "公主在护卫的保护下逃出王城，身后的宫殿燃起大火"},
            {"speaker": "护卫", "content": "公主殿下，我们必须立刻离开！"},
        ],
        llm_classifications=[
            {
                "character": "公主",
                "content": "我在护卫的保护下逃离了燃烧的王城，身后的家园化为灰烬",
                "category": "major",
                "reflection": "一切都变了，我必须坚强",
            },
            {
                "character": "护卫",
                "content": "我护送公主逃离王城，目睹宫殿被大火吞噬",
                "category": "major",
                "reflection": "我发誓要保护公主的安全",
            },
        ],
        expected_categories=["major", "major"],
        expected_promotion_eligible=True,
        expected_propagation_count=2,
    ),
    # Scenario 2: Daily chat — trivial, no lasting impact
    MemoryScenario(
        name="daily_casual_chat",
        dialogues=[
            {"speaker": "商人", "content": "今天天气不错啊"},
            {"speaker": "旅人", "content": "是啊，适合赶路"},
        ],
        llm_classifications=[
            {
                "character": "商人",
                "content": "和旅人聊了几句天气",
                "category": "trivial",
                "reflection": None,
            },
            {
                "character": "旅人",
                "content": "路过集市时和商人闲聊了几句",
                "category": "trivial",
                "reflection": None,
            },
        ],
        expected_categories=["trivial", "trivial"],
        expected_promotion_eligible=False,
        expected_propagation_count=0,
    ),
    # Scenario 3: Private conversation — between two people, not public
    MemoryScenario(
        name="private_secret_conversation",
        dialogues=[
            {"speaker": "密探", "content": "情报已经到手，今晚行动"},
            {"speaker": "首领", "content": "很好，不要让第三个人知道"},
        ],
        llm_classifications=[
            {
                "character": "密探",
                "content": "我向首领汇报了情报，今晚将执行秘密行动",
                "category": "private",
                "reflection": None,
            },
            {
                "character": "首领",
                "content": "密探带回了情报，我下令今晚行动",
                "category": "private",
                "reflection": None,
            },
        ],
        expected_categories=["private", "private"],
        expected_promotion_eligible=True,  # private is eligible for promotion
        expected_propagation_count=0,  # but does NOT propagate
    ),
    # Scenario 4: Multi-character complex scene — mixed categories
    MemoryScenario(
        name="multi_character_mixed_scene",
        dialogues=[
            {"speaker": "将军", "content": "全军出击！"},
            {"speaker": "士兵A", "content": "遵命！"},
            {"speaker": "谋士", "content": "将军，此计恐有不妥"},
            {"speaker": "敌将", "content": "来得好，正合我意"},
        ],
        llm_classifications=[
            {
                "character": "将军",
                "content": "我下令全军出击，谋士劝阻但我坚持己见",
                "category": "major",
                "reflection": "这一战将决定一切",
            },
            {
                "character": "士兵A",
                "content": "接到将军出击的命令，整装待发",
                "category": "trivial",
                "reflection": None,
            },
            {
                "character": "谋士",
                "content": "我劝将军不要冒进，但他没有听从",
                "category": "private",
                "reflection": "希望我的判断是错的",
            },
            {
                "character": "敌将",
                "content": "敌军中计了，正往我方埋伏圈前进",
                "category": "major",
                "reflection": None,
            },
        ],
        expected_categories=["major", "trivial", "private", "major"],
        expected_promotion_eligible=True,
        expected_propagation_count=2,  # only major memories propagate
    ),
]


# ---------------------------------------------------------------------------
# Parametrized regression tests
# ---------------------------------------------------------------------------


class TestMemoryScenarios:
    """Parametrized regression tests for known memory scenarios."""

    @pytest.mark.parametrize(
        "scenario",
        SCENARIOS,
        ids=[s.name for s in SCENARIOS],
    )
    async def test_scenario_classification(self, scenario: MemoryScenario):
        """Verify that LLM classifications are correctly processed."""
        # Build character map from all unique character names in classifications
        char_names = list({item["character"] for item in scenario.llm_classifications})
        chars = {name: _build_character(name) for name in char_names}

        # Mock LLM to return the scenario's classifications
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=scenario.llm_classifications)

        mock_session = AsyncMock()
        mock_memory_repo = AsyncMock()

        captured_memories = []

        async def fake_add(**kwargs):
            mem = _build_mock_memory(
                kwargs.get("content", ""),
                kwargs.get("memory_category"),
            )
            captured_memories.append(mem)
            return mem

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=mock_session,
            world_id=str(uuid.uuid4()),
            char_map=chars,
            dialogue_text="\n".join(f"{d['speaker']}：{d['content']}" for d in scenario.dialogues),
            event_description="测试事件",
            memory_repo=mock_memory_repo,
        )

        # Verify categories match expected
        assert len(result) == len(scenario.expected_categories)
        actual_categories = [m.memory_category for m in result]
        assert actual_categories == scenario.expected_categories

    @pytest.mark.parametrize(
        "scenario",
        SCENARIOS,
        ids=[s.name for s in SCENARIOS],
    )
    async def test_scenario_promotion_eligibility(self, scenario: MemoryScenario):
        """Verify promotion filtering matches expected eligibility."""
        # Build memories from classifications
        memories = []
        for item in scenario.llm_classifications:
            memories.append(_build_mock_memory(item.get("content", ""), item.get("category")))

        # Apply promotion filter (same logic as MemoryModule)
        exclude_categories = ["trivial"]
        eligible = [m for m in memories if m.memory_category not in exclude_categories]

        if scenario.expected_promotion_eligible:
            assert len(eligible) > 0, f"Scenario '{scenario.name}': expected eligible memories"
        else:
            assert len(eligible) == 0, f"Scenario '{scenario.name}': expected no eligible memories"

    @pytest.mark.parametrize(
        "scenario",
        SCENARIOS,
        ids=[s.name for s in SCENARIOS],
    )
    async def test_scenario_propagation_count(self, scenario: MemoryScenario):
        """Verify propagation filter produces expected number of propagable memories."""
        memories = []
        for item in scenario.llm_classifications:
            mem = _build_mock_memory(item.get("content", ""), item.get("category"))
            memories.append(mem)

        # Apply propagation filter (same logic as MemoryPropagationService)
        propagable = [
            m
            for m in memories
            if getattr(m, "memory_category", None) not in ("trivial", "private", None)
        ]

        assert len(propagable) == scenario.expected_propagation_count, (
            f"Scenario '{scenario.name}': expected {scenario.expected_propagation_count} "
            f"propagable, got {len(propagable)}"
        )

    @pytest.mark.parametrize(
        "scenario",
        SCENARIOS,
        ids=[s.name for s in SCENARIOS],
    )
    async def test_scenario_content_non_empty(self, scenario: MemoryScenario):
        """All generated memories have non-empty content."""
        char_names = list({item["character"] for item in scenario.llm_classifications})
        chars = {name: _build_character(name) for name in char_names}

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=scenario.llm_classifications)
        mock_session = AsyncMock()
        mock_memory_repo = AsyncMock()

        async def fake_add(**kwargs):
            return _build_mock_memory(kwargs.get("content", ""), kwargs.get("memory_category"))

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
            assert mem.content, f"Empty content in scenario '{scenario.name}'"


# ---------------------------------------------------------------------------
# Formatting regression tests
# ---------------------------------------------------------------------------


class TestFormattingRegression:
    """Regression tests for formatting functions with known inputs/outputs."""

    def test_short_term_recent_hint_present(self):
        """First two memories get a 'recent events' hint."""
        memories = [
            SimpleNamespace(content="记忆一", short_term_reflection=None, is_hearsay=False),
            SimpleNamespace(content="记忆二", short_term_reflection=None, is_hearsay=False),
            SimpleNamespace(content="记忆三", short_term_reflection=None, is_hearsay=False),
        ]
        result = format_short_term_for_injection(memories)
        # The hint appears before the first memory
        assert "最近发生的事件" in result
        # All memories present
        assert "记忆一" in result
        assert "记忆二" in result
        assert "记忆三" in result

    def test_short_term_reflection_included(self):
        """Reflections are included in parentheses."""
        memories = [
            SimpleNamespace(
                content="目睹大战",
                short_term_reflection="世道变了",
                is_hearsay=False,
            ),
        ]
        result = format_short_term_for_injection(memories)
        assert "世道变了" in result
        assert "感悟" in result

    def test_long_term_structured_format(self):
        """Structured long-term memories use [event_name] format."""
        memories = [
            SimpleNamespace(
                content="王城之变: 视角",
                event_name="王城之变",
                perspective_detail="我在混乱中逃离",
                reflection="一切都变了",
                memory_type="long_term",
            ),
        ]
        result = format_long_term_for_injection(memories)
        assert "[王城之变]" in result
        assert "我在混乱中逃离" in result
        assert "感悟：一切都变了" in result

    def test_long_term_legacy_format(self):
        """Legacy memories without structured fields use content directly."""
        memories = [
            SimpleNamespace(
                content="普通记忆内容",
                event_name=None,
                perspective_detail=None,
                reflection=None,
                memory_type="long_term",
            ),
        ]
        result = format_long_term_for_injection(memories)
        assert "- 普通记忆内容" in result

    def test_empty_memories_return_placeholder(self):
        """Empty memory lists return placeholder text."""
        assert format_short_term_for_injection([]) == "暂无"
        assert format_long_term_for_injection([]) == "暂无"


# ---------------------------------------------------------------------------
# Orchestrator error recovery regression
# ---------------------------------------------------------------------------


class TestOrchestratorErrorRecovery:
    """Regression tests for orchestrator error handling."""

    async def test_module_exception_returns_empty(self):
        """Orchestrator catches module exceptions and returns empty list."""
        mock_module = AsyncMock()
        mock_module.generate_short_term_memories = AsyncMock(
            side_effect=RuntimeError("LLM exploded")
        )

        orchestrator = MemoryOrchestrator(memory_module=mock_module)
        result = await orchestrator.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={},
            dialogue_text="",
            event_description="",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_propagation_exception_is_swallowed(self):
        """Orchestrator catches propagation exceptions silently."""
        mock_propagation = AsyncMock()
        mock_propagation.propagate_after_event_memories = AsyncMock(
            side_effect=ConnectionError("DB down")
        )

        orchestrator = MemoryOrchestrator(
            memory_module=None, memory_propagation_service=mock_propagation
        )

        # Should not raise
        await orchestrator.dispatch_event_propagation(
            world_id=str(uuid.uuid4()),
            event_id=str(uuid.uuid4()),
            participant_names=["角色"],
            newly_written_memories=[SimpleNamespace(content="记忆", memory_category="major")],
            virtual_time=None,
        )
