"""Tests for MemoryOrchestrator — unified memory lifecycle facade."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.character import Character
from src.services.memory_orchestrator import MemoryOrchestrator

WORLD_ID = str(uuid.uuid4())
CHAR_A_ID = uuid.uuid4()
CHAR_B_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()


def _make_character(char_id: uuid.UUID = CHAR_A_ID, name: str = "Alice") -> Character:
    return Character(
        id=str(char_id),
        world_id=WORLD_ID,
        name=name,
        profile={"brief": f"{name}简介"},
        tier="core",
    )


def _make_mem_obj(content: str = "记忆内容"):
    mem = MagicMock()
    mem.id = uuid.uuid4()
    mem.content = content
    return mem


@pytest.fixture
def memory_module():
    mod = AsyncMock()
    mod.generate_short_term_memories = AsyncMock(return_value=[_make_mem_obj()])
    mod.promote_long_term_memories_for_character = AsyncMock()
    return mod


@pytest.fixture
def propagation_service():
    svc = AsyncMock()
    svc.propagate_after_event_memories = AsyncMock(return_value={"propagated": 1})
    svc.propagate_after_chat_flush = AsyncMock(return_value={"propagated": 1})
    return svc


@pytest.fixture
def memory_repo():
    repo = AsyncMock()
    repo.list_characters_needing_promotion = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def world_repo():
    return AsyncMock()


@pytest.fixture
def relation_repo():
    return AsyncMock()


@pytest.fixture
def char_repo():
    return AsyncMock()


@pytest.fixture
def session():
    return AsyncMock()


@pytest.fixture
def orchestrator(memory_module, propagation_service):
    return MemoryOrchestrator(
        memory_module=memory_module,
        memory_propagation_service=propagation_service,
    )


@pytest.fixture
def orchestrator_no_module():
    return MemoryOrchestrator(memory_module=None)


@pytest.fixture
def orchestrator_no_propagation(memory_module):
    return MemoryOrchestrator(
        memory_module=memory_module,
        memory_propagation_service=None,
    )


# ── generate_short_term_memories ───────────────────────────────────────────


class TestGenerateShortTermMemories:
    @pytest.mark.asyncio
    async def test_delegates_to_memory_module(
        self, orchestrator, memory_module, session, memory_repo
    ):
        """Should delegate to memory_module.generate_short_term_memories."""
        char_map = {"Alice": _make_character()}
        expected = [_make_mem_obj(), _make_mem_obj()]
        memory_module.generate_short_term_memories = AsyncMock(return_value=expected)

        result = await orchestrator.generate_short_term_memories(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=memory_repo,
        )

        assert result == expected
        memory_module.generate_short_term_memories.assert_called_once_with(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=memory_repo,
            session_id=None,
            embedding_provider=None,
        )

    @pytest.mark.asyncio
    async def test_returns_empty_when_module_is_none(
        self, orchestrator_no_module, session, memory_repo
    ):
        """When memory_module is None, should return empty list."""
        char_map = {"Alice": _make_character()}

        result = await orchestrator_no_module.generate_short_term_memories(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=memory_repo,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_module_exception(
        self, orchestrator, memory_module, session, memory_repo
    ):
        """When memory_module raises, should catch and return empty list."""
        memory_module.generate_short_term_memories = AsyncMock(
            side_effect=RuntimeError("LLM failure")
        )
        char_map = {"Alice": _make_character()}

        result = await orchestrator.generate_short_term_memories(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=memory_repo,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_passes_optional_params(self, orchestrator, memory_module, session, memory_repo):
        """session_id and embedding_provider should be forwarded."""
        char_map = {"Alice": _make_character()}
        embedding_provider = AsyncMock()
        sid = uuid.uuid4()

        await orchestrator.generate_short_term_memories(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=memory_repo,
            session_id=sid,
            embedding_provider=embedding_provider,
        )

        memory_module.generate_short_term_memories.assert_called_once()
        call_kwargs = memory_module.generate_short_term_memories.call_args[1]
        assert call_kwargs["session_id"] == sid
        assert call_kwargs["embedding_provider"] == embedding_provider


# ── check_and_promote ───────────────────────────────────────────────────────


class TestCheckAndPromote:
    @pytest.mark.asyncio
    async def test_noop_when_module_is_none(
        self, orchestrator_no_module, session, memory_repo, world_repo, relation_repo, char_repo
    ):
        """When memory_module is None, should return without any calls."""
        char_map = {"Alice": _make_character()}

        await orchestrator_no_module.check_and_promote(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        memory_repo.list_characters_needing_promotion.assert_not_called()

    @pytest.mark.asyncio
    async def test_promotes_characters_needing_promotion(
        self,
        orchestrator,
        memory_module,
        session,
        memory_repo,
        world_repo,
        relation_repo,
        char_repo,
    ):
        """Characters in the promotion list should be promoted."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_b = _make_character(CHAR_B_ID, "Bob")
        char_map = {"Alice": char_a, "Bob": char_b}

        # Only Alice needs promotion (repo returns real UUID objects, matching the UUID DB column)
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value={CHAR_A_ID})

        await orchestrator.check_and_promote(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        # list_characters_needing_promotion called with keyword args
        memory_repo.list_characters_needing_promotion.assert_called_once()
        call_args = memory_repo.list_characters_needing_promotion.call_args
        assert call_args[1]["threshold"] == 40
        assert call_args[1]["exclude_categories"] == ["trivial"]

        # Only Alice should be promoted
        memory_module.promote_long_term_memories_for_character.assert_called_once()
        call_kwargs = memory_module.promote_long_term_memories_for_character.call_args[1]
        assert call_kwargs["character"] == char_a

    @pytest.mark.asyncio
    async def test_no_characters_needing_promotion(
        self,
        orchestrator,
        memory_module,
        session,
        memory_repo,
        world_repo,
        relation_repo,
        char_repo,
    ):
        """When no characters need promotion, should not call promote."""
        char_map = {"Alice": _make_character()}
        memory_repo.list_characters_needing_promotion = AsyncMock(return_value=[])

        await orchestrator.check_and_promote(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        memory_module.promote_long_term_memories_for_character.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_characters_promoted(
        self,
        orchestrator,
        memory_module,
        session,
        memory_repo,
        world_repo,
        relation_repo,
        char_repo,
    ):
        """All characters needing promotion should be promoted."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_b = _make_character(CHAR_B_ID, "Bob")
        char_map = {"Alice": char_a, "Bob": char_b}
        memory_repo.list_characters_needing_promotion = AsyncMock(
            return_value={CHAR_A_ID, CHAR_B_ID}
        )

        await orchestrator.check_and_promote(
            session=session,
            world_id=WORLD_ID,
            char_map=char_map,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        assert memory_module.promote_long_term_memories_for_character.call_count == 2


# ── dispatch_event_propagation ──────────────────────────────────────────────


class TestDispatchEventPropagation:
    @pytest.mark.asyncio
    async def test_delegates_to_propagation_service(self, orchestrator, propagation_service):
        """Should delegate to propagation_service.propagate_after_event_memories."""
        memories = [_make_mem_obj()]
        virtual_time = MagicMock()

        await orchestrator.dispatch_event_propagation(
            world_id=WORLD_ID,
            event_id=str(uuid.uuid4()),
            participant_names=["Alice"],
            newly_written_memories=memories,
            virtual_time=virtual_time,
            event_impacts=[{"severity": "high"}],
        )

        propagation_service.propagate_after_event_memories.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_when_propagation_service_is_none(self):
        """When propagation_service is None, should return without error."""
        orchestrator = MemoryOrchestrator(
            memory_module=AsyncMock(),
            memory_propagation_service=None,
        )

        # Should not raise
        await orchestrator.dispatch_event_propagation(
            world_id=WORLD_ID,
            event_id=str(uuid.uuid4()),
            participant_names=["Alice"],
            newly_written_memories=[_make_mem_obj()],
            virtual_time=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_noop_when_memories_empty(self, orchestrator, propagation_service):
        """When newly_written_memories is empty, should skip propagation."""
        await orchestrator.dispatch_event_propagation(
            world_id=WORLD_ID,
            event_id=str(uuid.uuid4()),
            participant_names=["Alice"],
            newly_written_memories=[],
            virtual_time=MagicMock(),
        )

        propagation_service.propagate_after_event_memories.assert_not_called()

    @pytest.mark.asyncio
    async def test_catches_propagation_exception(self, orchestrator, propagation_service):
        """When propagation raises, should catch and not re-raise."""
        propagation_service.propagate_after_event_memories = AsyncMock(
            side_effect=RuntimeError("Propagation failed")
        )

        # Should not raise
        await orchestrator.dispatch_event_propagation(
            world_id=WORLD_ID,
            event_id=str(uuid.uuid4()),
            participant_names=["Alice"],
            newly_written_memories=[_make_mem_obj()],
            virtual_time=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_passes_event_impacts(self, orchestrator, propagation_service):
        """event_impacts should be forwarded; defaults to empty list when None."""
        event_id = str(uuid.uuid4())
        impacts = [{"severity": "critical"}]
        memories = [_make_mem_obj()]
        vt = MagicMock()

        await orchestrator.dispatch_event_propagation(
            world_id=WORLD_ID,
            event_id=event_id,
            participant_names=["Alice"],
            newly_written_memories=memories,
            virtual_time=vt,
            event_impacts=impacts,
        )

        call_kwargs = propagation_service.propagate_after_event_memories.call_args[1]
        assert call_kwargs["event_impacts"] == impacts

    @pytest.mark.asyncio
    async def test_event_impacts_defaults_to_empty(self, orchestrator, propagation_service):
        """When event_impacts is not provided, should default to empty list."""
        memories = [_make_mem_obj()]
        vt = MagicMock()

        await orchestrator.dispatch_event_propagation(
            world_id=WORLD_ID,
            event_id=str(uuid.uuid4()),
            participant_names=["Alice"],
            newly_written_memories=memories,
            virtual_time=vt,
        )

        call_kwargs = propagation_service.propagate_after_event_memories.call_args[1]
        assert call_kwargs["event_impacts"] == []


# ── dispatch_chat_propagation ───────────────────────────────────────────────


class TestDispatchChatPropagation:
    @pytest.mark.asyncio
    async def test_delegates_to_propagation_service(self, orchestrator, propagation_service):
        """Should delegate to propagation_service.propagate_after_chat_flush."""
        memories = [_make_mem_obj()]
        virtual_time = MagicMock()

        await orchestrator.dispatch_chat_propagation(
            world_id=WORLD_ID,
            session_id=str(SESSION_ID),
            participant_names=["Alice"],
            newly_written_memories=memories,
            virtual_time=virtual_time,
        )

        propagation_service.propagate_after_chat_flush.assert_called_once_with(
            world_id=WORLD_ID,
            session_id=str(SESSION_ID),
            participant_names=["Alice"],
            newly_written_memories=memories,
            virtual_time=virtual_time,
        )

    @pytest.mark.asyncio
    async def test_noop_when_propagation_service_is_none(self):
        """When propagation_service is None, should return without error."""
        orchestrator = MemoryOrchestrator(
            memory_module=AsyncMock(),
            memory_propagation_service=None,
        )

        # Should not raise
        await orchestrator.dispatch_chat_propagation(
            world_id=WORLD_ID,
            session_id=str(SESSION_ID),
            participant_names=["Alice"],
            newly_written_memories=[_make_mem_obj()],
            virtual_time=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_noop_when_memories_empty(self, orchestrator, propagation_service):
        """When newly_written_memories is empty, should skip propagation."""
        await orchestrator.dispatch_chat_propagation(
            world_id=WORLD_ID,
            session_id=str(SESSION_ID),
            participant_names=["Alice"],
            newly_written_memories=[],
            virtual_time=MagicMock(),
        )

        propagation_service.propagate_after_chat_flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_catches_propagation_exception(self, orchestrator, propagation_service):
        """When propagation raises, should catch and not re-raise."""
        propagation_service.propagate_after_chat_flush = AsyncMock(
            side_effect=RuntimeError("Propagation failed")
        )

        # Should not raise
        await orchestrator.dispatch_chat_propagation(
            world_id=WORLD_ID,
            session_id=str(SESSION_ID),
            participant_names=["Alice"],
            newly_written_memories=[_make_mem_obj()],
            virtual_time=MagicMock(),
        )


# ── Construction ────────────────────────────────────────────────────────────


class TestConstruction:
    def test_construction_with_all_deps(self):
        """Should accept both memory_module and propagation_service."""
        mod = AsyncMock()
        prop = AsyncMock()
        orch = MemoryOrchestrator(memory_module=mod, memory_propagation_service=prop)
        assert orch.memory_module is mod
        assert orch.memory_propagation_service is prop

    def test_construction_with_no_module(self):
        """Should accept None for memory_module."""
        orch = MemoryOrchestrator(memory_module=None)
        assert orch.memory_module is None
        assert orch.memory_propagation_service is None

    def test_construction_with_no_propagation(self):
        """Should accept None for memory_propagation_service (default)."""
        mod = AsyncMock()
        orch = MemoryOrchestrator(memory_module=mod)
        assert orch.memory_module is mod
        assert orch.memory_propagation_service is None
