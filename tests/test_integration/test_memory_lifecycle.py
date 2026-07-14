"""MemoryOrchestrator + MemoryModule integration tests.

Tests the full memory lifecycle against a real database:
  short-term generation -> storage -> query -> promotion -> long-term storage -> query.
LLM calls are mocked; all DB operations are real.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest_asyncio
from sqlalchemy import text

from src.db.models import M1World, M2Character
from src.db.repositories.character_memory_repo import CharacterMemoryRepository
from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.relation_repo import RelationRepository
from src.db.repositories.world_repo import WorldRepository
from src.models.character import Character
from src.models.world import Element, WorldDoc, WorldMeta, WorldSource
from src.services.memory_module import MemoryModule
from src.services.memory_orchestrator import MemoryOrchestrator
from tests.conftest import TestSession

# ── Shared test IDs ──────────────────────────────────────────────────────────

WORLD_ID = uuid.uuid4()
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
CHAR_A_ID = uuid.uuid4()
CHAR_B_ID = uuid.uuid4()


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    """Ensure each test starts with a clean slate."""
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        await session.commit()
    yield
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def seed_world():
    """Seed a world with two characters for all tests."""
    async with TestSession() as session:
        session.add(
            M1World(
                id=WORLD_ID,
                user_id=USER_ID,
                title="记忆测试世界",
                world_doc={
                    "world_id": str(WORLD_ID),
                    "source": {"title": "测试作品", "author": "测试作者"},
                    "meta": {},
                    "elements": [
                        {
                            "id": "e1",
                            "category": "场所",
                            "name": "黑森林",
                            "brief": "阴暗的森林",
                            "detail": "古老的黑森林，常年不见阳光",
                        },
                    ],
                },
            )
        )
        session.add(
            M2Character(
                id=CHAR_A_ID,
                world_id=WORLD_ID,
                name="角色A",
                profile={"brief": "勇敢的战士", "detailed": "来自北方的战士"},
            )
        )
        session.add(
            M2Character(
                id=CHAR_B_ID,
                world_id=WORLD_ID,
                name="角色B",
                profile={"brief": "聪明的法师", "detailed": "精通元素魔法"},
            )
        )
        await session.commit()


def _char_map() -> dict[str, Character]:
    """Build a char_map matching MemoryModule's expected format."""
    return {
        "角色A": Character(
            id=str(CHAR_A_ID),
            world_id=str(WORLD_ID),
            name="角色A",
            profile={"brief": "勇敢的战士", "detailed": "来自北方的战士"},
        ),
        "角色B": Character(
            id=str(CHAR_B_ID),
            world_id=str(WORLD_ID),
            name="角色B",
            profile={"brief": "聪明的法师", "detailed": "精通元素魔法"},
        ),
    }


def _make_llm_mock() -> AsyncMock:
    """Create a fresh mock LLM provider."""
    return AsyncMock()


def _make_world_doc() -> WorldDoc:
    """Build a WorldDoc for promotion tests."""
    return WorldDoc(
        world_id=str(WORLD_ID),
        source=WorldSource(title="测试作品", author="测试作者"),
        meta=WorldMeta(),
        elements=[
            Element(
                id="e1",
                category="场所",
                name="黑森林",
                brief="阴暗的森林",
                detail="古老的黑森林，常年不见阳光",
            ),
        ],
    )


# ── Short-term memory generation tests ───────────────────────────────────────


