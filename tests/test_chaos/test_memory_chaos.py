"""Chaos tests for the memory system.

Tests that the system handles abnormal conditions gracefully:
- LLM timeout / errors
- Invalid JSON from LLM
- Database connection failures
- Concurrent promotion race conditions
- Memory pressure (large inputs)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.character import Character
from src.services.memory_module import MemoryModule
from src.services.memory_orchestrator import MemoryOrchestrator
from src.services.memory_propagation_service import MemoryPropagationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_character(name: str) -> Character:
    return Character(
        id=str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        profile={"brief": f"{name}简介", "detailed": f"{name}详情"},
    )


def _make_mock_memory(
    content: str = "记忆",
    category: str | None = "major",
    is_hearsay: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        content=content,
        memory_category=category,
        character_id=uuid.uuid4(),
        world_id=uuid.uuid4(),
        is_hearsay=is_hearsay,
        origin_event_id=None,
        involved_characters=None,
    )


def _make_promotion_session() -> AsyncMock:
    """Build a session mock that handles internal EventIndexRepository queries.

    promote_long_term_memories_for_character creates EventIndexRepository(session)
    internally, so the session.execute() must return a mock with .scalars().all().
    """
    mock_session = AsyncMock()

    # Build result chain: result.scalars().all() -> []
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()

    return mock_session


# ---------------------------------------------------------------------------
# Chaos: LLM Timeout
# ---------------------------------------------------------------------------


class TestLLMTimeout:
    """Test graceful handling of LLM timeout errors."""

    async def test_generate_survives_timeout(self, caplog):
        """Short-term memory generation returns empty list on LLM timeout."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(side_effect=TimeoutError("LLM request timed out"))

        mock_memory_repo = AsyncMock()
        module = MemoryModule(llm=mock_llm, session_factory=None)

        with caplog.at_level(logging.WARNING):
            result = await module.generate_short_term_memories(
                session=AsyncMock(),
                world_id=str(uuid.uuid4()),
                char_map={"公主": _build_character("公主")},
                dialogue_text="对话",
                event_description="事件",
                memory_repo=mock_memory_repo,
            )

        assert result == []
        # memory_repo.add should never be called
        mock_memory_repo.add.assert_not_called()

    async def test_promote_survives_phase1_timeout(self, caplog):
        """Promotion returns silently when phase 1 (element selection) times out."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(side_effect=TimeoutError("Phase 1 timeout"))

        mock_memory_repo = AsyncMock()
        mock_memory_repo.get_oldest_short_term = AsyncMock(
            return_value=[_make_mock_memory("记忆1", "major")]
        )

        mock_world_repo = AsyncMock()
        mock_world_repo.get = AsyncMock(
            return_value=SimpleNamespace(
                elements=[],
                source=SimpleNamespace(title="作品", author="作者", common_sense=None),
                world_doc={},
            )
        )

        mock_relation_repo = AsyncMock()
        mock_relation_repo.list_by_world = AsyncMock(return_value=[])

        mock_char_repo = AsyncMock()
        mock_char_repo.list_by_world = AsyncMock(return_value=[])

        module = MemoryModule(llm=mock_llm, session_factory=None)

        # Should not raise
        await module.promote_long_term_memories_for_character(
            session=_make_promotion_session(),
            world_id=str(uuid.uuid4()),
            character=_build_character("角色"),
            memory_repo=mock_memory_repo,
            world_repo=mock_world_repo,
            relation_repo=mock_relation_repo,
            char_repo=mock_char_repo,
        )

    async def test_orchestrator_survives_module_timeout(self):
        """Orchestrator returns empty list when module times out."""
        mock_module = AsyncMock()
        mock_module.generate_short_term_memories = AsyncMock(side_effect=TimeoutError("timeout"))

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


# ---------------------------------------------------------------------------
# Chaos: Invalid JSON from LLM
# ---------------------------------------------------------------------------


class TestInvalidLLMOutput:
    """Test handling of malformed LLM responses."""

    async def test_llm_returns_none(self):
        """LLM returning None results in empty list."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=None)

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_llm_returns_dict_instead_of_list(self):
        """LLM returning a dict (not wrapped in known keys) results in empty list."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value={"unexpected": "structure"})

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_llm_returns_non_dict_items(self):
        """LLM returning list with non-dict items filters them out."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=["not a dict", 42, None, True])

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_llm_returns_items_with_missing_fields(self):
        """LLM items missing character or content are skipped."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(
            return_value=[
                {"content": "有内容无角色名"},  # missing character
                {"character": "角色"},  # missing content
                {"character": "", "content": ""},  # empty both
                {"character": "不存在的角色", "content": "内容"},  # char not in map
            ]
        )

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_llm_returns_empty_list(self):
        """LLM returning empty list results in empty output."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=[])

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_llm_returns_wrapped_dict(self):
        """LLM returning dict with wrapper key (e.g. 'memories') is unwrapped."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(
            return_value={
                "memories": [
                    {
                        "character": "公主",
                        "content": "我经历了大事",
                        "category": "major",
                    }
                ]
            }
        )

        mock_memory_repo = AsyncMock()

        async def fake_add(**kwargs):
            return _make_mock_memory(kwargs.get("content", ""), kwargs.get("memory_category"))

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"公主": _build_character("公主")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=mock_memory_repo,
        )
        assert len(result) == 1
        assert result[0].content == "我经历了大事"


# ---------------------------------------------------------------------------
# Chaos: Database Connection Failures
# ---------------------------------------------------------------------------


class TestDatabaseFailures:
    """Test graceful handling of database errors."""

    async def test_repo_add_raises_integrity_error(self, caplog):
        """Repository add raising DB error is handled gracefully."""
        from sqlalchemy.exc import IntegrityError

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(
            return_value=[{"character": "角色", "content": "记忆内容", "category": "major"}]
        )

        mock_memory_repo = AsyncMock()
        mock_memory_repo.add = AsyncMock(
            side_effect=IntegrityError("duplicate key", None, Exception())
        )

        module = MemoryModule(llm=mock_llm, session_factory=None)

        with caplog.at_level(logging.ERROR):
            # The function does NOT catch repo errors internally,
            # so IntegrityError should propagate. The orchestrator catches it.
            with pytest.raises(IntegrityError):
                await module.generate_short_term_memories(
                    session=AsyncMock(),
                    world_id=str(uuid.uuid4()),
                    char_map={"角色": _build_character("角色")},
                    dialogue_text="对话",
                    event_description="事件",
                    memory_repo=mock_memory_repo,
                )

    async def test_orchestrator_catches_repo_errors(self):
        """Orchestrator catches and logs repo errors."""
        from sqlalchemy.exc import OperationalError

        mock_module = AsyncMock()
        mock_module.generate_short_term_memories = AsyncMock(
            side_effect=OperationalError("connection lost", None, Exception())
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

    async def test_hearsay_write_failure_is_skipped(self, caplog):
        """Hearsay write failures are logged and skipped, not fatal."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(
            return_value=[{"character": "接收者", "content": "我听说了大事"}]
        )

        mock_memory_repo = AsyncMock()
        mock_memory_repo.add_hearsay = AsyncMock(
            side_effect=Exception("DB connection pool exhausted")
        )
        mock_memory_repo.count_hearsay = AsyncMock(return_value=0)

        mock_char_repo = AsyncMock()
        char_obj = _build_character("接收者")
        mock_char_repo.find_by_name = AsyncMock(return_value=char_obj)
        mock_char_repo.get_by_id = AsyncMock(return_value=char_obj)

        mock_relation_repo = AsyncMock()
        mock_relation_repo.list_by_world = AsyncMock(
            return_value=[
                SimpleNamespace(
                    character_a=uuid.uuid4(),
                    character_b=uuid.uuid4(),
                    type="朋友",
                )
            ]
        )

        mock_world_repo = AsyncMock()
        mock_world_repo.get = AsyncMock(
            return_value=SimpleNamespace(world_doc={"scale": "standard"})
        )

        # Patch _is_enabled to return True
        with patch("src.services.memory_propagation_service._is_enabled", return_value=True):
            source_memory = _make_mock_memory("原始记忆", "major")
            source_memory.origin_event_id = uuid.uuid4()

            # Create a mock session context manager (not async -- returns CM object)
            mock_session = AsyncMock()

            class _SessionCtx:
                async def __aenter__(self):
                    return mock_session

                async def __aexit__(self, *args):
                    pass

            propagation = MemoryPropagationService(
                llm=mock_llm,
                session_factory=lambda: _SessionCtx(),
                redis=None,
            )

            # Patch repo constructors to return our mocks
            with (
                patch(
                    "src.services.memory_propagation_service.CharacterRepository",
                    return_value=mock_char_repo,
                ),
                patch(
                    "src.services.memory_propagation_service.CharacterMemoryRepository",
                    return_value=mock_memory_repo,
                ),
                patch(
                    "src.services.memory_propagation_service.RelationRepository",
                    return_value=mock_relation_repo,
                ),
                patch(
                    "src.services.memory_propagation_service.WorldRepository",
                    return_value=mock_world_repo,
                ),
            ):
                result = await propagation.propagate_after_event_memories(
                    world_id=str(uuid.uuid4()),
                    event_id=str(uuid.uuid4()),
                    participant_names=["发送者"],
                    newly_written_memories=[source_memory],
                    virtual_time=None,
                    event_impacts=[{"severity": "high"}],
                )

        # Should return error result, not crash
        assert isinstance(result, dict)
        assert "propagated" in result or "skipped" in result


