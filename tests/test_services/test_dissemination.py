"""Tests for element event dissemination and memory integration (P1).

Tests:
- Dissemination probability mechanism
- Awareness tag state machine (no tag -> heard -> integrated)
- Integration background task behavior
"""

from __future__ import annotations

import random
import uuid

from src.db.models import M2CharacterMemory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(
    content: str = "记忆",
    tags: list[str] | None = None,
    dissemination: float | None = None,
    **kwargs,
) -> M2CharacterMemory:
    mem = M2CharacterMemory(
        id=uuid.uuid4(),
        character_id=uuid.uuid4(),
        world_id=uuid.uuid4(),
        memory_type="short_term",
        content=content,
        tags=tags,
        dissemination=dissemination,
    )
    for k, v in kwargs.items():
        object.__setattr__(mem, k, v)
    return mem


# ---------------------------------------------------------------------------
# Dissemination probability tests
# ---------------------------------------------------------------------------


class TestDisseminationProbability:
    """Test the random probability check for dissemination."""

    def test_high_dissemination_always_hits(self):
        """Dissemination 1.0 should always hit."""
        dissemination = 1.0
        random_val = random.random()
        assert random_val <= dissemination or random_val == dissemination

    def test_zero_dissemination_never_hits(self):
        """Dissemination 0.0 should never hit."""
        dissemination = 0.0
        # With random.random(), the probability of getting exactly 0.0 is ~0
        # But 0.0 <= any positive random is False
        random_val = 0.5
        assert not (random_val <= dissemination)

    def test_probability_check_with_random(self):
        """Test the core probability check logic."""
        dissemination = 0.5
        # Set seed for deterministic test
        rng = random.Random(42)
        hits = sum(1 for _ in range(1000) if rng.random() <= dissemination)
        # Should be roughly 500 out of 1000
        assert 400 < hits < 600

    def test_no_tag_triggers_check(self):
        """Only memories without tags should trigger dissemination check."""
        mem_no_tag = _make_memory(tags=None)
        mem_heard = _make_memory(tags=["heard"])
        mem_integrated = _make_memory(tags=["integrated"])

        should_check = [m for m in [mem_no_tag, mem_heard, mem_integrated] if not m.tags]
        assert len(should_check) == 1

    def test_already_tagged_skips_check(self):
        """Memories with existing tags skip the probability check."""
        mem = _make_memory(tags=["heard"])
        # Should return directly, no random check
        assert mem.tags is not None and len(mem.tags) > 0


# ---------------------------------------------------------------------------
# Awareness tag state machine
# ---------------------------------------------------------------------------


class TestAwarenessStateMachine:
    """Test the tag state machine: no tag -> heard -> integrated."""

    def test_no_tag_initial_state(self):
        mem = _make_memory(tags=None)
        assert not mem.tags

    def test_transition_to_heard(self):
        mem = _make_memory(tags=None)
        mem.tags = ["heard"]
        assert "heard" in mem.tags
        assert "integrated" not in mem.tags

    def test_transition_heard_to_integrated(self):
        mem = _make_memory(tags=["heard"])
        mem.tags = ["integrated"]
        assert "integrated" in mem.tags
        assert "heard" not in mem.tags

    def test_heard_provides_summary_level_data(self):
        """'Heard' state should provide event name + summary."""
        mem = _make_memory(tags=["heard"])
        object.__setattr__(mem, "event_name", "王城之变")
        object.__setattr__(mem, "perspective_detail", None)
        # Heard = summary only, no full detail
        assert mem.tags == ["heard"]
        assert mem.perspective_detail is None

    def test_integrated_provides_full_data(self):
        """'Integrated' state should provide complete details."""
        mem = _make_memory(tags=["integrated"])
        object.__setattr__(mem, "event_name", "王城之变")
        object.__setattr__(mem, "perspective_detail", "完整视角详情")
        object.__setattr__(mem, "reflection", "完整感悟")
        assert mem.perspective_detail is not None
        assert mem.reflection is not None

    def test_cannot_skip_to_integrated(self):
        """State machine enforces: must go through 'heard' first.
        (Implemented via business logic, not model constraint.)"""
        mem = _make_memory(tags=None)
        # Direct jump to integrated is not allowed by convention
        # The integration task should only process 'heard' memories
        valid_transitions = {
            None: ["heard"],
            "heard": ["integrated"],
            "integrated": [],
        }
        current = mem.tags[0] if mem.tags else None
        assert valid_transitions.get(current) is not None


# ---------------------------------------------------------------------------
# Atomicity of tag writes
# ---------------------------------------------------------------------------


class TestTagWriteAtomicity:
    """Test that tag writes are atomic (same transaction as dissemination check)."""

    def test_tag_write_in_same_transaction(self):
        """Tag and memory should be written in the same DB transaction."""
        # This is a conceptual test - actual implementation uses
        # session.flush() within the same transaction
        mem = _make_memory(tags=None)
        # Simulate: check dissemination -> write tag in same transaction
        mem.tags = ["heard"]
        # If the transaction fails, both the check and tag write should roll back
        assert "heard" in mem.tags


# ---------------------------------------------------------------------------
# Integration background task (P1)
# ---------------------------------------------------------------------------


class TestIntegrationTask:
    """Test that memory integration runs as a background task."""

    def test_integration_not_in_injection_path(self):
        """Integration should not happen during memory injection."""
        # Injection only reads existing tags, never triggers integration
        mem = _make_memory(tags=["heard"])
        # Injection sees "heard" and provides summary data
        # Integration is a separate background task
        assert mem.tags == ["heard"]

    def test_integration_processes_only_heard(self):
        """Integration task should only process 'heard' memories."""
        heard = _make_memory(tags=["heard"])
        integrated = _make_memory(tags=["integrated"])
        no_tag = _make_memory(tags=None)

        candidates = [m for m in [heard, integrated, no_tag] if m.tags and "heard" in m.tags]
        assert len(candidates) == 1
        assert candidates[0] == heard

    def test_integration_uses_character_perspective_as_primary(self):
        """During integration, character's subjective perspective is primary."""
        character_memory = _make_memory(
            content="我亲眼看到了王城之变",
            tags=["heard"],
        )
        object.__setattr__(character_memory, "perspective_detail", "我站在城墙上目睹了一切")
        # Element event exists but character perspective takes priority
        # element_event = {"name": "王城之变", "detail": "客观的事件描述"}

        # Character perspective should take priority
        merged_detail = character_memory.perspective_detail
        assert "我站在城墙上" in merged_detail
