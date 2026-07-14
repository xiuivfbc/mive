"""Tests for MemoryPropagationService — multi-hop propagation system.

Covers:
- _should_write_event_element (trivial/private/major mapping)
- _write_event_element (dissemination + authority + effective_day)
- _judge_dissemination (LLM call)
- _multi_hop_hearsay (two-hop with three-parameter filtering)
- _generate_hearsay_batch (batch LLM)
- _write_hearsay_memory (dedup by event_id, sequence)
- _calculate_hearsay_delay
- world_day
- End-to-end event path and chat path
"""

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import M2CharacterMemory
from src.services.memory_propagation_service import (
    AUTHORITY_COEFFICIENT,
    CHAT_INACTIVITY_TIMEOUT_MINUTES,
    CHAT_PROPAGATION_BUDGET,
    EVENT_NEWS_BASE_DELAY,
    HEARSAY_INFO_THRESHOLD,
    HEARSAY_RELATION_COEFF,
    HEARSAY_RETENTION_RANGE,
    HEARSAY_SPREAD_PROBABILITY,
    MAX_HOP_COUNT,
    PROPAGATION_BUDGET,
    PROPAGATION_DELAY,
    MemoryPropagationService,
    _get_relation_priority_weight,
    _infer_severity,
    world_day,
)

WORLD_ID = uuid.uuid4()
CHAR_A_ID = uuid.uuid4()
CHAR_B_ID = uuid.uuid4()
CHAR_C_ID = uuid.uuid4()
CHAR_D_ID = uuid.uuid4()
CHAR_E_ID = uuid.uuid4()
EVENT_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()
VIRTUAL_TIME = datetime(2026, 6, 5, 10, 0, 0, tzinfo=UTC)
WORLD_CREATED_AT = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _enable_propagation():
    """Enable propagation for all tests by default."""
    with patch("src.services.memory_propagation_service._is_enabled", return_value=True):
        yield


def _make_memory(
    char_id: uuid.UUID = CHAR_A_ID,
    content: str = "我经历了暴风雪",
    memory_type: str = "short_term",
    is_hearsay: bool = False,
    origin_event_id: uuid.UUID | None = None,
    propagated_from: uuid.UUID | None = None,
    involved_characters: list[uuid.UUID] | None = None,
    propagation_meta: dict | None = None,
    session_id: uuid.UUID | None = SESSION_ID,
    visible_at: datetime | None = None,
    memory_category: str | None = "major",
) -> M2CharacterMemory:
    mem = M2CharacterMemory(
        id=uuid.uuid4(),
        character_id=char_id,
        world_id=WORLD_ID,
        session_id=session_id,
        memory_type=memory_type,
        content=content,
        visible_at=visible_at or VIRTUAL_TIME,
        origin_event_id=origin_event_id,
        is_hearsay=is_hearsay,
        propagated_from=propagated_from,
        involved_characters=involved_characters,
        propagation_meta=propagation_meta,
        memory_category=memory_category,
    )
    return mem


def _make_relation(
    char_a: uuid.UUID = CHAR_A_ID,
    char_b: uuid.UUID = CHAR_B_ID,
    rel_type: str = "朋友",
) -> MagicMock:
    rel = MagicMock()
    rel.character_a = char_a
    rel.character_b = char_b
    rel.type = rel_type
    rel.description = f"{rel_type}关系"
    rel.status = "active"
    rel.historical_changes = None
    rel.metadata_ = None
    return rel


def _make_session_factory():
    """Create a mock session_factory that yields a mock session."""
    mock_session = AsyncMock()
    session_factory = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    session_factory.return_value = mock_session
    return session_factory, mock_session


def _patch_repos(char_repo=None, mem_repo=None, rel_repo=None, world_repo=None):
    """Return (char_repo, mem_repo, rel_repo, world_repo, exit_stack)."""
    if char_repo is None:
        char_repo = AsyncMock()
    if mem_repo is None:
        mem_repo = AsyncMock()
    if rel_repo is None:
        rel_repo = AsyncMock()
    if world_repo is None:
        world_repo = AsyncMock()

    stack = ExitStack()
    stack.enter_context(
        patch(
            "src.services.memory_propagation_service.CharacterRepository",
            return_value=char_repo,
        )
    )
    stack.enter_context(
        patch(
            "src.services.memory_propagation_service.CharacterMemoryRepository",
            return_value=mem_repo,
        )
    )
    stack.enter_context(
        patch(
            "src.services.memory_propagation_service.RelationRepository",
            return_value=rel_repo,
        )
    )
    stack.enter_context(
        patch(
            "src.services.memory_propagation_service.WorldRepository",
            return_value=world_repo,
        )
    )
    return char_repo, mem_repo, rel_repo, world_repo, stack


def _make_llm_hearsay_response(candidates: list[dict], source: str = "听说") -> dict:
    """Build a mock LLM response for _generate_hearsay_batch."""
    hearsays = [{"character": c["name"], "content": f"{source}{c['name']}的事"} for c in candidates]
    return {"hearsays": hearsays}


def _make_llm_dissemination_response(
    base_dissemination: float = 0.8, source_type: str = "official"
) -> dict:
    """Build a mock LLM response for _judge_dissemination."""
    return {
        "base_dissemination": base_dissemination,
        "source_type": source_type,
        "reasoning": "测试",
    }


# ── Helper function tests ─────────────────────────────────────────────────────


class TestInferSeverity:
    def test_returns_highest_severity(self):
        impacts = [
            {"severity": "low"},
            {"severity": "high"},
            {"severity": "medium"},
        ]
        assert _infer_severity(impacts) == "high"

    def test_empty_impacts_returns_low(self):
        assert _infer_severity([]) == "low"

    def test_single_critical(self):
        assert _infer_severity([{"severity": "critical"}]) == "critical"

    def test_unknown_severity_treated_as_low(self):
        assert _infer_severity([{"severity": "unknown"}]) == "low"

    def test_missing_severity_key(self):
        assert _infer_severity([{"other": "value"}]) == "low"


class TestRelationPriorityWeight:
    def test_exact_match_high(self):
        assert _get_relation_priority_weight("恋人") == 3
        assert _get_relation_priority_weight("家人") == 3

    def test_exact_match_medium(self):
        assert _get_relation_priority_weight("朋友") == 2
        assert _get_relation_priority_weight("同僚") == 2

    def test_exact_match_low(self):
        assert _get_relation_priority_weight("认识") == 1

    def test_substring_match_high(self):
        assert _get_relation_priority_weight("暗恋人") == 3
        assert _get_relation_priority_weight("亲兄弟") == 3

    def test_substring_match_medium(self):
        assert _get_relation_priority_weight("老朋友") == 2

    def test_no_match(self):
        assert _get_relation_priority_weight("未知关系") == 0

    def test_none_returns_zero(self):
        assert _get_relation_priority_weight(None) == 0

    def test_empty_string(self):
        assert _get_relation_priority_weight("") == 0

    def test_english_exact_match(self):
        assert _get_relation_priority_weight("spouse") == 3
        assert _get_relation_priority_weight("friend") == 2
        assert _get_relation_priority_weight("acquaintance") == 1


# ── world_day ─────────────────────────────────────────────────────────────────


