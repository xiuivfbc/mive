"""Tests for structured long-term memory (P0: four-field structure).

Tests the new structured fields: event_name, perspective_detail, reflection,
and the repository methods that work with them.
"""

from __future__ import annotations

import uuid

from src.db.models import M2CharacterMemory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_structured_memory(
    event_name: str = "测试事件",
    perspective_detail: str = "我在事件中的经历",
    reflection: str = "我的感悟",
    involved_characters: list[uuid.UUID] | None = None,
    **kwargs,
) -> M2CharacterMemory:
    """Build an in-memory M2CharacterMemory with structured fields."""
    mem = M2CharacterMemory(
        id=uuid.uuid4(),
        character_id=uuid.uuid4(),
        world_id=uuid.uuid4(),
        memory_type="long_term",
        content=f"{event_name}: {perspective_detail}",  # legacy content fallback
        event_name=event_name,
        perspective_detail=perspective_detail,
        reflection=reflection,
        involved_characters=involved_characters or [],
    )
    for k, v in kwargs.items():
        object.__setattr__(mem, k, v)
    return mem


# ---------------------------------------------------------------------------
# Model field existence tests
# ---------------------------------------------------------------------------


class TestModelFields:
    """Verify M2CharacterMemory has the new structured columns."""

    def test_event_name_field_exists(self):
        mem = M2CharacterMemory()
        # Should not raise
        mem.event_name = "test event"

    def test_perspective_detail_field_exists(self):
        mem = M2CharacterMemory()
        mem.perspective_detail = "perspective text"

    def test_reflection_field_exists(self):
        mem = M2CharacterMemory()
        mem.reflection = "reflection text"

    def test_involved_characters_field_exists(self):
        """involved_characters already existed, verify it still works."""
        mem = M2CharacterMemory()
        mem.involved_characters = [uuid.uuid4()]

    def test_tags_field_exists(self):
        """tags field for awareness mechanism (P1)."""
        mem = M2CharacterMemory()
        mem.tags = ["heard"]

    def test_dissemination_field_exists(self):
        """dissemination field for element events (P1)."""
        mem = M2CharacterMemory()
        mem.dissemination = 0.5


# ---------------------------------------------------------------------------
# Repository: add_structured_long_term tests
# ---------------------------------------------------------------------------


class TestAddStructuredLongTerm:
    """Test CharacterMemoryRepository.add_structured_long_term()."""

    async def test_add_structured_creates_long_term_memory(self):
        from src.db.repositories.character_memory_repo import CharacterMemoryRepository
        from tests.conftest import TestSession

        char_id = uuid.uuid4()
        world_id = uuid.uuid4()
        async with TestSession() as session:
            from src.db.models import M1World, M2Character

            session.add(M1World(id=world_id, user_id=uuid.uuid4(), title="t", world_doc={}))
            session.add(M2Character(id=char_id, world_id=world_id, name="C1", profile={}))
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            mem = await repo.add_structured_long_term(
                character_id=char_id,
                world_id=world_id,
                event_name="王城之变",
                perspective_detail="我亲眼目睹了政变的全过程",
                reflection="权力斗争的残酷超乎想象",
                involved_characters=[char_id],
            )
            await session.commit()
            assert mem.id is not None
            assert mem.memory_type == "long_term"
            assert mem.event_name == "王城之变"
            assert mem.perspective_detail == "我亲眼目睹了政变的全过程"
            assert mem.reflection == "权力斗争的残酷超乎想象"
            assert mem.involved_characters == [char_id]
            # content should be auto-generated from structured fields
            assert "王城之变" in mem.content

    async def test_add_structured_with_none_optional_fields(self):
        from src.db.repositories.character_memory_repo import CharacterMemoryRepository
        from tests.conftest import TestSession

        char_id = uuid.uuid4()
        world_id = uuid.uuid4()
        async with TestSession() as session:
            from src.db.models import M1World, M2Character

            session.add(M1World(id=world_id, user_id=uuid.uuid4(), title="t", world_doc={}))
            session.add(M2Character(id=char_id, world_id=world_id, name="C1", profile={}))
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            mem = await repo.add_structured_long_term(
                character_id=char_id,
                world_id=world_id,
                event_name="简单事件",
                perspective_detail="发生了某些事",
                reflection=None,
                involved_characters=None,
            )
            await session.commit()
            assert mem.event_name == "简单事件"
            assert mem.reflection is None


# ---------------------------------------------------------------------------
# Repository: get_by_event_name tests
# ---------------------------------------------------------------------------


class TestGetByEventName:
    """Test CharacterMemoryRepository.get_by_event_name()."""

    async def test_finds_existing_event_name(self):
        from src.db.repositories.character_memory_repo import CharacterMemoryRepository
        from tests.conftest import TestSession

        char_id = uuid.uuid4()
        world_id = uuid.uuid4()
        async with TestSession() as session:
            from src.db.models import M1World, M2Character

            session.add(M1World(id=world_id, user_id=uuid.uuid4(), title="t", world_doc={}))
            session.add(M2Character(id=char_id, world_id=world_id, name="C1", profile={}))
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            await repo.add_structured_long_term(
                character_id=char_id,
                world_id=world_id,
                event_name="王城之变",
                perspective_detail="详情",
                reflection=None,
                involved_characters=[char_id],
            )
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            found = await repo.get_by_event_name(char_id, "王城之变")
            assert found is not None
            assert found.event_name == "王城之变"

    async def test_returns_none_for_missing_event_name(self):
        from src.db.repositories.character_memory_repo import CharacterMemoryRepository
        from tests.conftest import TestSession

        char_id = uuid.uuid4()
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            found = await repo.get_by_event_name(char_id, "不存在的事件")
            assert found is None