# ---------------------------------------------------------------------------
# Chaos: Concurrent Promotion
# ---------------------------------------------------------------------------


class TestConcurrentPromotion:
    """Test concurrent promotion scenarios."""

    async def test_concurrent_promote_same_character(self):
        """Multiple concurrent promotions for the same character don't corrupt state."""
        mock_llm = AsyncMock()
        # Phase 1: element selection
        # Phase 2: promotion judgment
        call_count = 0

        async def mock_complete_json(system_prompt, user_prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            # Simulate slight delay
            await asyncio.sleep(0.01)
            if "元素" in user_prompt or call_count % 2 == 1:
                return ["元素A"]
            return {"promote": []}  # No actual promotions

        mock_llm.complete_json = AsyncMock(side_effect=mock_complete_json)

        mock_memory_repo = AsyncMock()
        mock_memory_repo.get_oldest_short_term = AsyncMock(
            return_value=[_make_mock_memory(f"记忆{i}", "major") for i in range(5)]
        )
        mock_memory_repo.list_long_term_structured = AsyncMock(return_value=[])

        mock_world_repo = AsyncMock()
        mock_world_repo.get = AsyncMock(
            return_value=SimpleNamespace(
                elements=[SimpleNamespace(name="元素A", brief="简介", detailed="详情")],
                source=SimpleNamespace(title="作品", author="作者", common_sense=None),
                world_doc={},
            )
        )

        mock_relation_repo = AsyncMock()
        mock_relation_repo.list_by_world = AsyncMock(return_value=[])

        mock_char_repo = AsyncMock()
        mock_char_repo.list_by_world = AsyncMock(return_value=[])

        module = MemoryModule(llm=mock_llm, session_factory=None)
        character = _build_character("角色")

        # Run multiple promotions concurrently
        tasks = [
            module.promote_long_term_memories_for_character(
                session=_make_promotion_session(),
                world_id=str(uuid.uuid4()),
                character=character,
                memory_repo=mock_memory_repo,
                world_repo=mock_world_repo,
                relation_repo=mock_relation_repo,
                char_repo=mock_char_repo,
            )
            for _ in range(3)
        ]

        # Should not raise or corrupt state
        await asyncio.gather(*tasks)

    async def test_concurrent_generate_and_promote(self):
        """Concurrent generation and promotion don't interfere."""
        mock_llm = AsyncMock()

        async def mock_complete_json(system_prompt, user_prompt, **kwargs):
            await asyncio.sleep(0.01)
            if "记忆" in user_prompt or "对话" in user_prompt:
                return [{"character": "角色", "content": "新记忆", "category": "major"}]
            return {"promote": []}

        mock_llm.complete_json = AsyncMock(side_effect=mock_complete_json)

        mock_memory_repo = AsyncMock()

        async def fake_add(**kwargs):
            return _make_mock_memory(kwargs.get("content", ""), kwargs.get("memory_category"))

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)
        mock_memory_repo.get_oldest_short_term = AsyncMock(return_value=[])
        mock_memory_repo.list_long_term_structured = AsyncMock(return_value=[])

        mock_world_repo = AsyncMock()
        mock_world_repo.get = AsyncMock(
            return_value=SimpleNamespace(
                elements=[],
                source=SimpleNamespace(title="作品", author="作者", common_sense=None),
                world_doc={},
            )
        )

        module = MemoryModule(llm=mock_llm, session_factory=None)
        char_map = {"角色": _build_character("角色")}

        # Run generation and promotion concurrently
        gen_task = module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=mock_memory_repo,
        )
        promo_task = module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            character=char_map["角色"],
            memory_repo=mock_memory_repo,
            world_repo=mock_world_repo,
            relation_repo=AsyncMock(),
            char_repo=AsyncMock(),
        )

        gen_result, _ = await asyncio.gather(gen_task, promo_task)
        # Generation should succeed
        assert isinstance(gen_result, list)