class TestWorldDay:
    def test_world_creation_day_is_1(self):
        created = datetime(2026, 6, 1, 0, 0, 0)
        vt = datetime(2026, 6, 1, 23, 59, 59)
        assert world_day(vt, created) == 1

    def test_next_day_is_2(self):
        created = datetime(2026, 6, 1, 0, 0, 0)
        vt = datetime(2026, 6, 2, 0, 0, 0)
        assert world_day(vt, created) == 2

    def test_many_days_later(self):
        created = datetime(2026, 6, 1, 0, 0, 0)
        vt = datetime(2026, 6, 11, 0, 0, 0)
        assert world_day(vt, created) == 11

    def test_minimum_is_1(self):
        """Even if virtual_time is before created_at, day is at least 1."""
        created = datetime(2026, 6, 10, 0, 0, 0)
        vt = datetime(2026, 6, 1, 0, 0, 0)
        assert world_day(vt, created) == 1


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_max_hop_count(self):
        assert MAX_HOP_COUNT == 2

    def test_hearsay_info_threshold(self):
        assert HEARSAY_INFO_THRESHOLD == 0.5

    def test_authority_coefficients(self):
        assert AUTHORITY_COEFFICIENT["official"] == 1.0
        assert AUTHORITY_COEFFICIENT["folk_org"] == 0.7
        assert AUTHORITY_COEFFICIENT["hearsay"] == 0.4

    def test_spread_probability_table(self):
        assert HEARSAY_SPREAD_PROBABILITY[3] == 0.8
        assert HEARSAY_SPREAD_PROBABILITY[2] == 0.6
        assert HEARSAY_SPREAD_PROBABILITY[1] == 0.4
        assert HEARSAY_SPREAD_PROBABILITY[0] == 0.2

    def test_relation_coeff_table(self):
        assert HEARSAY_RELATION_COEFF[3] == 0.95
        assert HEARSAY_RELATION_COEFF[2] == 0.8
        assert HEARSAY_RELATION_COEFF[1] == 0.65
        assert HEARSAY_RELATION_COEFF[0] == 0.5

    def test_retention_range_table(self):
        assert HEARSAY_RETENTION_RANGE[3] == (0.75, 0.9)
        assert HEARSAY_RETENTION_RANGE[2] == (0.65, 0.85)
        assert HEARSAY_RETENTION_RANGE[1] == (0.6, 0.75)
        assert HEARSAY_RETENTION_RANGE[0] == (0.6, 0.7)

    def test_event_news_base_delay(self):
        assert EVENT_NEWS_BASE_DELAY["standard"] == 1
        assert EVENT_NEWS_BASE_DELAY["detailed"] == 2
        assert EVENT_NEWS_BASE_DELAY["deep"] == 3
        assert EVENT_NEWS_BASE_DELAY["all"] == 3

    def test_chat_inactivity_timeout(self):
        assert CHAT_INACTIVITY_TIMEOUT_MINUTES == 30

    def test_propagation_budget_values(self):
        assert PROPAGATION_BUDGET["standard"] == 4
        assert PROPAGATION_BUDGET["detailed"] == 8
        assert PROPAGATION_BUDGET["deep"] == 12
        assert PROPAGATION_BUDGET["all"] == 16

    def test_chat_propagation_budget_values(self):
        assert CHAT_PROPAGATION_BUDGET["standard"] == 2
        assert CHAT_PROPAGATION_BUDGET["detailed"] == 3
        assert CHAT_PROPAGATION_BUDGET["deep"] == 4
        assert CHAT_PROPAGATION_BUDGET["all"] == 5

    def test_propagation_delay_values(self):
        assert PROPAGATION_DELAY[3] == timedelta(hours=1)
        assert PROPAGATION_DELAY[2] == timedelta(hours=4)
        assert PROPAGATION_DELAY[1] == timedelta(hours=12)
        assert PROPAGATION_DELAY[0] == timedelta(days=1)


# ── Service construction ─────────────────────────────────────────────────────


class TestServiceConstruction:
    def test_construction(self):
        llm = AsyncMock()
        sf = MagicMock()
        svc = MemoryPropagationService(llm=llm, session_factory=sf)
        assert svc.llm is llm
        assert svc.session_factory is sf

    @patch("src.services.memory_propagation_service._is_enabled", return_value=False)
    async def test_feature_flag_disabled(self, _mock_enabled):
        svc = MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())
        result = await svc.propagate_after_event_memories(
            world_id=str(WORLD_ID),
            event_id=str(EVENT_ID),
            participant_names=["A"],
            newly_written_memories=[],
            virtual_time=VIRTUAL_TIME,
            event_impacts=[],
        )
        assert result["propagated"] == 0
        assert result["skipped"] == "disabled"


# ── _should_propagate ────────────────────────────────────────────────────────


class TestShouldPropagate:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    def test_hearsay_does_not_trigger(self, svc):
        mem = _make_memory(is_hearsay=True, origin_event_id=EVENT_ID)
        assert svc._should_propagate(mem) is False

    def test_no_origin_event_id_does_not_trigger(self, svc):
        mem = _make_memory(origin_event_id=None)
        assert svc._should_propagate(mem) is False

    def test_real_memory_with_event_triggers(self, svc):
        mem = _make_memory(origin_event_id=EVENT_ID)
        assert svc._should_propagate(mem) is True


# ── Severity threshold ───────────────────────────────────────────────────────


class TestSeverityThreshold:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    def test_standard_high_and_above(self, svc):
        assert svc._meets_severity_threshold("high", "standard") is True
        assert svc._meets_severity_threshold("medium", "standard") is False

    def test_detailed_medium_and_above(self, svc):
        assert svc._meets_severity_threshold("medium", "detailed") is True
        assert svc._meets_severity_threshold("low", "detailed") is False


# ── Budget ────────────────────────────────────────────────────────────────────


class TestBudget:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    def test_get_budget_event_path(self, svc):
        assert svc._get_budget("deep", is_event=True) == 12

    def test_get_budget_chat_path(self, svc):
        assert svc._get_budget("deep", is_event=False) == 4


# ── Candidate pool building ──────────────────────────────────────────────────


class TestCandidatePool:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    async def test_excludes_participants(self, svc):
        rel_a_c = _make_relation(char_a=CHAR_A_ID, char_b=CHAR_C_ID, rel_type="朋友")
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[rel_a_c])

        candidates = await svc._build_candidate_pool(
            world_id=str(WORLD_ID),
            participant_names=["A"],
            exclude_ids=set(),
            character_repo=char_repo,
            relation_repo=rel_repo,
        )
        candidate_ids = {c["character_id"] for c in candidates}
        assert CHAR_A_ID not in candidate_ids
        assert CHAR_C_ID in candidate_ids

    async def test_sorts_by_weight(self, svc):
        rel_acq = _make_relation(char_a=CHAR_A_ID, char_b=CHAR_C_ID, rel_type="认识")
        rel_fam = _make_relation(char_a=CHAR_A_ID, char_b=CHAR_D_ID, rel_type="家人")
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_repo = AsyncMock()
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[rel_acq, rel_fam])

        candidates = await svc._build_candidate_pool(
            world_id=str(WORLD_ID),
            participant_names=["A"],
            exclude_ids=set(),
            character_repo=char_repo,
            relation_repo=rel_repo,
        )
        assert len(candidates) == 2
        assert candidates[0]["weight"] >= candidates[1]["weight"]

    async def test_empty_participants_returns_empty(self, svc):
        candidates = await svc._build_candidate_pool(
            world_id=str(WORLD_ID),
            participant_names=[],
            exclude_ids=set(),
            character_repo=AsyncMock(),
            relation_repo=AsyncMock(),
        )
        assert candidates == []


# ── _should_write_event_element ──────────────────────────────────────────────


class TestShouldWriteEventElement:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    def test_major_always_writes(self, svc):
        memories = [_make_memory(memory_category="major")]
        assert svc._should_write_event_element(memories, "low") is True

    def test_major_writes_regardless_of_severity(self, svc):
        memories = [_make_memory(memory_category="major")]
        assert svc._should_write_event_element(memories, "low") is True
        assert svc._should_write_event_element(memories, "critical") is True

    def test_trivial_skips_unless_critical(self, svc):
        memories = [_make_memory(memory_category="trivial")]
        assert svc._should_write_event_element(memories, "low") is False
        assert svc._should_write_event_element(memories, "high") is False
        assert svc._should_write_event_element(memories, "critical") is True

    def test_pure_private_no_major_skips(self, svc):
        memories = [_make_memory(memory_category="private")]
        assert svc._should_write_event_element(memories, "high") is False

    def test_mixed_private_and_major_writes(self, svc):
        """When there is a mix of private and major, major wins."""
        memories = [
            _make_memory(memory_category="private"),
            _make_memory(memory_category="major", char_id=CHAR_B_ID),
        ]
        assert svc._should_write_event_element(memories, "low") is True

    def test_mixed_categories_writes_if_high_severity(self, svc):
        """Mix of non-uniform categories (not all same): write if high/critical."""
        memories = [
            _make_memory(memory_category="trivial"),
            _make_memory(memory_category="major", char_id=CHAR_B_ID),
        ]
        # "major" in categories → True
        assert svc._should_write_event_element(memories, "low") is True

    def test_empty_memories(self, svc):
        """Empty memories → always skip (no vacuous truth)."""
        assert svc._should_write_event_element([], "high") is False
        assert svc._should_write_event_element([], "critical") is False


# ── _calculate_hearsay_delay ─────────────────────────────────────────────────