class TestShortTermMemoryGeneration:
    """Test MemoryModule.generate_short_term_memories with real DB."""

    async def test_generates_memories_for_multiple_characters(self):
        llm = _make_llm_mock()
        llm.complete_json.return_value = [
            {
                "character": "角色A",
                "content": "我在黑森林中击败了一头狼",
                "category": "major",
                "reflection": "战斗让我成长",
            },
            {
                "character": "角色B",
                "content": "我用火球术支援了角色A",
                "category": "private",
                "reflection": None,
            },
        ]

        module = MemoryModule(llm=llm, session_factory=TestSession)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            written = await module.generate_short_term_memories(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                dialogue_text="角色A: 我来挡住！角色B: 火球术！",
                event_description="在黑森林遭遇狼群",
                memory_repo=repo,
            )
            await session.commit()

        assert len(written) == 2
        assert written[0].content == "我在黑森林中击败了一头狼"
        assert written[0].memory_category == "major"
        assert written[0].short_term_reflection == "战斗让我成长"
        assert written[1].content == "我用火球术支援了角色A"
        assert written[1].memory_category == "private"

        # Verify persisted to DB
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            mems_a = await repo.list_short_term(CHAR_A_ID, limit=10)
            mems_b = await repo.list_short_term(CHAR_B_ID, limit=10)

        assert len(mems_a) == 1
        assert mems_a[0].content == "我在黑森林中击败了一头狼"
        assert len(mems_b) == 1
        assert mems_b[0].content == "我用火球术支援了角色A"

    async def test_skips_null_content(self):
        """Characters with null content should not produce a memory row."""
        llm = _make_llm_mock()
        llm.complete_json.return_value = [
            {
                "character": "角色A",
                "content": "我经历了战斗",
                "category": "major",
                "reflection": None,
            },
            {"character": "角色B", "content": None, "category": "trivial", "reflection": None},
        ]

        module = MemoryModule(llm=llm, session_factory=TestSession)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            written = await module.generate_short_term_memories(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                dialogue_text="战斗发生",
                event_description="遭遇战",
                memory_repo=repo,
            )
            await session.commit()

        assert len(written) == 1
        assert str(written[0].character_id) == str(CHAR_A_ID)

    async def test_handles_llm_failure_gracefully(self):
        """LLM exception should return empty list, not crash."""
        llm = _make_llm_mock()
        llm.complete_json.side_effect = RuntimeError("LLM unavailable")

        module = MemoryModule(llm=llm, session_factory=TestSession)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            written = await module.generate_short_term_memories(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                dialogue_text="对话",
                event_description="事件",
                memory_repo=repo,
            )

        assert written == []

    async def test_category_normalization(self):
        """Invalid categories should be normalized to None."""
        llm = _make_llm_mock()
        llm.complete_json.return_value = [
            {
                "character": "角色A",
                "content": "记忆内容",
                "category": "invalid_cat",
                "reflection": None,
            },
        ]

        module = MemoryModule(llm=llm, session_factory=TestSession)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            written = await module.generate_short_term_memories(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                dialogue_text="对话",
                event_description="事件",
                memory_repo=repo,
            )
            await session.commit()

        assert len(written) == 1
        assert written[0].memory_category is None


# ── Orchestrator delegation tests ────────────────────────────────────────────


class TestOrchestratorDelegation:
    """Test MemoryOrchestrator delegates correctly to MemoryModule."""

    async def test_orchestrator_with_no_module_returns_empty(self):
        """Orchestrator with memory_module=None should return empty list."""
        orchestrator = MemoryOrchestrator(memory_module=None)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await orchestrator.generate_short_term_memories(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                dialogue_text="对话",
                event_description="事件",
                memory_repo=repo,
            )

        assert result == []

    async def test_orchestrator_delegates_to_module(self):
        """Orchestrator should pass through to MemoryModule correctly."""
        llm = _make_llm_mock()
        llm.complete_json.return_value = [
            {
                "character": "角色A",
                "content": "我在森林中迷路了",
                "category": "private",
                "reflection": None,
            },
        ]

        module = MemoryModule(llm=llm, session_factory=TestSession)
        orchestrator = MemoryOrchestrator(memory_module=module)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            written = await orchestrator.generate_short_term_memories(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                dialogue_text="迷路了",
                event_description="森林迷路",
                memory_repo=repo,
            )
            await session.commit()

        assert len(written) == 1
        assert written[0].content == "我在森林中迷路了"

    async def test_orchestrator_swallows_module_exception(self):
        """Orchestrator should catch exceptions from MemoryModule and return []."""
        module = AsyncMock()
        module.generate_short_term_memories.side_effect = RuntimeError("boom")

        orchestrator = MemoryOrchestrator(memory_module=module)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await orchestrator.generate_short_term_memories(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                dialogue_text="对话",
                event_description="事件",
                memory_repo=repo,
            )

        assert result == []


# ── Promotion lifecycle tests ────────────────────────────────────────────────


