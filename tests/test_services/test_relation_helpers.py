"""Tests for relation helper functions.

Tests pure helper functions extracted from GenerationService's relation
generation logic: _format_evidence, assign_code_names, compute_batches,
_resolve_relation_codes, _char_with_code.
"""

from src.services.generation_service import (
    _char_with_code,
    _format_evidence,
    _resolve_relation_codes,
    assign_code_names,
    compute_batches,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _char(name: str, detail: str = "", tier: str = "core", cid: str = "") -> dict:
    """Build a minimal character dict matching the real structure."""
    return {
        "id": cid or f"id_{name}",
        "name": name,
        "tier": tier,
        "profile": {
            "brief": f"{name}简介",
            "detail": detail,
        },
    }


# ===========================================================================
# _format_evidence
# ===========================================================================


class TestFormatEvidence:
    def test_explicit_evidence(self):
        rel = {"evidence_type": "explicit"}
        assert _format_evidence(rel) == "explicit"

    def test_inferred_evidence(self):
        rel = {"evidence_type": "inferred"}
        assert _format_evidence(rel) == "inferred"

    def test_missing_evidence_type_defaults_to_inferred(self):
        rel = {"type": "friends"}
        assert _format_evidence(rel) == "inferred"

    def test_empty_relation_dict(self):
        assert _format_evidence({}) == "inferred"

    def test_none_evidence_type_defaults_to_inferred(self):
        rel = {"evidence_type": None}
        assert _format_evidence(rel) == "inferred"


# ===========================================================================
# assign_code_names
# ===========================================================================


class TestAssignCodeNames:
    def test_basic_assignment(self):
        chars = [_char("Alice"), _char("Bob"), _char("Carol")]
        code_to_id = assign_code_names(chars)
        assert code_to_id == {"C1": "id_Alice", "C2": "id_Bob", "C3": "id_Carol"}

    def test_single_character(self):
        chars = [_char("Solo")]
        code_to_id = assign_code_names(chars)
        assert code_to_id == {"C1": "id_Solo"}

    def test_empty_list(self):
        code_to_id = assign_code_names([])
        assert code_to_id == {}

    def test_preserves_list_order(self):
        chars = [_char("Z"), _char("A"), _char("M")]
        code_to_id = assign_code_names(chars)
        assert code_to_id["C1"] == "id_Z"
        assert code_to_id["C2"] == "id_A"
        assert code_to_id["C3"] == "id_M"

    def test_many_characters(self):
        chars = [_char(f"Char{i}") for i in range(30)]
        code_to_id = assign_code_names(chars)
        assert len(code_to_id) == 30
        assert code_to_id["C30"] == "id_Char29"

    def test_global_codes_no_collision(self):
        """With 3 core + 3 noncore, global codes C1..C6 have no overlap."""
        chars = [
            _char("Core1", tier="core"),
            _char("Core2", tier="core"),
            _char("Core3", tier="core"),
            _char("Sup1", tier="supporting"),
            _char("Sup2", tier="supporting"),
            _char("Extra1", tier="extra"),
        ]
        code_to_id = assign_code_names(chars)
        # All codes are unique
        assert len(code_to_id) == 6
        assert len(set(code_to_id.keys())) == 6
        # Core chars get C1-C3, noncore get C4-C6
        assert code_to_id["C1"] == "id_Core1"
        assert code_to_id["C4"] == "id_Sup1"
        assert code_to_id["C6"] == "id_Extra1"


# ===========================================================================
# _char_with_code
# ===========================================================================


class TestCharWithCode:
    def test_basic_format(self):
        char = _char("Alice", detail="勇敢的战士")
        result = _char_with_code(char, "C1")
        assert "C1" in result
        assert "Alice" in result
        assert "勇敢的战士" in result

    def test_contains_brief_and_detail(self):
        char = _char("Bob", detail="详细描写")
        result = _char_with_code(char, "C5")
        assert "brief:" in result
        assert "detail:" in result
        assert "详细描写" in result


# ===========================================================================
# compute_batches
# ===========================================================================


class TestComputeBatches:
    def test_zero(self):
        assert compute_batches(0, 200) == []

    def test_one(self):
        assert compute_batches(1, 200) == [1]

    def test_two_small_p(self):
        # remaining=2, P=3: remaining*remaining=4 > 3, b=max(1, 3//2)=1
        # first batch: b=1, remaining=1; second: 1*1<=3, b=1
        assert compute_batches(2, 3) == [1, 1]

    def test_two_large_p(self):
        # remaining=2, P=100: remaining*remaining=4 <= 100, b=2
        assert compute_batches(2, 100) == [2]

    def test_exact_budget(self):
        # remaining=5, P=20: remaining*remaining=25 > 20, b=max(1, 20//5)=4
        # remaining=1: 1*1<=20, b=1
        result = compute_batches(5, 20)
        assert sum(result) == 5
        assert result == [4, 1]

    def test_large_n_small_p(self):
        result = compute_batches(50, 20)
        assert sum(result) == 50
        assert all(b >= 1 for b in result)
        # First batches should be small (b = max(1, 20//remaining))
        # remaining=50: b=max(1,20//50)=1
        assert result[0] == 1

    def test_all_ones_when_p_lt_n(self):
        # remaining=N, P=1: b=max(1, 1//remaining)=1 for all remaining
        result = compute_batches(10, 1)
        assert result == [1] * 10

    def test_single_batch_when_p_large(self):
        # remaining=5, P=100: 5*5=25<=100, b=5
        assert compute_batches(5, 100) == [5]

    def test_sum_equals_n(self):
        for n in [0, 1, 2, 5, 10, 20, 50]:
            result = compute_batches(n, 200)
            assert sum(result) == n, f"n={n}: sum({result}) != {n}"


# ===========================================================================
# _resolve_relation_codes
# ===========================================================================


class TestResolveRelationCodes:
    def test_valid_codes(self):
        code_to_id = {"C1": "uuid-1", "C2": "uuid-2"}
        rel = {
            "character_a": "C1",
            "character_b": "C2",
            "type": "朋友",
            "description": "好友",
            "direction": "bidirectional",
            "evidence_type": "explicit",
        }
        result = _resolve_relation_codes(rel, code_to_id)
        assert result is not None
        assert result["character_a"] == "uuid-1"
        assert result["character_b"] == "uuid-2"
        assert result["type"] == "朋友"

    def test_invalid_code_a(self):
        code_to_id = {"C1": "uuid-1"}
        rel = {"character_a": "C99", "character_b": "C1", "type": "x", "description": "y"}
        result = _resolve_relation_codes(rel, code_to_id)
        assert result is None

    def test_invalid_code_b(self):
        code_to_id = {"C1": "uuid-1"}
        rel = {"character_a": "C1", "character_b": "C99", "type": "x", "description": "y"}
        result = _resolve_relation_codes(rel, code_to_id)
        assert result is None

    def test_missing_code_fields(self):
        code_to_id = {"C1": "uuid-1"}
        rel = {"type": "x", "description": "y"}
        result = _resolve_relation_codes(rel, code_to_id)
        assert result is None

    def test_preserves_other_fields(self):
        code_to_id = {"C1": "uuid-1", "C2": "uuid-2"}
        rel = {
            "character_a": "C1",
            "character_b": "C2",
            "type": "对手",
            "description": "宿敌",
            "direction": "a_to_b",
            "evidence_type": "inferred",
        }
        result = _resolve_relation_codes(rel, code_to_id)
        assert result["type"] == "对手"
        assert result["description"] == "宿敌"
        assert result["direction"] == "a_to_b"
        assert result["evidence_type"] == "inferred"

    def test_defaults_missing_optional_fields(self):
        code_to_id = {"C1": "uuid-1", "C2": "uuid-2"}
        rel = {"character_a": "C1", "character_b": "C2"}
        result = _resolve_relation_codes(rel, code_to_id)
        assert result is not None
        assert result["character_a"] == "uuid-1"
        assert result["character_b"] == "uuid-2"
        assert result["evidence_type"] == "inferred"

    def test_code_not_in_batch_scope_still_resolves(self):
        """Codes outside batch∪scope are still resolved; validation of batch∪scope
        membership is done by the caller, not by _resolve_relation_codes."""
        code_to_id = {"C1": "uuid-1", "C2": "uuid-2", "C3": "uuid-3"}
        rel = {"character_a": "C1", "character_b": "C3", "type": "x", "description": "y"}
        result = _resolve_relation_codes(rel, code_to_id)
        assert result is not None
        assert result["character_b"] == "uuid-3"