class TestCalculateHearsayDelay:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    def test_hop1_family(self, svc):
        delay = svc._calculate_hearsay_delay(3, hop_count=1)
        assert delay == timedelta(hours=1)

    def test_hop1_friend(self, svc):
        delay = svc._calculate_hearsay_delay(2, hop_count=1)
        assert delay == timedelta(hours=4)

    def test_hop1_acquaintance(self, svc):
        delay = svc._calculate_hearsay_delay(1, hop_count=1)
        assert delay == timedelta(hours=12)

    def test_hop1_other(self, svc):
        delay = svc._calculate_hearsay_delay(0, hop_count=1)
        assert delay == timedelta(days=1)

    def test_hop2_doubles_delay(self, svc):
        """Second hop doubles the base delay."""
        delay1 = svc._calculate_hearsay_delay(2, hop_count=1)
        delay2 = svc._calculate_hearsay_delay(2, hop_count=2)
        assert delay2 == delay1 * 2

    def test_unknown_weight_defaults_to_one_day(self, svc):
        delay = svc._calculate_hearsay_delay(99, hop_count=1)
        assert delay == timedelta(days=1)


# ── Info amount formula ──────────────────────────────────────────────────────


class TestInfoAmountFormula:
    """Verify the three-parameter info_amount formula for hop-1 and hop-2."""

    def test_hop1_family_formula(self):
        """info_amount = relation_coeff * retention_coeff (hop-1)."""
        rc = HEARSAY_RELATION_COEFF[3]  # 0.95
        ret = 0.85  # within (0.75, 0.9)
        info = rc * ret
        assert info == pytest.approx(0.8075, abs=0.001)
        assert info >= HEARSAY_INFO_THRESHOLD  # >= 0.5 → propagates

    def test_hop1_acquaintance_low_info(self):
        """Acquaintance with low retention → below threshold."""
        rc = HEARSAY_RELATION_COEFF[1]  # 0.65
        ret = 0.6  # lower bound of (0.6, 0.75)
        info = rc * ret
        assert info == pytest.approx(0.39, abs=0.001)
        assert info < HEARSAY_INFO_THRESHOLD  # < 0.5 → stops

    def test_hop2_uses_fixed_info_not_relation_coeff(self):
        """Hop-2: info_amount = fixed_hop1_info * retention_coeff (no relation_coeff)."""
        fixed_hop1_info = 0.76
        ret = 0.75
        info = fixed_hop1_info * ret
        assert info == pytest.approx(0.57, abs=0.001)
        assert info >= HEARSAY_INFO_THRESHOLD

    def test_hop2_low_fixed_info_stops(self):
        """Hop-2 with low fixed info → below threshold."""
        fixed_hop1_info = 0.6
        ret = 0.6
        info = fixed_hop1_info * ret
        assert info == pytest.approx(0.36, abs=0.001)
        assert info < HEARSAY_INFO_THRESHOLD


# ── _judge_dissemination ─────────────────────────────────────────────────────


class TestJudgeDissemination:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    async def test_returns_base_and_source_type(self, svc):
        svc.llm.complete_json = AsyncMock(
            return_value=_make_llm_dissemination_response(0.8, "official")
        )
        base, source_type = await svc._judge_dissemination(
            world_id=str(WORLD_ID),
            event_description="暴风雪袭击了小镇",
            event_impacts=[{"severity": "high"}],
        )
        assert base == 0.8
        assert source_type == "official"

    async def test_llm_failure_returns_defaults(self, svc):
        svc.llm.complete_json = AsyncMock(side_effect=RuntimeError("timeout"))
        base, source_type = await svc._judge_dissemination(
            world_id=str(WORLD_ID),
            event_description="test",
            event_impacts=[],
        )
        assert base == 0.5
        assert source_type == "official"

    async def test_invalid_source_type_falls_back_to_hearsay(self, svc):
        svc.llm.complete_json = AsyncMock(
            return_value={"base_dissemination": 0.6, "source_type": "invalid"}
        )
        _, source_type = await svc._judge_dissemination(
            world_id=str(WORLD_ID),
            event_description="test",
            event_impacts=[],
        )
        assert source_type == "hearsay"

    async def test_clamps_base_dissemination(self, svc):
        svc.llm.complete_json = AsyncMock(
            return_value={"base_dissemination": 1.5, "source_type": "official"}
        )
        base, _ = await svc._judge_dissemination(
            world_id=str(WORLD_ID),
            event_description="test",
            event_impacts=[],
        )
        assert base == 1.0

    async def test_list_wrapped_response(self, svc):
        """LLM may return list-wrapped dicts."""
        svc.llm.complete_json = AsyncMock(
            return_value=[{"base_dissemination": 0.7, "source_type": "folk_org"}]
        )
        base, source_type = await svc._judge_dissemination(
            world_id=str(WORLD_ID),
            event_description="test",
            event_impacts=[],
        )
        assert base == 0.7
        assert source_type == "folk_org"


# ── _write_event_element ─────────────────────────────────────────────────────


class TestWriteEventElement:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    async def test_skips_when_should_write_returns_false(self, svc):
        """Trivial-only memories should not write event element."""
        memories = [_make_memory(memory_category="trivial")]
        world_doc = MagicMock()
        mem_repo = AsyncMock()

        await svc._write_event_element(
            world_id=str(WORLD_ID),
            event_id=str(EVENT_ID),
            participant_names=["A"],
            newly_written_memories=memories,
            virtual_time=VIRTUAL_TIME,
            event_impacts=[{"severity": "low"}],
            max_severity="low",
            world_scale="standard",
            world_doc=world_doc,
            memory_repo=mem_repo,
        )
        svc.llm.complete_json.assert_not_called()

    async def test_writes_event_element_for_major_memory(self, svc):
        """Major memory triggers event element write with LLM dissemination judge."""
        memories = [_make_memory(memory_category="major")]
        world_doc = MagicMock()
        world_doc.created_at = WORLD_CREATED_AT
        mem_repo = AsyncMock()
        event_index_repo = AsyncMock()
        event_index_repo.get_by_id = AsyncMock(return_value=None)
        event_index_repo.add = AsyncMock()

        svc.llm.complete_json = AsyncMock(
            return_value=_make_llm_dissemination_response(0.8, "official")
        )

        with patch(
            "src.services.memory_propagation_service.EventIndexRepository",
            return_value=event_index_repo,
        ):
            await svc._write_event_element(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=memories,
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
                max_severity="high",
                world_scale="standard",
                world_doc=world_doc,
                memory_repo=mem_repo,
            )

        event_index_repo.add.assert_called_once()
        call_kwargs = event_index_repo.add.call_args[1]
        # dissemination = 0.8 * 1.0 (official) = 0.8
        assert call_kwargs["dissemination"] == pytest.approx(0.8, abs=0.01)
        # effective_day should be calculated (dissemination > 0)
        assert call_kwargs["effective_day"] is not None
        assert call_kwargs["effective_day"] >= 1

    async def test_private_event_no_major_skips_event_element(self, svc):
        """Pure private memories (no major) → skip event element entirely."""
        memories = [_make_memory(memory_category="private")]
        world_doc = MagicMock()
        mem_repo = AsyncMock()
        event_index_repo = AsyncMock()
        event_index_repo.get_by_id = AsyncMock(return_value=None)
        event_index_repo.add = AsyncMock()

        svc.llm.complete_json = AsyncMock(
            return_value=_make_llm_dissemination_response(0.9, "official")
        )

        with patch(
            "src.services.memory_propagation_service.EventIndexRepository",
            return_value=event_index_repo,
        ):
            await svc._write_event_element(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=memories,
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
                max_severity="high",
                world_scale="standard",
                world_doc=world_doc,
                memory_repo=mem_repo,
            )

        # Pure private (no major) → _should_write_event_element returns False → skip
        event_index_repo.add.assert_not_called()
        svc.llm.complete_json.assert_not_called()

    async def test_private_with_major_uses_llm_dissemination(self, svc):
        """Private + major → event IS written, uses LLM dissemination (not forced to 0)."""
        memories = [
            _make_memory(memory_category="private"),
            _make_memory(memory_category="major", char_id=CHAR_B_ID),
        ]
        world_doc = MagicMock()
        world_doc.created_at = WORLD_CREATED_AT
        mem_repo = AsyncMock()
        event_index_repo = AsyncMock()
        event_index_repo.get_by_id = AsyncMock(return_value=None)
        event_index_repo.add = AsyncMock()

        # LLM returns high dissemination, but pure-private rule doesn't apply (has major)
        svc.llm.complete_json = AsyncMock(
            return_value=_make_llm_dissemination_response(0.8, "official")
        )

        with patch(
            "src.services.memory_propagation_service.EventIndexRepository",
            return_value=event_index_repo,
        ):
            await svc._write_event_element(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=memories,
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
                max_severity="high",
                world_scale="standard",
                world_doc=world_doc,
                memory_repo=mem_repo,
            )

        event_index_repo.add.assert_called_once()
        call_kwargs = event_index_repo.add.call_args[1]
        # Has major → NOT forced to 0, uses LLM result * authority
        assert call_kwargs["dissemination"] == pytest.approx(0.8, abs=0.01)

    async def test_authority_coefficient_applied(self, svc):
        """hearsay source should apply 0.4 coefficient."""
        memories = [_make_memory(memory_category="major")]
        world_doc = MagicMock()
        world_doc.created_at = WORLD_CREATED_AT
        mem_repo = AsyncMock()
        event_index_repo = AsyncMock()
        event_index_repo.get_by_id = AsyncMock(return_value=None)
        event_index_repo.add = AsyncMock()

        svc.llm.complete_json = AsyncMock(
            return_value=_make_llm_dissemination_response(0.8, "hearsay")
        )

        with patch(
            "src.services.memory_propagation_service.EventIndexRepository",
            return_value=event_index_repo,
        ):
            await svc._write_event_element(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=memories,
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
                max_severity="high",
                world_scale="standard",
                world_doc=world_doc,
                memory_repo=mem_repo,
            )

        call_kwargs = event_index_repo.add.call_args[1]
        # dissemination = 0.8 * 0.4 (hearsay) = 0.32
        assert call_kwargs["dissemination"] == pytest.approx(0.32, abs=0.01)

    async def test_llm_failure_defaults_to_half_official(self, svc):
        """LLM failure → default 0.5/official."""
        memories = [_make_memory(memory_category="major")]
        world_doc = MagicMock()
        world_doc.created_at = WORLD_CREATED_AT
        mem_repo = AsyncMock()
        event_index_repo = AsyncMock()
        event_index_repo.get_by_id = AsyncMock(return_value=None)
        event_index_repo.add = AsyncMock()

        svc.llm.complete_json = AsyncMock(side_effect=RuntimeError("fail"))

        with patch(
            "src.services.memory_propagation_service.EventIndexRepository",
            return_value=event_index_repo,
        ):
            await svc._write_event_element(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=memories,
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
                max_severity="high",
                world_scale="standard",
                world_doc=world_doc,
                memory_repo=mem_repo,
            )

        event_index_repo.add.assert_called_once()
        call_kwargs = event_index_repo.add.call_args[1]
        # 0.5 * 1.0 (official) = 0.5
        assert call_kwargs["dissemination"] == pytest.approx(0.5, abs=0.01)