# ---------------------------------------------------------------------------
# Chaos: Memory Pressure (Large Inputs)
# ---------------------------------------------------------------------------


class TestMemoryPressure:
    """Test behavior under memory pressure conditions."""

    async def test_large_dialogue_text(self):
        """Very large dialogue text doesn't crash generation."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=[])

        module = MemoryModule(llm=mock_llm, session_factory=None)

        # 1MB of dialogue text
        huge_text = "A" * (1024 * 1024)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text=huge_text,
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_many_characters_in_map(self):
        """Large number of characters doesn't crash generation."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=[])

        module = MemoryModule(llm=mock_llm, session_factory=None)

        # 100 characters
        char_map = {f"角色{i}": _build_character(f"角色{i}") for i in range(100)}
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map=char_map,
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_llm_returns_many_items(self):
        """LLM returning many items processes them all without crash."""
        mock_llm = AsyncMock()
        # 50 items, all valid
        items = [
            {"character": "角色", "content": f"记忆{i}", "category": "major"} for i in range(50)
        ]
        mock_llm.complete_json = AsyncMock(return_value=items)

        mock_memory_repo = AsyncMock()

        async def fake_add(**kwargs):
            return _make_mock_memory(kwargs.get("content", ""), kwargs.get("memory_category"))

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=mock_memory_repo,
        )
        # All 50 items should be processed (one character matches all)
        assert len(result) == 50

    async def test_embedding_computation_failure_is_skipped(self, caplog):
        """Embedding computation failure is logged and skipped, doesn't affect memories."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(
            return_value=[{"character": "角色", "content": "记忆内容", "category": "major"}]
        )

        mock_memory_repo = AsyncMock()

        async def fake_add(**kwargs):
            return _make_mock_memory(kwargs.get("content", ""), kwargs.get("memory_category"))

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)
        mock_memory_repo.set_embedding = AsyncMock(side_effect=Exception("embedding service down"))

        mock_embedding_provider = AsyncMock()
        mock_embedding_provider.embed = AsyncMock(
            side_effect=Exception("embedding API unavailable")
        )

        module = MemoryModule(llm=mock_llm, session_factory=None)

        with caplog.at_level(logging.WARNING):
            result = await module.generate_short_term_memories(
                session=AsyncMock(),
                world_id=str(uuid.uuid4()),
                char_map={"角色": _build_character("角色")},
                dialogue_text="对话",
                event_description="事件",
                memory_repo=mock_memory_repo,
                embedding_provider=mock_embedding_provider,
            )

        # Memory should still be returned despite embedding failure
        assert len(result) == 1
        assert result[0].content == "记忆内容"
        # Warning should be logged
        assert any("embedding" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# Chaos: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test unusual but possible edge cases."""

    async def test_empty_char_map(self):
        """Empty character map returns empty list."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value=[])
        mock_memory_repo = AsyncMock()

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=mock_memory_repo,
        )
        assert result == []

    async def test_llm_returns_items_for_unknown_characters(self):
        """Items referencing characters not in char_map are skipped."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(
            return_value=[
                {"character": "未知角色A", "content": "记忆A", "category": "major"},
                {"character": "未知角色B", "content": "记忆B", "category": "trivial"},
            ]
        )
        mock_memory_repo = AsyncMock()

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"已知角色": _build_character("已知角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=mock_memory_repo,
        )
        assert result == []

    async def test_mixed_valid_and_invalid_items(self):
        """Mix of valid and invalid LLM items: only valid ones produce memories."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(
            return_value=[
                {"character": "公主", "content": "有效记忆", "category": "major"},
                {"character": "不存在", "content": "无效", "category": "trivial"},
                {"content": "无角色名"},  # missing character
                {"character": "公主"},  # missing content
                {"character": "公主", "content": "", "category": "trivial"},  # empty content
                "not_a_dict",  # not a dict
                42,  # not a dict
                {"character": "公主", "content": "另一条有效记忆", "category": "invalid_cat"},
            ]
        )
        mock_memory_repo = AsyncMock()

        async def fake_add(**kwargs):
            return _make_mock_memory(kwargs.get("content", ""), kwargs.get("memory_category"))

        mock_memory_repo.add = AsyncMock(side_effect=fake_add)

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"公主": _build_character("公主")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=mock_memory_repo,
        )

        # Only 2 valid items: "有效记忆" (major) and "另一条有效记忆" (invalid -> None)
        assert len(result) == 2
        assert result[0].content == "有效记忆"
        assert result[0].memory_category == "major"
        assert result[1].content == "另一条有效记忆"
        assert result[1].memory_category is None  # invalid category normalized

    async def test_json_decode_error_from_llm(self):
        """LLM raising JSONDecodeError is caught and returns empty list."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(
            side_effect=json.JSONDecodeError("Expecting value", "", 0)
        )

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_connection_error_from_llm(self):
        """LLM raising ConnectionError is caught and returns empty list."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(side_effect=ConnectionError("Connection refused"))

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []

    async def test_memory_error_from_llm(self):
        """LLM raising MemoryError is caught and returns empty list."""
        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(side_effect=MemoryError("Out of memory"))

        module = MemoryModule(llm=mock_llm, session_factory=None)
        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=str(uuid.uuid4()),
            char_map={"角色": _build_character("角色")},
            dialogue_text="对话",
            event_description="事件",
            memory_repo=AsyncMock(),
        )
        assert result == []