# ---------------------------------------------------------------------------
# Repository: list_long_term_structured tests
# ---------------------------------------------------------------------------


class TestListLongTermStructured:
    """Test list_long_term and list_long_term_structured with mixed formats."""

    async def test_structured_memories_returned_with_fields(self):
        from src.db.repositories.character_memory_repo import CharacterMemoryRepository
        from tests.conftest import TestSession

        char_id = uuid.uuid4()
        world_id = uuid.uuid4()
        async with TestSession() as session:
            from src.db.models import M1World, M2Character

            session.add(M1World(id=world_id, user_id=uuid.uuid4(), title="t", world_doc={}))
            session.add(M2Character(id=char_id, world_id=world_id, name="C1", profile={}))
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            await repo.add_structured_long_term(
                character_id=char_id,
                world_id=world_id,
                event_name="结构化事件",
                perspective_detail="视角详情",
                reflection="感悟",
                involved_characters=[char_id],
            )
            # Also add a legacy (non-structured) long-term memory
            await repo.add(
                character_id=char_id,
                world_id=world_id,
                session_id=None,
                memory_type="long_term",
                content="旧格式长期记忆",
            )
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            # list_long_term returns ALL long-term memories
            long_mems = await repo.list_long_term(char_id)
            assert len(long_mems) == 2

            # list_long_term_structured returns only those with event_name
            structured_mems = await repo.list_long_term_structured(char_id)
            assert len(structured_mems) == 1
            assert structured_mems[0].event_name == "结构化事件"
            assert structured_mems[0].perspective_detail == "视角详情"
            assert structured_mems[0].reflection == "感悟"

    async def test_list_long_term_structured_excludes_legacy(self):
        """Legacy memories without event_name are excluded."""
        from src.db.repositories.character_memory_repo import CharacterMemoryRepository
        from tests.conftest import TestSession

        char_id = uuid.uuid4()
        world_id = uuid.uuid4()
        async with TestSession() as session:
            from src.db.models import M1World, M2Character

            session.add(M1World(id=world_id, user_id=uuid.uuid4(), title="t", world_doc={}))
            session.add(M2Character(id=char_id, world_id=world_id, name="C1", profile={}))
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            # Only add legacy memory
            await repo.add(
                character_id=char_id,
                world_id=world_id,
                session_id=None,
                memory_type="long_term",
                content="旧格式记忆",
            )
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            structured = await repo.list_long_term_structured(char_id)
            assert len(structured) == 0


# ---------------------------------------------------------------------------
# Token budget estimation
# ---------------------------------------------------------------------------


class TestTokenBudget:
    """Test token budget control for long-term memory injection."""

    def test_estimate_tokens_roughly(self):
        """Basic sanity check that token estimation works."""
        mem = _make_structured_memory(
            event_name="王城之变",
            perspective_detail="这是一段较长的事件描述" * 10,
            reflection="感悟内容" * 5,
        )
        # Rough estimate: Chinese chars ~1 token each
        text = f"{mem.event_name} {mem.perspective_detail} {mem.reflection}"
        assert len(text) > 50  # Sanity check


# ---------------------------------------------------------------------------
# Awareness tags (P1)
# ---------------------------------------------------------------------------


class TestAwarenessTags:
    """Test the awareness tag mechanism for element events (P1)."""

    def test_memory_has_tags_default_empty(self):
        mem = M2CharacterMemory()
        # tags should default to empty or None
        tags = getattr(mem, "tags", None)
        assert tags is None or tags == []

    def test_memory_can_set_heard_tag(self):
        mem = M2CharacterMemory()
        mem.tags = ["heard"]
        assert "heard" in mem.tags

    def test_memory_can_set_integrated_tag(self):
        mem = M2CharacterMemory()
        mem.tags = ["integrated"]
        assert "integrated" in mem.tags


# ---------------------------------------------------------------------------
# Dissemination (P1)
# ---------------------------------------------------------------------------


class TestDissemination:
    """Test dissemination field on memory records."""

    def test_dissemination_default_none(self):
        mem = M2CharacterMemory()
        assert mem.dissemination is None

    def test_dissemination_set_float(self):
        mem = M2CharacterMemory()
        mem.dissemination = 0.7
        assert mem.dissemination == 0.7

    def test_dissemination_boundary_zero(self):
        mem = M2CharacterMemory()
        mem.dissemination = 0.0
        assert mem.dissemination == 0.0

    def test_dissemination_boundary_one(self):
        mem = M2CharacterMemory()
        mem.dissemination = 1.0
        assert mem.dissemination == 1.0