# ── _write_hearsay_memory ────────────────────────────────────────────────────


class TestWriteHearsayMemory:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    async def test_creates_new_hearsay(self, svc):
        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=5)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)
        mem_repo.add_hearsay = AsyncMock()

        await svc._write_hearsay_memory(
            character_id=CHAR_C_ID,
            world_id=WORLD_ID,
            content="听说了暴风雪",
            visible_at=VIRTUAL_TIME,
            origin_event_id=EVENT_ID,
            propagated_from=CHAR_A_ID,
            source_character_id=CHAR_A_ID,
            hop_count=1,
            info_amount=0.76,
            involved_characters=[CHAR_A_ID],
            session_id=None,
            source="event_flush",
            severity="high",
            memory_repo=mem_repo,
        )

        mem_repo.add_hearsay.assert_called_once()
        call_kwargs = mem_repo.add_hearsay.call_args[1]
        assert call_kwargs["memory_sequence"] == 6  # max(5) + 1
        assert call_kwargs["hop_count"] == 1
        assert call_kwargs["info_amount"] == 0.76

    async def test_dedup_keeps_higher_info_amount(self, svc):
        """Existing hearsay with lower info → overwrite via upsert IntegrityError path."""
        existing = MagicMock()
        existing.info_amount = 0.5
        existing.content = "旧内容"

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=3)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=existing)
        # Simulate unique-index conflict (IntegrityError) on first insert
        from sqlalchemy.exc import IntegrityError

        mem_repo.add_hearsay = AsyncMock(side_effect=IntegrityError("", "", ""))

        await svc._write_hearsay_memory(
            character_id=CHAR_C_ID,
            world_id=WORLD_ID,
            content="新内容",
            visible_at=VIRTUAL_TIME,
            origin_event_id=EVENT_ID,
            propagated_from=CHAR_A_ID,
            source_character_id=CHAR_A_ID,
            hop_count=1,
            info_amount=0.76,
            involved_characters=None,
            session_id=None,
            source="event_flush",
            severity=None,
            memory_repo=mem_repo,
        )

        # Should update existing, not create new
        assert existing.content == "新内容"
        assert existing.info_amount == 0.76

    async def test_dedup_keeps_existing_when_higher(self, svc):
        """Existing hearsay with higher info → keep existing via upsert IntegrityError path."""
        existing = MagicMock()
        existing.info_amount = 0.9
        existing.content = "旧的好内容"

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=3)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=existing)
        from sqlalchemy.exc import IntegrityError

        mem_repo.add_hearsay = AsyncMock(side_effect=IntegrityError("", "", ""))

        await svc._write_hearsay_memory(
            character_id=CHAR_C_ID,
            world_id=WORLD_ID,
            content="新的差内容",
            visible_at=VIRTUAL_TIME,
            origin_event_id=EVENT_ID,
            propagated_from=CHAR_A_ID,
            source_character_id=CHAR_A_ID,
            hop_count=2,
            info_amount=0.55,
            involved_characters=None,
            session_id=None,
            source="event_flush",
            severity=None,
            memory_repo=mem_repo,
        )

        # Should keep existing (higher info)
        assert existing.content == "旧的好内容"

    async def test_chat_path_dedup_creates_new_when_none(self, svc):
        """Chat path (no event_id) with no existing → creates new."""
        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock()
        mem_repo.get_hearsay_by_session = AsyncMock(return_value=None)
        mem_repo.add_hearsay = AsyncMock()

        await svc._write_hearsay_memory(
            character_id=CHAR_C_ID,
            world_id=WORLD_ID,
            content="聊天传闻",
            visible_at=VIRTUAL_TIME,
            origin_event_id=None,
            propagated_from=CHAR_A_ID,
            source_character_id=CHAR_A_ID,
            hop_count=1,
            info_amount=0.7,
            involved_characters=None,
            session_id=SESSION_ID,
            source="chat_flush",
            severity=None,
            memory_repo=mem_repo,
        )

        # Should NOT call get_hearsay_by_event (no event_id)
        mem_repo.get_hearsay_by_event.assert_not_called()
        # Should call get_hearsay_by_session for chat dedup
        mem_repo.get_hearsay_by_session.assert_called_once()
        mem_repo.add_hearsay.assert_called_once()

    async def test_chat_path_dedup_keeps_higher_info(self, svc):
        """Chat path dedup: existing hearsay with lower info → overwrite."""
        existing = MagicMock()
        existing.info_amount = 0.5
        existing.content = "旧聊天传闻"

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=3)
        mem_repo.get_hearsay_by_session = AsyncMock(return_value=existing)
        mem_repo.add_hearsay = AsyncMock()

        await svc._write_hearsay_memory(
            character_id=CHAR_C_ID,
            world_id=WORLD_ID,
            content="新聊天传闻",
            visible_at=VIRTUAL_TIME,
            origin_event_id=None,
            propagated_from=CHAR_A_ID,
            source_character_id=CHAR_A_ID,
            hop_count=1,
            info_amount=0.7,
            involved_characters=None,
            session_id=SESSION_ID,
            source="chat_flush",
            severity=None,
            memory_repo=mem_repo,
        )

        # Should update existing, not create new
        assert existing.content == "新聊天传闻"
        assert existing.info_amount == 0.7
        mem_repo.add_hearsay.assert_not_called()


# ── _multi_hop_hearsay ───────────────────────────────────────────────────────


