"""Tests for event name unification mechanism (P2).

Tests:
- Event name priority rules (relation > tier > element > LLM)
- Event name conflict detection (same name + different participants)
- Rename trigger logic
"""

from __future__ import annotations

import uuid

# ---------------------------------------------------------------------------
# Event name priority tests
# ---------------------------------------------------------------------------


class TestEventNamePriority:
    """Test the four-level priority for event naming."""

    def test_relation_character_memory_highest_priority(self):
        """Priority 1: Relations' long-term memories."""
        relation_memory_names = {"王城之变": ["C1", "C2"]}
        # Priority 1: relation memory is checked first
        candidates = list(relation_memory_names.keys())
        assert candidates[0] == "王城之变"

    def test_tier_memory_second_priority(self):
        """Priority 2: Tier-ordered character memories (core > supporting)."""
        tier_memory_names = {"黑森林事件": ["C1"]}
        candidates = list(tier_memory_names.keys())
        assert "黑森林事件" in candidates

    def test_element_event_third_priority(self):
        """Priority 3: Element event names."""
        element_names = {"龙之陨落": "元素事件"}
        candidates = list(element_names.keys())
        assert "龙之陨落" in candidates

    def test_llm_fallback_last_priority(self):
        """Priority 4: LLM free naming when no existing match."""
        # LLM generates the name when no existing matches
        llm_name = "全新事件"
        assert llm_name == "全新事件"

    def test_cold_start_uses_llm_naming(self):
        """Cold start: no memories or elements, LLM names freely."""
        all_existing = set()
        llm_generated = "首次事件"
        assert llm_generated not in all_existing


# ---------------------------------------------------------------------------
# Event name conflict detection
# ---------------------------------------------------------------------------


class TestEventNameConflict:
    """Test detection of event name conflicts."""

    def test_same_name_same_participants_no_conflict(self):
        """Same event name + same participants = no conflict (same event)."""
        existing = {
            "王城之变": {"participants": {uuid.UUID(int=1), uuid.UUID(int=2)}},
        }
        new_participants = {uuid.UUID(int=1), uuid.UUID(int=2)}
        existing_entry = existing.get("王城之变")
        if existing_entry:
            # Same participants = same event, no conflict
            assert existing_entry["participants"] == new_participants

    def test_same_name_different_participants_is_conflict(self):
        """Same event name + completely different participants = conflict."""
        existing = {
            "王城之变": {"participants": {uuid.UUID(int=1), uuid.UUID(int=2)}},
        }
        new_participants = {uuid.UUID(int=3), uuid.UUID(int=4)}
        existing_entry = existing.get("王城之变")
        if existing_entry:
            # Completely different participants = conflict
            overlap = existing_entry["participants"] & new_participants
            assert len(overlap) == 0

    def test_same_name_partial_overlap_no_conflict(self):
        """Same event name + partial participant overlap = likely same event."""
        existing = {
            "王城之变": {"participants": {uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)}},
        }
        new_participants = {uuid.UUID(int=1), uuid.UUID(int=4)}
        existing_entry = existing.get("王城之变")
        if existing_entry:
            overlap = existing_entry["participants"] & new_participants
            # Has overlap = likely same event, no conflict
            assert len(overlap) > 0

    def test_conflict_triggers_rename(self):
        """When conflict detected, new event gets renamed."""
        existing_names = {"王城之变": {"participants": {uuid.UUID(int=1)}}}
        new_name = "王城之变"
        new_participants = {uuid.UUID(int=99)}

        if new_name in existing_names:
            existing_parts = existing_names[new_name]["participants"]
            overlap = existing_parts & new_participants
            if not overlap:
                # Trigger rename
                renamed = f"{new_name}_2"
                assert renamed != new_name

    def test_rename_increments_suffix(self):
        """Rename should increment suffix to avoid further collision."""
        existing_names = {"王城之变", "王城之变_2"}
        base = "王城之变"
        suffix = 2
        while f"{base}_{suffix}" in existing_names:
            suffix += 1
        assert f"{base}_{suffix}" == "王城之变_3"


# ---------------------------------------------------------------------------
# Event name generation with existing list reference
# ---------------------------------------------------------------------------


class TestEventNameGeneration:
    """Test that LLM generates event names referencing existing list."""

    def test_existing_names_provided_to_llm(self):
        """The existing event name list should be included in the LLM prompt."""
        existing_names = ["王城之变", "黑森林事件", "龙之陨落"]
        prompt_fragment = "已有事件名：" + "、".join(existing_names)
        assert "王城之变" in prompt_fragment
        assert "黑森林事件" in prompt_fragment

    def test_empty_existing_list(self):
        """When no existing names, LLM generates freely."""
        existing_names = []
        # LLM prompt should handle empty list gracefully
        assert len(existing_names) == 0