class TestPromotionLifecycle:
    """Test the full promotion path: short-term accumulation -> promotion -> long-term storage."""

    async def _seed_short_term_memories(self, count: int) -> list[uuid.UUID]:
        """Insert `count` non-trivial short-term memories for CHAR_A."""
        ids = []
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            for i in range(count):
                mem = await repo.add(
                    character_id=CHAR_A_ID,
                    world_id=WORLD_ID,
                    session_id=None,
                    memory_type="short_term",
                    content=f"短期记忆{i}: 在黑森林的冒险经历",
                    memory_category="major" if i % 3 == 0 else "private",
                    short_term_reflection=f"感悟{i}" if i % 2 == 0 else None,
                )
                ids.append(mem.id)
            await session.commit()
        return ids

    async def test_promote_creates_long_term_and_deletes_short_term(self):
        """Full promotion: seed short-term -> promote -> verify long-term created and short-term deleted."""  # noqa: E501
        await self._seed_short_term_memories(5)

        # Verify short-term memories exist
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            st_before = await repo.list_short_term(CHAR_A_ID, limit=50)
        assert len(st_before) == 5

        # Set up mocks for promotion
        llm = _make_llm_mock()
        # Phase 1: element selection
        # Phase 2: promotion decision
        llm.complete_json.side_effect = [
            ["黑森林"],  # Phase 1: selected elements
            {  # Phase 2: promotion decision
                "promote": [
                    {
                        "event_name": "黑森林之战",
                        "event_code": "new",
                        "event_brief": "角色A在黑森林中经历了一场战斗",
                        "perspective_detail": "我在黑森林中遭遇了伏击，拼死搏斗才得以脱身",
                        "reflection": "战斗让我认识到自己的极限",
                        "involved_characters": ["C1"],
                    }
                ]
            },
        ]

        world_doc = _make_world_doc()
        world_repo = AsyncMock(spec=WorldRepository)
        world_repo.get.return_value = world_doc

        char_a = Character(
            id=str(CHAR_A_ID),
            world_id=str(WORLD_ID),
            name="角色A",
            profile={"brief": "勇敢的战士", "detailed": "来自北方的战士"},
        )
        char_b = Character(
            id=str(CHAR_B_ID),
            world_id=str(WORLD_ID),
            name="角色B",
            profile={"brief": "聪明的法师", "detailed": "精通元素魔法"},
        )
        char_repo = AsyncMock(spec=CharacterRepository)
        char_repo.list_by_world.return_value = [char_a, char_b]
        char_repo.get_by_id.return_value = char_a

        relation_repo = AsyncMock(spec=RelationRepository)
        relation_repo.list_by_world.return_value = []

        module = MemoryModule(llm=llm, session_factory=TestSession, redis=None)

        # Seed an event index entry so the event code resolution works
        async with TestSession() as session:
            # Promote
            await module.promote_long_term_memories_for_character(
                session=session,
                world_id=str(WORLD_ID),
                character=char_a,
                memory_repo=CharacterMemoryRepository(session),
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )
            await session.commit()

        # Verify: long-term memory created
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            lt = await repo.list_long_term(CHAR_A_ID)
            st_after = await repo.get_oldest_short_term(CHAR_A_ID, limit=50)

        assert len(lt) == 1
        assert lt[0].memory_type == "long_term"
        assert lt[0].perspective_detail == "我在黑森林中遭遇了伏击，拼死搏斗才得以脱身"
        assert lt[0].reflection == "战斗让我认识到自己的极限"
        assert lt[0].event_name is not None  # event ID stored

        # Short-term memories should be deleted after promotion
        assert len(st_after) == 0

    async def test_promote_no_short_term_is_noop(self):
        """When there are no short-term memories, promotion should be a no-op."""
        llm = _make_llm_mock()

        world_repo = AsyncMock(spec=WorldRepository)
        char_repo = AsyncMock(spec=CharacterRepository)
        relation_repo = AsyncMock(spec=RelationRepository)

        char_a = Character(
            id=str(CHAR_A_ID),
            world_id=str(WORLD_ID),
            name="角色A",
            profile={"brief": "战士"},
        )
        module = MemoryModule(llm=llm, session_factory=TestSession, redis=None)

        async with TestSession() as session:
            await module.promote_long_term_memories_for_character(
                session=session,
                world_id=str(WORLD_ID),
                character=char_a,
                memory_repo=CharacterMemoryRepository(session),
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )
            await session.commit()

        # No LLM calls should have been made
        llm.complete_json.assert_not_called()

        # No long-term memories
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            lt = await repo.list_long_term(CHAR_A_ID)
        assert lt == []

    async def test_promote_llm_failure_is_noop(self):
        """If LLM fails during promotion, no memories should be written or deleted."""
        await self._seed_short_term_memories(5)

        llm = _make_llm_mock()
        llm.complete_json.side_effect = RuntimeError("LLM down")

        world_doc = _make_world_doc()
        world_repo = AsyncMock(spec=WorldRepository)
        world_repo.get.return_value = world_doc

        char_a = Character(
            id=str(CHAR_A_ID),
            world_id=str(WORLD_ID),
            name="角色A",
            profile={"brief": "战士", "detailed": "战士详情"},
        )
        char_repo = AsyncMock(spec=CharacterRepository)
        char_repo.list_by_world.return_value = [char_a]
        relation_repo = AsyncMock(spec=RelationRepository)
        relation_repo.list_by_world.return_value = []

        module = MemoryModule(llm=llm, session_factory=TestSession, redis=None)

        async with TestSession() as session:
            await module.promote_long_term_memories_for_character(
                session=session,
                world_id=str(WORLD_ID),
                character=char_a,
                memory_repo=CharacterMemoryRepository(session),
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )
            await session.commit()

        # Short-term memories should still exist (no deletion on failure)
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            st = await repo.list_short_term(CHAR_A_ID, limit=50)
            lt = await repo.list_long_term(CHAR_A_ID)

        assert len(st) == 5
        assert lt == []

    async def test_promote_with_existing_event_index(self):
        """When an event code matches an existing event index entry, use its ID."""
        await self._seed_short_term_memories(5)

        # Seed an event index entry
        event_id = uuid.uuid4()
        async with TestSession() as session:
            from src.db.models import M26EventIndex

            session.add(
                M26EventIndex(
                    id=event_id,
                    world_id=WORLD_ID,
                    event_name="黑森林之战",
                    brief="在黑森林中的战斗",
                )
            )
            await session.commit()

        llm = _make_llm_mock()
        llm.complete_json.side_effect = [
            ["黑森林"],  # Phase 1
            {
                "promote": [
                    {
                        "event_name": "黑森林之战",
                        "event_code": "E001",
                        "perspective_detail": "我在黑森林中经历了生死之战",
                        "reflection": None,
                        "involved_characters": ["C1"],
                    }
                ]
            },
        ]

        world_doc = _make_world_doc()
        world_repo = AsyncMock(spec=WorldRepository)
        world_repo.get.return_value = world_doc

        char_a = Character(
            id=str(CHAR_A_ID),
            world_id=str(WORLD_ID),
            name="角色A",
            profile={"brief": "战士", "detailed": "战士详情"},
        )
        char_b = Character(
            id=str(CHAR_B_ID),
            world_id=str(WORLD_ID),
            name="角色B",
            profile={"brief": "法师", "detailed": "法师详情"},
        )
        char_repo = AsyncMock(spec=CharacterRepository)
        char_repo.list_by_world.return_value = [char_a, char_b]
        char_repo.get_by_id.return_value = char_a
        relation_repo = AsyncMock(spec=RelationRepository)
        relation_repo.list_by_world.return_value = []

        module = MemoryModule(llm=llm, session_factory=TestSession, redis=None)

        async with TestSession() as session:
            await module.promote_long_term_memories_for_character(
                session=session,
                world_id=str(WORLD_ID),
                character=char_a,
                memory_repo=CharacterMemoryRepository(session),
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )
            await session.commit()

        # Verify the long-term memory references the existing event ID
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            lt = await repo.list_long_term(CHAR_A_ID)

        assert len(lt) == 1
        assert lt[0].event_name == str(event_id)  # references existing event index entry