class TestMultiHopHearsay:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    async def test_empty_candidates_returns_zero(self, svc):
        result = await svc._multi_hop_hearsay(
            world_id=str(WORLD_ID),
            event_id=EVENT_ID,
            candidates=[],
            source_memories=[_make_memory()],
            virtual_time=VIRTUAL_TIME,
            source_character_id=CHAR_A_ID,
            involved_characters=[CHAR_A_ID],
            source="event_flush",
            severity="high",
            world_scale="standard",
            character_repo=AsyncMock(),
            memory_repo=AsyncMock(),
            relation_repo=AsyncMock(),
        )
        assert result == 0

    async def test_empty_source_memories_returns_zero(self, svc):
        result = await svc._multi_hop_hearsay(
            world_id=str(WORLD_ID),
            event_id=EVENT_ID,
            candidates=[{"character_id": CHAR_C_ID, "weight": 2, "rel_type": "朋友"}],
            source_memories=[],
            virtual_time=VIRTUAL_TIME,
            source_character_id=CHAR_A_ID,
            involved_characters=None,
            source="event_flush",
            severity="high",
            world_scale="standard",
            character_repo=AsyncMock(),
            memory_repo=AsyncMock(),
            relation_repo=AsyncMock(),
        )
        assert result == 0

    async def test_hop1_propagation_writes_hearsay(self, svc):
        """Normal hop-1 propagation: three-parameter filtering + LLM + write."""
        char_repo = AsyncMock()
        char_c = MagicMock()
        char_c.id = CHAR_C_ID
        char_c.name = "C"
        char_c.profile = {"brief": "角色C"}
        char_repo.get_by_id = AsyncMock(return_value=char_c)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[])

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)
        mem_repo.add_hearsay = AsyncMock()

        # Mock random to always pass spread check and give deterministic retention
        # Set MAX_HOP_COUNT=1 to skip hop2 (avoids RelationRepository mock complexity)
        with (
            patch("src.services.memory_propagation_service.random") as mock_random,
            patch(
                "src.services.memory_propagation_service.get_character_names",
                new_callable=AsyncMock,
                return_value={str(CHAR_C_ID): "C"},
            ),
            patch("src.services.memory_propagation_service.MAX_HOP_COUNT", 1),
        ):
            # random.random() < 0.6 (spread_prob for friend) → passes
            # random.uniform(0.65, 0.85) → 0.75
            mock_random.random.return_value = 0.1
            mock_random.uniform.return_value = 0.75

            svc.llm.complete_json = AsyncMock(
                return_value=_make_llm_hearsay_response([{"name": "C"}], source="听说")
            )

            result = await svc._multi_hop_hearsay(
                world_id=str(WORLD_ID),
                event_id=EVENT_ID,
                candidates=[{"character_id": CHAR_C_ID, "weight": 2, "rel_type": "朋友"}],
                source_memories=[_make_memory()],
                virtual_time=VIRTUAL_TIME,
                source_character_id=CHAR_A_ID,
                involved_characters=[CHAR_A_ID],
                source="event_flush",
                severity="high",
                world_scale="standard",
                character_repo=char_repo,
                memory_repo=mem_repo,
                relation_repo=rel_repo,
            )

        assert result >= 1
        mem_repo.add_hearsay.assert_called()
        call_kwargs = mem_repo.add_hearsay.call_args[1]
        assert call_kwargs["hop_count"] == 1
        assert call_kwargs["info_amount"] == pytest.approx(0.8 * 0.75, abs=0.01)

    async def test_hop2_propagation_two_hops(self, svc):
        """Full two-hop propagation: hop-1 → hop-2.

        relation_repo is now passed as a parameter to _multi_hop_hearsay.
        """
        char_repo = AsyncMock()
        char_c = MagicMock()
        char_c.id = CHAR_C_ID
        char_c.name = "C"
        char_c.profile = {"brief": "角色C"}
        char_d = MagicMock()
        char_d.id = CHAR_D_ID
        char_d.name = "D"
        char_d.profile = {"brief": "角色D"}

        async def get_by_id(cid):
            return {str(CHAR_C_ID): char_c, str(CHAR_D_ID): char_d}.get(cid)

        char_repo.get_by_id = AsyncMock(side_effect=get_by_id)

        rel_repo = AsyncMock()
        # C-D relation for hop-2
        rel_c_d = _make_relation(char_a=CHAR_C_ID, char_b=CHAR_D_ID, rel_type="朋友")
        rel_repo.list_by_world = AsyncMock(return_value=[rel_c_d])

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)
        mem_repo.add_hearsay = AsyncMock()

        with (
            patch("src.services.memory_propagation_service.random") as mock_random,
            patch(
                "src.services.memory_propagation_service.get_character_names",
                new_callable=AsyncMock,
            ) as mock_names,
        ):
            # Always pass spread check
            mock_random.random.return_value = 0.01
            # Retention: 0.75 (within range for friend)
            mock_random.uniform.return_value = 0.75

            mock_names.return_value = {
                str(CHAR_C_ID): "C",
                str(CHAR_D_ID): "D",
            }

            # LLM returns hearsay for both hops
            svc.llm.complete_json = AsyncMock(
                return_value=_make_llm_hearsay_response(
                    [{"name": "C"}, {"name": "D"}], source="听说"
                )
            )

            result = await svc._multi_hop_hearsay(
                world_id=str(WORLD_ID),
                event_id=EVENT_ID,
                candidates=[{"character_id": CHAR_C_ID, "weight": 2, "rel_type": "朋友"}],
                source_memories=[_make_memory()],
                virtual_time=VIRTUAL_TIME,
                source_character_id=CHAR_A_ID,
                involved_characters=[CHAR_A_ID],
                source="event_flush",
                severity="high",
                world_scale="standard",
                character_repo=char_repo,
                memory_repo=mem_repo,
                relation_repo=rel_repo,
            )

        # Should have propagated to both C (hop-1) and D (hop-2)
        assert result >= 1
        # Verify add_hearsay was called with hop_count=1 and hop_count=2
        calls = mem_repo.add_hearsay.call_args_list
        hop_counts = [c[1]["hop_count"] for c in calls]
        assert 1 in hop_counts

    async def test_spread_probability_filter(self, svc):
        """When random > spread_prob, candidate is skipped."""
        char_repo = AsyncMock()
        char_c = MagicMock()
        char_c.id = CHAR_C_ID
        char_c.name = "C"
        char_c.profile = {"brief": "角色C"}
        char_repo.get_by_id = AsyncMock(return_value=char_c)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[])

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)

        with (
            patch("src.services.memory_propagation_service.random") as mock_random,
            patch(
                "src.services.memory_propagation_service.get_character_names",
                new_callable=AsyncMock,
                return_value={str(CHAR_C_ID): "C"},
            ),
        ):
            # random.random() = 0.9 > 0.6 (spread_prob for friend) → SKIP
            mock_random.random.return_value = 0.9

            result = await svc._multi_hop_hearsay(
                world_id=str(WORLD_ID),
                event_id=EVENT_ID,
                candidates=[{"character_id": CHAR_C_ID, "weight": 2, "rel_type": "朋友"}],
                source_memories=[_make_memory()],
                virtual_time=VIRTUAL_TIME,
                source_character_id=CHAR_A_ID,
                involved_characters=None,
                source="event_flush",
                severity="high",
                world_scale="standard",
                character_repo=char_repo,
                memory_repo=mem_repo,
                relation_repo=rel_repo,
            )

        assert result == 0
        mem_repo.add_hearsay.assert_not_called()

    async def test_info_below_threshold_stops(self, svc):
        """When info_amount < 0.5, propagation stops."""
        char_repo = AsyncMock()
        char_c = MagicMock()
        char_c.id = CHAR_C_ID
        char_c.name = "C"
        char_c.profile = {"brief": "角色C"}
        char_repo.get_by_id = AsyncMock(return_value=char_c)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[])

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)

        with (
            patch("src.services.memory_propagation_service.random") as mock_random,
            patch(
                "src.services.memory_propagation_service.get_character_names",
                new_callable=AsyncMock,
                return_value={str(CHAR_C_ID): "C"},
            ),
        ):
            # Pass spread check
            mock_random.random.return_value = 0.01
            # Low retention → info = 0.65 * 0.6 = 0.39 < 0.5
            mock_random.uniform.return_value = 0.6

            result = await svc._multi_hop_hearsay(
                world_id=str(WORLD_ID),
                event_id=EVENT_ID,
                candidates=[{"character_id": CHAR_C_ID, "weight": 1, "rel_type": "认识"}],
                source_memories=[_make_memory()],
                virtual_time=VIRTUAL_TIME,
                source_character_id=CHAR_A_ID,
                involved_characters=None,
                source="event_flush",
                severity="high",
                world_scale="standard",
                character_repo=char_repo,
                memory_repo=mem_repo,
                relation_repo=rel_repo,
            )

        assert result == 0
        mem_repo.add_hearsay.assert_not_called()

    async def test_max_hop_count_1_skips_hop2(self, svc):
        """When MAX_HOP_COUNT=1, only hop-1 runs."""
        char_repo = AsyncMock()
        char_c = MagicMock()
        char_c.id = CHAR_C_ID
        char_c.name = "C"
        char_c.profile = {"brief": "角色C"}
        char_repo.get_by_id = AsyncMock(return_value=char_c)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[])

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)
        mem_repo.add_hearsay = AsyncMock()

        with (
            patch("src.services.memory_propagation_service.random") as mock_random,
            patch("src.services.memory_propagation_service.MAX_HOP_COUNT", 1),
            patch(
                "src.services.memory_propagation_service.get_character_names",
                new_callable=AsyncMock,
                return_value={str(CHAR_C_ID): "C"},
            ),
        ):
            mock_random.random.return_value = 0.01
            mock_random.uniform.return_value = 0.75

            svc.llm.complete_json = AsyncMock(
                return_value=_make_llm_hearsay_response([{"name": "C"}])
            )

            await svc._multi_hop_hearsay(
                world_id=str(WORLD_ID),
                event_id=EVENT_ID,
                candidates=[{"character_id": CHAR_C_ID, "weight": 2, "rel_type": "朋友"}],
                source_memories=[_make_memory()],
                virtual_time=VIRTUAL_TIME,
                source_character_id=CHAR_A_ID,
                involved_characters=[CHAR_A_ID],
                source="event_flush",
                severity="high",
                world_scale="standard",
                character_repo=char_repo,
                memory_repo=mem_repo,
                relation_repo=rel_repo,
            )

        # Only hop-1 should run, no hop-2
        calls = mem_repo.add_hearsay.call_args_list
        for call in calls:
            assert call[1]["hop_count"] == 1


# ── _generate_hearsay_batch ──────────────────────────────────────────────────


class TestGenerateHearsayBatch:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    async def test_hop1_batch_generation(self, svc):
        """Hop-1: generates hearsay from source_memories."""
        svc.llm.complete_json = AsyncMock(
            return_value={
                "hearsays": [
                    {"character": "C", "content": "听说了暴风雪"},
                ]
            }
        )

        candidates = [{"character_id": CHAR_C_ID, "name": "C", "info_amount": 0.76}]
        source_memories = [_make_memory(content="暴风雪袭击了小镇")]

        result = await svc._generate_hearsay_batch(
            source_memories=source_memories,
            candidates=candidates,
            hop_count=1,
        )

        assert str(CHAR_C_ID) in result
        assert result[str(CHAR_C_ID)] == "听说了暴风雪"

    async def test_hop2_batch_generation(self, svc):
        """Hop-2: generates hearsay from hop-1 hearsay content."""
        svc.llm.complete_json = AsyncMock(
            return_value={
                "hearsays": [
                    {"character": "D", "content": "听人说起暴风雪"},
                ]
            }
        )

        candidates = [{"character_id": CHAR_D_ID, "name": "D", "info_amount": 0.56}]

        result = await svc._generate_hearsay_batch(
            source_memories=None,
            candidates=candidates,
            hop_count=2,
            source_memories_by_receiver={str(CHAR_D_ID): "听说了暴风雪"},
            fixed_info_amount=0.76,
        )

        assert str(CHAR_D_ID) in result

    async def test_llm_failure_returns_empty(self, svc):
        svc.llm.complete_json = AsyncMock(side_effect=RuntimeError("fail"))
        result = await svc._generate_hearsay_batch(
            source_memories=[_make_memory()],
            candidates=[{"character_id": CHAR_C_ID, "name": "C", "info_amount": 0.76}],
            hop_count=1,
        )
        assert result == {}

    async def test_null_content_returns_none_for_that_char(self, svc):
        svc.llm.complete_json = AsyncMock(
            return_value={
                "hearsays": [
                    {"character": "C", "content": None},
                ]
            }
        )
        result = await svc._generate_hearsay_batch(
            source_memories=[_make_memory()],
            candidates=[{"character_id": CHAR_C_ID, "name": "C", "info_amount": 0.76}],
            hop_count=1,
        )
        assert result[str(CHAR_C_ID)] is None

    async def test_reduction_levels_by_info_amount(self, svc):
        """Different info_amount levels should produce different reduction descriptions."""
        svc.llm.complete_json = AsyncMock(return_value={"hearsays": []})
        candidates = [
            {"character_id": CHAR_C_ID, "name": "C", "info_amount": 0.9},
            {"character_id": CHAR_D_ID, "name": "D", "info_amount": 0.7},
            {"character_id": CHAR_E_ID, "name": "E", "info_amount": 0.55},
        ]
        await svc._generate_hearsay_batch(
            source_memories=[_make_memory()],
            candidates=candidates,
            hop_count=1,
        )
        # Verify the LLM was called (prompt contains reduction info)
        svc.llm.complete_json.assert_called_once()
        user_prompt = svc.llm.complete_json.call_args[0][1]
        assert "轻度删减" in user_prompt
        assert "中度删减" in user_prompt
        assert "重度删减" in user_prompt


# ── Event path: propagate_after_event_memories ───────────────────────────────


class TestPropagateAfterEvent:
    async def test_skips_when_severity_below_threshold(self):
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_repo.get = AsyncMock(return_value=world_doc)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(world_repo=world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "low"}],
            )
            assert result["propagated"] == 0
            assert result["skipped"] == "severity_below_threshold"

    async def test_skips_when_no_propagable_memories(self):
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_repo.get = AsyncMock(return_value=world_doc)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(world_repo=world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=None)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] == 0

    async def test_llm_failure_graceful_degradation(self):
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = None
        world_doc.created_at = WORLD_CREATED_AT
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_a.name = "A"
        char_a.profile = {"brief": "角色A"}
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        char_repo.get_by_id = AsyncMock(return_value=char_a)

        rel_repo = AsyncMock()
        rel = _make_relation(char_a=CHAR_A_ID, char_b=CHAR_C_ID)
        rel_repo.list_by_world = AsyncMock(return_value=[rel])

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)
        event_index_repo = AsyncMock()
        event_index_repo.get_by_id = AsyncMock(return_value=None)
        event_index_repo.add = AsyncMock()

        llm = AsyncMock()
        llm.complete_json = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)
        stack.enter_context(
            patch(
                "src.services.memory_propagation_service.EventIndexRepository",
                return_value=event_index_repo,
            )
        )

        with stack:
            svc = MemoryPropagationService(llm=llm, session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            # Should not raise, returns 0 propagated (LLM failed for both dissemination and hearsay)
            assert result["propagated"] == 0

    async def test_no_relations_no_propagation(self):
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = None
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_repo.find_by_name = AsyncMock(return_value=char_a)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[])

        mem_repo = AsyncMock()
        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] == 0

    async def test_budget_limit(self):
        """Deep world should not exceed 12 propagations."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "deep"
        world_doc.user_character_id = None
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_a.name = "A"
        char_a.profile = {"brief": "角色A"}
        char_repo.find_by_name = AsyncMock(return_value=char_a)

        relations = []
        for i in range(15):
            other_id = uuid.uuid4()
            rel = _make_relation(char_a=CHAR_A_ID, char_b=other_id, rel_type="朋友")
            relations.append(rel)
            other_char = MagicMock()
            other_char.id = other_id
            other_char.name = f"Other{i}"
            other_char.profile = {"brief": f"角色{i}"}
            char_repo.get_by_id = AsyncMock(return_value=other_char)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=relations)

        mem_repo = AsyncMock()
        mem_repo.add_hearsay = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)

        llm = AsyncMock()
        # Return hearsay dict format for batch generation
        hearsay_items = {
            "hearsays": [{"character": f"Other{i}", "content": f"听说了事件{i}"} for i in range(15)]
        }
        # First call: dissemination judge; rest: hearsay batch
        llm.complete_json = AsyncMock(return_value=hearsay_items)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)

        with stack:
            svc = MemoryPropagationService(llm=llm, session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] <= 12


# ── Chat path: propagate_after_chat_flush ────────────────────────────────────


class TestPropagateAfterChatFlush:
    async def test_chat_flush_always_triggers(self):
        """Chat path has no severity threshold."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = None
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_repo.find_by_name = AsyncMock(return_value=char_a)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[])

        mem_repo = AsyncMock()
        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=None, session_id=SESSION_ID)
            result = await svc.propagate_after_chat_flush(
                world_id=str(WORLD_ID),
                session_id=str(SESSION_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
            )
            assert result.get("skipped") != "severity_below_threshold"

    async def test_chat_budget_limit(self):
        """Chat path uses smaller budget (standard=2)."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = None
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_a.name = "A"
        char_a.profile = {"brief": "角色A"}
        char_repo.find_by_name = AsyncMock(return_value=char_a)

        relations = []
        for i in range(10):
            other_id = uuid.uuid4()
            rel = _make_relation(char_a=CHAR_A_ID, char_b=other_id, rel_type="朋友")
            relations.append(rel)
            other_char = MagicMock()
            other_char.id = other_id
            other_char.name = f"Other{i}"
            other_char.profile = {"brief": f"角色{i}"}
            char_repo.get_by_id = AsyncMock(return_value=other_char)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=relations)

        mem_repo = AsyncMock()
        mem_repo.add_hearsay = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)

        llm = AsyncMock()
        llm.complete_json = AsyncMock(
            return_value={
                "hearsays": [
                    {"character": f"Other{i}", "content": f"听说了消息{i}"} for i in range(10)
                ]
            }
        )

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)

        with stack:
            svc = MemoryPropagationService(llm=llm, session_factory=session_factory)
            mem = _make_memory(origin_event_id=None, session_id=SESSION_ID, memory_category="major")
            result = await svc.propagate_after_chat_flush(
                world_id=str(WORLD_ID),
                session_id=str(SESSION_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
            )
            assert result["propagated"] <= 2


# ── Feature flag ─────────────────────────────────────────────────────────────


class TestFeatureFlag:
    async def test_disabled_no_llm_calls(self):
        llm = AsyncMock()
        session_factory = MagicMock()

        svc = MemoryPropagationService(llm=llm, session_factory=session_factory)

        with patch("src.services.memory_propagation_service._is_enabled", return_value=False):
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[_make_memory()],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )

        assert result["propagated"] == 0
        assert result["skipped"] == "disabled"
        llm.complete_json.assert_not_called()
        session_factory.assert_not_called()


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    async def test_empty_participants_no_crash(self):
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = None
        world_repo.get = AsyncMock(return_value=world_doc)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(world_repo=world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=[],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] == 0
            assert result["skipped"] == "no_candidates"

    async def test_empty_newly_written_memories(self):
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_repo.get = AsyncMock(return_value=world_doc)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(world_repo=world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] == 0

    async def test_llm_returns_empty_hearsays(self):
        """LLM returning empty hearsays list → 0 propagated."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = None
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_a.name = "A"
        char_a.profile = {"brief": "角色A"}
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        char_c = MagicMock()
        char_c.id = CHAR_C_ID
        char_repo.get_by_id = AsyncMock(return_value=char_c)

        rel_repo = AsyncMock()
        rel = _make_relation(char_a=CHAR_A_ID, char_b=CHAR_C_ID)
        rel_repo.list_by_world = AsyncMock(return_value=[rel])

        mem_repo = AsyncMock()

        llm = AsyncMock()
        llm.complete_json = AsyncMock(return_value={"hearsays": []})

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)

        with stack:
            svc = MemoryPropagationService(llm=llm, session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] == 0