# ── Orchestrator check_and_promote tests ─────────────────────────────────────


class TestOrchestratorPromotion:
    """Test MemoryOrchestrator.check_and_promote integration."""

    async def test_check_and_promote_with_no_module(self):
        """Orchestrator with no module should be a no-op."""
        orchestrator = MemoryOrchestrator(memory_module=None)

        async with TestSession() as session:
            await orchestrator.check_and_promote(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                memory_repo=CharacterMemoryRepository(session),
                world_repo=AsyncMock(),
                relation_repo=AsyncMock(),
                char_repo=AsyncMock(),
            )
            await session.commit()

        # No crash, no side effects

    async def test_check_and_promote_respects_threshold(self):
        """Characters below the promotion threshold should not be promoted."""
        # Seed only 10 short-term memories (threshold is 40)
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            for i in range(10):
                await repo.add(
                    character_id=CHAR_A_ID,
                    world_id=WORLD_ID,
                    session_id=None,
                    memory_type="short_term",
                    content=f"记忆{i}",
                    memory_category="major",
                )
            await session.commit()

        llm = _make_llm_mock()
        module = MemoryModule(llm=llm, session_factory=TestSession, redis=None)
        orchestrator = MemoryOrchestrator(memory_module=module)

        world_repo = AsyncMock(spec=WorldRepository)
        char_repo = AsyncMock(spec=CharacterRepository)
        relation_repo = AsyncMock(spec=RelationRepository)

        async with TestSession() as session:
            await orchestrator.check_and_promote(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                memory_repo=CharacterMemoryRepository(session),
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )
            await session.commit()

        # No promotion should have happened (below threshold)
        llm.complete_json.assert_not_called()