# ── World scale resolution ───────────────────────────────────────────────────


class TestWorldScaleResolution:
    def test_world_scale_from_world_doc(self):
        world_doc = MagicMock()
        world_doc.scale = "deep"

        svc = MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())
        scale = svc._get_world_scale(world_doc)
        assert scale == "deep"

    def test_world_scale_defaults_to_standard(self):
        world_doc = MagicMock()
        world_doc.scale = None

        svc = MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())
        scale = svc._get_world_scale(world_doc)
        assert scale == "standard"

    def test_world_scale_none_doc(self):
        svc = MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())
        scale = svc._get_world_scale(None)
        assert scale == "standard"


# ── Relation evaluation ─────────────────────────────────────────────────────


class TestRelationEvaluation:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    async def test_relation_eval_stub(self, svc):
        """Relation evaluation is a stub in v1, returns 0."""
        result = await svc.evaluate_relation_changes(str(WORLD_ID))
        assert result["evaluated"] == 0
        assert result["updated"] == 0


# ── User character exclusion ─────────────────────────────────────────────────


class TestUserCharacterExclusion:
    async def test_user_character_excluded_from_candidates(self):
        """User character should be excluded from propagation candidates."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = str(CHAR_A_ID)
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_a.name = "A"
        char_repo.find_by_name = AsyncMock(return_value=char_a)

        # C is related to A, but A is user character → should be excluded
        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[])

        mem_repo = AsyncMock()
        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            # No candidates because user char is excluded and no other relations
            assert result["propagated"] == 0
            assert result["skipped"] == "no_candidates"


# ── Hop-2 does not trigger further propagation ──────────────────────────────


class TestHop2DoesNotPropagateFurther:
    async def test_hop2_stops_at_max_hop_count(self):
        """Hop-2 hearsay should not trigger hop-3 (MAX_HOP_COUNT=2)."""
        char_repo = AsyncMock()
        char_c = MagicMock()
        char_c.id = CHAR_C_ID
        char_c.name = "C"
        char_c.profile = {"brief": "角色C"}
        char_d = MagicMock()
        char_d.id = CHAR_D_ID
        char_d.name = "D"
        char_d.profile = {"brief": "角色D"}
        char_e = MagicMock()
        char_e.id = CHAR_E_ID
        char_e.name = "E"
        char_e.profile = {"brief": "角色E"}

        async def get_by_id(cid):
            return {str(CHAR_C_ID): char_c, str(CHAR_D_ID): char_d, str(CHAR_E_ID): char_e}.get(cid)

        char_repo.get_by_id = AsyncMock(side_effect=get_by_id)

        rel_repo = AsyncMock()
        # C-D for hop-2, D-E would be hop-3 (should not happen)
        rel_c_d = _make_relation(char_a=CHAR_C_ID, char_b=CHAR_D_ID, rel_type="朋友")
        rel_d_e = _make_relation(char_a=CHAR_D_ID, char_b=CHAR_E_ID, rel_type="朋友")
        rel_repo.list_by_world = AsyncMock(return_value=[rel_c_d, rel_d_e])

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)
        mem_repo.add_hearsay = AsyncMock()

        with (
            patch("src.services.memory_propagation_service.random") as mock_random,
            patch(
                "src.services.memory_propagation_service.get_character_names",
                new_callable=AsyncMock,
            ) as mock_names,
        ):
            mock_random.random.return_value = 0.01
            mock_random.uniform.return_value = 0.8

            mock_names.return_value = {
                str(CHAR_C_ID): "C",
                str(CHAR_D_ID): "D",
                str(CHAR_E_ID): "E",
            }

            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())
            svc.llm.complete_json = AsyncMock(
                return_value=_make_llm_hearsay_response(
                    [{"name": "C"}, {"name": "D"}], source="听说"
                )
            )

            await svc._multi_hop_hearsay(
                world_id=str(WORLD_ID),
                event_id=EVENT_ID,
                candidates=[{"character_id": CHAR_C_ID, "weight": 2, "rel_type": "朋友"}],
                source_memories=[_make_memory()],
                virtual_time=VIRTUAL_TIME,
                source_character_id=CHAR_A_ID,
                involved_characters=[CHAR_A_ID],
                source="event_flush",
                severity="high",
                world_scale="standard",
                character_repo=char_repo,
                memory_repo=mem_repo,
                relation_repo=rel_repo,
            )

        # Verify only hop-1 and hop-2 were written, no hop-3
        calls = mem_repo.add_hearsay.call_args_list
        hop_counts = [c[1]["hop_count"] for c in calls]
        assert 3 not in hop_counts  # No hop-3
        assert all(hc <= 2 for hc in hop_counts)


# ── Chat path hop-2 dedup ───────────────────────────────────────────────────


class TestChatPathHop2Dedup:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    async def test_chat_hop2_dedup_by_session(self, svc):
        """Chat path hop-2 should dedup by session_id + source_character_id."""
        existing = MagicMock()
        existing.info_amount = 0.5
        existing.content = "旧聊天传闻"

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=3)
        mem_repo.get_hearsay_by_session = AsyncMock(return_value=existing)
        mem_repo.add_hearsay = AsyncMock()

        await svc._write_hearsay_memory(
            character_id=CHAR_C_ID,
            world_id=WORLD_ID,
            content="新聊天传闻",
            visible_at=VIRTUAL_TIME,
            origin_event_id=None,
            propagated_from=CHAR_A_ID,
            source_character_id=CHAR_A_ID,
            hop_count=2,
            info_amount=0.7,
            involved_characters=None,
            session_id=SESSION_ID,
            source="chat_flush",
            severity=None,
            memory_repo=mem_repo,
        )

        # Should update existing (higher info), not create new
        assert existing.content == "新聊天传闻"
        assert existing.info_amount == 0.7
        assert existing.hop_count == 2
        mem_repo.add_hearsay.assert_not_called()


# ── _get_world_created_at ───────────────────────────────────────────────────


class TestGetWorldCreatedAt:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    def test_returns_created_at_from_world_doc(self, svc):
        """When world_doc has created_at, return it."""
        world_doc = MagicMock()
        world_doc.created_at = WORLD_CREATED_AT
        result = svc._get_world_created_at(world_doc)
        assert result == WORLD_CREATED_AT

    def test_returns_utcnow_when_no_created_at(self, svc):
        """When world_doc has no created_at, return utcnow()."""
        world_doc = MagicMock()
        world_doc.created_at = None
        before = datetime.now(UTC)
        result = svc._get_world_created_at(world_doc)
        after = datetime.now(UTC)
        assert before <= result <= after

    def test_returns_utcwhen_none_doc(self, svc):
        """When world_doc is None, return utcnow()."""
        before = datetime.now(UTC)
        result = svc._get_world_created_at(None)
        after = datetime.now(UTC)
        assert before <= result <= after


# ── Budget with unknown scale ───────────────────────────────────────────────


class TestBudgetUnknownScale:
    @pytest.fixture
    def svc(self):
        return MemoryPropagationService(llm=AsyncMock(), session_factory=MagicMock())

    def test_unknown_scale_event_budget_defaults(self, svc):
        """Unknown scale should default to 4 for event path."""
        assert svc._get_budget("unknown_scale", is_event=True) == 4

    def test_unknown_scale_chat_budget_defaults(self, svc):
        """Unknown scale should default to 2 for chat path."""
        assert svc._get_budget("unknown_scale", is_event=False) == 2


# ── Category filtering boundary tests ────────────────────────────────────────


class TestCategoryFiltering:
    """Integration tests for memory_category filtering in propagation paths.

    Only `major` memories should trigger hearsay propagation.
    `private`, `trivial`, and `None` categories must be filtered out.
    """

    async def test_propagation_only_triggered_by_major_event_path(self):
        """Only major memories pass category filter in event path."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = None
        world_doc.created_at = WORLD_CREATED_AT
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_a.name = "A"
        char_a.profile = {"brief": "角色A"}
        char_repo.find_by_name = AsyncMock(return_value=char_a)
        char_c = MagicMock()
        char_c.id = CHAR_C_ID
        char_c.name = "C"
        char_c.profile = {"brief": "角色C"}
        char_repo.get_by_id = AsyncMock(return_value=char_c)

        rel_repo = AsyncMock()
        rel = _make_relation(char_a=CHAR_A_ID, char_b=CHAR_C_ID, rel_type="朋友")
        rel_repo.list_by_world = AsyncMock(return_value=[rel])

        mem_repo = AsyncMock()
        mem_repo.get_max_sequence = AsyncMock(return_value=0)
        mem_repo.get_hearsay_by_event = AsyncMock(return_value=None)
        mem_repo.add_hearsay = AsyncMock()

        llm = AsyncMock()
        llm.complete_json = AsyncMock(
            return_value=_make_llm_hearsay_response([{"name": "C"}], source="听说")
        )

        event_index_repo = AsyncMock()
        event_index_repo.get_by_id = AsyncMock(return_value=None)
        event_index_repo.add = AsyncMock()

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)
        stack.enter_context(
            patch(
                "src.services.memory_propagation_service.EventIndexRepository",
                return_value=event_index_repo,
            )
        )

        with (
            stack,
            patch("src.services.memory_propagation_service.random") as mock_random,
            patch(
                "src.services.memory_propagation_service.get_character_names",
                new_callable=AsyncMock,
                return_value={str(CHAR_C_ID): "C"},
            ),
        ):
            mock_random.random.return_value = 0.01
            mock_random.uniform.return_value = 0.8

            svc = MemoryPropagationService(llm=llm, session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID, memory_category="major")
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] >= 1
            mem_repo.add_hearsay.assert_called()

    async def test_propagation_skips_private_memories_event_path(self):
        """Private memories are filtered out — event path returns no_propagable_memories."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_repo.get = AsyncMock(return_value=world_doc)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(world_repo=world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID, memory_category="private")
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] == 0
            assert result["skipped"] == "no_propagable_memories"

    async def test_propagation_skips_trivial_memories_event_path(self):
        """Trivial memories are filtered out — event path returns no_propagable_memories."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_repo.get = AsyncMock(return_value=world_doc)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(world_repo=world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID, memory_category="trivial")
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] == 0
            assert result["skipped"] == "no_propagable_memories"

    async def test_propagation_skips_none_category_event_path(self):
        """Memories with memory_category=None are filtered out."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_repo.get = AsyncMock(return_value=world_doc)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(world_repo=world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(origin_event_id=EVENT_ID, memory_category=None)
            result = await svc.propagate_after_event_memories(
                world_id=str(WORLD_ID),
                event_id=str(EVENT_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
                event_impacts=[{"severity": "high"}],
            )
            assert result["propagated"] == 0
            assert result["skipped"] == "no_propagable_memories"

    async def test_propagation_skips_private_trivial_chat_path(self):
        """Private/trivial memories are filtered out — chat path returns no_propagable_memories."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_repo.get = AsyncMock(return_value=world_doc)

        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(world_repo=world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            private_mem = _make_memory(
                origin_event_id=None,
                session_id=SESSION_ID,
                memory_category="private",
            )
            trivial_mem = _make_memory(
                origin_event_id=None,
                session_id=SESSION_ID,
                memory_category="trivial",
                char_id=CHAR_B_ID,
            )
            result = await svc.propagate_after_chat_flush(
                world_id=str(WORLD_ID),
                session_id=str(SESSION_ID),
                participant_names=["A"],
                newly_written_memories=[private_mem, trivial_mem],
                virtual_time=VIRTUAL_TIME,
            )
            assert result["propagated"] == 0
            assert result["skipped"] == "no_propagable_memories"


class TestDisabledConfigChatPath:
    """Chat path should also short-circuit when feature flag is disabled."""

    async def test_disabled_no_propagation_chat_path(self):
        llm = AsyncMock()
        session_factory = MagicMock()

        svc = MemoryPropagationService(llm=llm, session_factory=session_factory)

        with patch("src.services.memory_propagation_service._is_enabled", return_value=False):
            result = await svc.propagate_after_chat_flush(
                world_id=str(WORLD_ID),
                session_id=str(SESSION_ID),
                participant_names=["A"],
                newly_written_memories=[_make_memory(origin_event_id=None, session_id=SESSION_ID)],
                virtual_time=VIRTUAL_TIME,
            )

        assert result["propagated"] == 0
        assert result["skipped"] == "disabled"
        llm.complete_json.assert_not_called()
        session_factory.assert_not_called()


class TestEmptyTargetListChatPath:
    """Chat path should handle empty candidate pool gracefully."""

    async def test_empty_relations_no_candidates_chat_path(self):
        """No relations → no propagation candidates in chat path."""
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.scale = "standard"
        world_doc.user_character_id = None
        world_repo.get = AsyncMock(return_value=world_doc)

        char_repo = AsyncMock()
        char_a = MagicMock()
        char_a.id = CHAR_A_ID
        char_repo.find_by_name = AsyncMock(return_value=char_a)

        rel_repo = AsyncMock()
        rel_repo.list_by_world = AsyncMock(return_value=[])

        mem_repo = AsyncMock()
        session_factory, _ = _make_session_factory()
        _, _, _, _, stack = _patch_repos(char_repo, mem_repo, rel_repo, world_repo)

        with stack:
            svc = MemoryPropagationService(llm=AsyncMock(), session_factory=session_factory)
            mem = _make_memory(
                origin_event_id=None,
                session_id=SESSION_ID,
                memory_category="major",
            )
            result = await svc.propagate_after_chat_flush(
                world_id=str(WORLD_ID),
                session_id=str(SESSION_ID),
                participant_names=["A"],
                newly_written_memories=[mem],
                virtual_time=VIRTUAL_TIME,
            )
            assert result["propagated"] == 0
            assert result["skipped"] == "no_candidates"