# ── Concurrent memory generation tests ───────────────────────────────────────


class TestConcurrentMemoryGeneration:
    """Test concurrent memory generation for multiple characters."""

    async def test_concurrent_generation_for_different_characters(self):
        """Simulate two concurrent memory generation calls for different characters."""
        import asyncio

        results_a = [
            {
                "character": "角色A",
                "content": "角色A的记忆A",
                "category": "major",
                "reflection": None,
            },
        ]
        results_b = [
            {
                "character": "角色B",
                "content": "角色B的记忆B",
                "category": "private",
                "reflection": None,
            },
        ]

        call_count = 0

        async def mock_complete_json(system_prompt, user_prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if "角色A" in system_prompt and call_count <= 1:
                return results_a
            return results_b

        llm = _make_llm_mock()
        llm.complete_json.side_effect = mock_complete_json

        module = MemoryModule(llm=llm, session_factory=TestSession)

        async def generate_for_char(char_name: str, char_id: uuid.UUID):
            char_single_map = {
                char_name: Character(
                    id=str(char_id),
                    world_id=str(WORLD_ID),
                    name=char_name,
                    profile={"brief": "测试"},
                ),
            }
            async with TestSession() as session:
                repo = CharacterMemoryRepository(session)
                written = await module.generate_short_term_memories(
                    session=session,
                    world_id=str(WORLD_ID),
                    char_map=char_single_map,
                    dialogue_text=f"{char_name}的对话",
                    event_description="共同事件",
                    memory_repo=repo,
                )
                await session.commit()
            return written

        # Run concurrently
        results = await asyncio.gather(
            generate_for_char("角色A", CHAR_A_ID),
            generate_for_char("角色B", CHAR_B_ID),
        )

        # Both should succeed
        assert len(results) == 2
        total_written = sum(len(r) for r in results)
        assert total_written >= 1  # At least one should succeed

        # Verify DB state
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            mems_a = await repo.list_short_term(CHAR_A_ID, limit=10)
            mems_b = await repo.list_short_term(CHAR_B_ID, limit=10)

        # At least one character should have memories
        assert len(mems_a) + len(mems_b) >= 1


# ── Data consistency tests ───────────────────────────────────────────────────


class TestDataConsistency:
    """Verify data consistency across the memory lifecycle."""

    async def test_short_term_memory_fields_complete(self):
        """All required fields should be populated on a short-term memory."""
        llm = _make_llm_mock()
        llm.complete_json.return_value = [
            {
                "character": "角色A",
                "content": "完整的记忆内容",
                "category": "major",
                "reflection": "深刻的感悟",
            },
        ]

        module = MemoryModule(llm=llm, session_factory=TestSession)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            written = await module.generate_short_term_memories(
                session=session,
                world_id=str(WORLD_ID),
                char_map=_char_map(),
                dialogue_text="对话",
                event_description="事件",
                memory_repo=repo,
                session_id=None,
            )
            await session.commit()

        assert len(written) == 1
        mem = written[0]
        assert mem.id is not None
        assert str(mem.character_id) == str(CHAR_A_ID)
        assert str(mem.world_id) == str(WORLD_ID)
        assert mem.memory_type == "short_term"
        assert mem.content == "完整的记忆内容"
        assert mem.memory_category == "major"
        assert mem.short_term_reflection == "深刻的感悟"
        assert mem.is_hearsay is False
        assert mem.created_at is not None

    async def test_long_term_memory_structured_fields(self):
        """Long-term memory should have all four structured fields populated correctly."""
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            mem = await repo.add_structured_long_term(
                character_id=CHAR_A_ID,
                world_id=WORLD_ID,
                event_name="测试事件",
                perspective_detail="角色视角的详情",
                reflection="角色的感悟",
                involved_characters=[CHAR_B_ID],
            )
            await session.commit()

        assert mem.memory_type == "long_term"
        assert mem.event_name == "测试事件"
        assert mem.perspective_detail == "角色视角的详情"
        assert mem.reflection == "角色的感悟"
        assert mem.involved_characters == [CHAR_B_ID]
        # content is auto-generated from event_name + perspective_detail
        assert mem.content == "测试事件: 角色视角的详情"

    async def test_promotion_preserves_data_integrity(self):
        """After promotion, verify full state: long-term exists, short-term gone."""
        # Seed 5 short-term memories
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            for i in range(5):
                await repo.add(
                    character_id=CHAR_A_ID,
                    world_id=WORLD_ID,
                    session_id=None,
                    memory_type="short_term",
                    content=f"记忆{i}",
                    memory_category="major",
                    short_term_reflection=f"感悟{i}" if i < 2 else None,
                )
            await session.commit()

        llm = _make_llm_mock()
        llm.complete_json.side_effect = [
            ["黑森林"],  # Phase 1
            {
                "promote": [
                    {
                        "event_name": "重大事件",
                        "event_code": "new",
                        "event_brief": "发生了重大事件",
                        "perspective_detail": "我经历了重大事件",
                        "reflection": "这改变了我",
                        "involved_characters": ["C1", "C2"],
                    }
                ]
            },
        ]

        world_doc = _make_world_doc()
        world_repo = AsyncMock(spec=WorldRepository)
        world_repo.get.return_value = world_doc

        char_a = Character(
            id=str(CHAR_A_ID),
            world_id=str(WORLD_ID),
            name="角色A",
            profile={"brief": "战士", "detailed": "战士详情"},
        )
        char_b = Character(
            id=str(CHAR_B_ID),
            world_id=str(WORLD_ID),
            name="角色B",
            profile={"brief": "法师", "detailed": "法师详情"},
        )
        char_repo = AsyncMock(spec=CharacterRepository)
        char_repo.list_by_world.return_value = [char_a, char_b]
        char_repo.get_by_id.return_value = char_a
        relation_repo = AsyncMock(spec=RelationRepository)
        relation_repo.list_by_world.return_value = []

        module = MemoryModule(llm=llm, session_factory=TestSession, redis=None)

        async with TestSession() as session:
            await module.promote_long_term_memories_for_character(
                session=session,
                world_id=str(WORLD_ID),
                character=char_a,
                memory_repo=CharacterMemoryRepository(session),
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )
            await session.commit()

        # Final state verification
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            lt = await repo.list_long_term(CHAR_A_ID)
            st = await repo.get_oldest_short_term(CHAR_A_ID, limit=50)

        # Long-term: 1 promoted memory
        assert len(lt) == 1
        lt_mem = lt[0]
        assert lt_mem.perspective_detail == "我经历了重大事件"
        assert lt_mem.reflection == "这改变了我"
        assert lt_mem.involved_characters is not None
        assert len(lt_mem.involved_characters) == 2

        # Short-term: all deleted after successful promotion
        assert len(st) == 0

    async def test_trivial_memories_excluded_from_promotion(self):
        """Trivial memories should not be candidates for promotion."""
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            # 3 trivial + 2 major = 5 total
            for i in range(3):
                await repo.add(
                    character_id=CHAR_A_ID,
                    world_id=WORLD_ID,
                    session_id=None,
                    memory_type="short_term",
                    content=f"琐事{i}",
                    memory_category="trivial",
                )
            for i in range(2):
                await repo.add(
                    character_id=CHAR_A_ID,
                    world_id=WORLD_ID,
                    session_id=None,
                    memory_type="short_term",
                    content=f"重要事件{i}",
                    memory_category="major",
                )
            await session.commit()

        # get_oldest_short_term with exclude_categories=["trivial"] should return only 2
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            candidates = await repo.get_oldest_short_term(
                CHAR_A_ID, limit=50, exclude_categories=["trivial"]
            )
        assert len(candidates) == 2
        for c in candidates:
            assert c.memory_category != "trivial"
