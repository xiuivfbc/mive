"""Tests for MemoryModule — short-term generation and long-term promotion."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.character import Character
from src.services.memory_module import MemoryModule

WORLD_ID = str(uuid.uuid4())
CHAR_A_ID = uuid.uuid4()
CHAR_B_ID = uuid.uuid4()


def _make_character(char_id: uuid.UUID = CHAR_A_ID, name: str = "Alice") -> Character:
    return Character(
        id=str(char_id),
        world_id=WORLD_ID,
        name=name,
        profile={
            "brief": f"{name}是一个勇敢的战士",
            "detailed": f"{name}出生在一个小村庄，后来成为王国骑士。",
        },
        tier="core",
    )


def _make_mem_obj(mem_id: uuid.UUID | None = None, content: str = "我经历了暴风雪"):
    mem = MagicMock()
    mem.id = mem_id or uuid.uuid4()
    mem.content = content
    return mem


def _make_world_doc():
    doc = MagicMock()
    doc.source = MagicMock()
    doc.source.title = "测试作品"
    doc.source.author = "测试作者"
    doc.source.common_sense = "这是一个魔法世界"
    elem_a = MagicMock()
    elem_a.name = "暴风雪"
    elem_a.brief = "一场罕见的暴风雪"
    elem_a.detailed = "暴风雪席卷了整个王国"
    elem_b = MagicMock()
    elem_b.name = "王城"
    elem_b.brief = "王国的首都"
    elem_b.detailed = "王城是王国的政治中心"
    doc.elements = [elem_a, elem_b]
    return doc


@pytest.fixture
def llm():
    return AsyncMock()


@pytest.fixture
def session_factory():
    sf = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    sf.return_value = mock_session
    return sf


@pytest.fixture
def memory_repo():
    repo = AsyncMock()
    repo.add = AsyncMock(side_effect=lambda **kw: _make_mem_obj(content=kw.get("content", "")))
    repo.set_embedding = AsyncMock()
    repo.get_oldest_short_term = AsyncMock(return_value=[])
    repo.list_long_term_structured = AsyncMock(return_value=[])
    repo.list_characters_needing_promotion = AsyncMock(return_value=[])
    repo.delete_by_ids = AsyncMock()
    return repo


@pytest.fixture
def world_repo():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_make_world_doc())
    return repo


@pytest.fixture
def relation_repo():
    repo = AsyncMock()
    repo.list_by_world = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def char_repo():
    repo = AsyncMock()
    char_a = _make_character(CHAR_A_ID, "Alice")
    char_b = _make_character(CHAR_B_ID, "Bob")
    repo.list_by_world = AsyncMock(return_value=[char_a, char_b])
    return repo


@pytest.fixture
def embedding_provider():
    provider = AsyncMock()
    provider.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    return provider


@pytest.fixture
def module(llm, session_factory):
    return MemoryModule(llm=llm, session_factory=session_factory)


# ── generate_short_term_memories ───────────────────────────────────────────


class TestGenerateShortTermMemories:
    @pytest.mark.asyncio
    async def test_normal_generation(self, module, llm, memory_repo, embedding_provider):
        """Normal LLM response should produce one memory per valid item."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_map = {"Alice": char_a}

        llm.complete_json = AsyncMock(
            return_value=[
                {
                    "character": "Alice",
                    "content": "我经历了暴风雪",
                    "category": "major",
                    "reflection": "这是我人生中最危险的一天",
                }
            ]
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="Alice: 我看到了暴风雪",
            event_description="暴风雪袭击了王城",
            memory_repo=memory_repo,
            embedding_provider=embedding_provider,
        )

        assert len(result) == 1
        memory_repo.add.assert_called_once()
        call_kwargs = memory_repo.add.call_args[1]
        assert call_kwargs["content"] == "我经历了暴风雪"
        assert call_kwargs["memory_category"] == "major"
        assert call_kwargs["short_term_reflection"] == "这是我人生中最危险的一天"

    @pytest.mark.asyncio
    async def test_llm_returns_empty_list(self, module, llm, memory_repo):
        """Empty list from LLM should return no memories."""
        char_map = {"Alice": _make_character(CHAR_A_ID, "Alice")}
        llm.complete_json = AsyncMock(return_value=[])

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert result == []
        memory_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_returns_dict_wrapper(self, module, llm, memory_repo):
        """LLM returning dict wrapper like {'items': [...]} should be unwrapped."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_map = {"Alice": char_a}

        llm.complete_json = AsyncMock(
            return_value={
                "items": [
                    {
                        "character": "Alice",
                        "content": "我在暴风雪中迷路了",
                        "category": "private",
                    }
                ]
            }
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert len(result) == 1
        memory_repo.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json(self, module, llm, memory_repo):
        """LLM exception should be caught, returning empty list."""
        char_map = {"Alice": _make_character(CHAR_A_ID, "Alice")}
        llm.complete_json = AsyncMock(side_effect=ValueError("Invalid JSON"))

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert result == []
        memory_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_null_content_skipped(self, module, llm, memory_repo):
        """Items with null content should be skipped."""
        char_map = {"Alice": _make_character(CHAR_A_ID, "Alice")}
        llm.complete_json = AsyncMock(
            return_value=[
                {"character": "Alice", "content": None, "category": "trivial"},
                {"character": "Alice", "content": "", "category": "trivial"},
            ]
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert result == []
        memory_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_character_skipped(self, module, llm, memory_repo):
        """Items for characters not in char_map should be skipped."""
        char_map = {"Alice": _make_character(CHAR_A_ID, "Alice")}
        llm.complete_json = AsyncMock(
            return_value=[
                {"character": "UnknownChar", "content": "一些内容", "category": "major"},
            ]
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert result == []
        memory_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_category_normalized(self, module, llm, memory_repo):
        """Invalid category values should be normalized to None."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_map = {"Alice": char_a}
        llm.complete_json = AsyncMock(
            return_value=[
                {"character": "Alice", "content": "内容", "category": "invalid_cat"},
            ]
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert len(result) == 1
        call_kwargs = memory_repo.add.call_args[1]
        assert call_kwargs["memory_category"] is None

    @pytest.mark.asyncio
    async def test_multiple_characters(self, module, llm, memory_repo):
        """Multiple characters should each get their own memory."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_b = _make_character(CHAR_B_ID, "Bob")
        char_map = {"Alice": char_a, "Bob": char_b}

        llm.complete_json = AsyncMock(
            return_value=[
                {"character": "Alice", "content": "我见到了暴风雪", "category": "major"},
                {"character": "Bob", "content": "我听到了雷声", "category": "private"},
            ]
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert len(result) == 2
        assert memory_repo.add.call_count == 2

    @pytest.mark.asyncio
    async def test_reflection_whitespace_normalized(self, module, llm, memory_repo):
        """Whitespace-only reflection should be normalized to None."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_map = {"Alice": char_a}
        llm.complete_json = AsyncMock(
            return_value=[
                {
                    "character": "Alice",
                    "content": "内容",
                    "category": "major",
                    "reflection": "   ",
                },
            ]
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert len(result) == 1
        call_kwargs = memory_repo.add.call_args[1]
        assert call_kwargs["short_term_reflection"] is None

    @pytest.mark.asyncio
    async def test_embedding_provider_none_skips_embedding(self, module, llm, memory_repo):
        """When embedding_provider is None, embeddings should not be computed."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_map = {"Alice": char_a}
        llm.complete_json = AsyncMock(
            return_value=[
                {"character": "Alice", "content": "内容", "category": "major"},
            ]
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
            embedding_provider=None,
        )

        assert len(result) == 1
        memory_repo.set_embedding.assert_not_called()

    @pytest.mark.asyncio
    async def test_embedding_computed_for_new_memories(
        self, module, llm, memory_repo, embedding_provider
    ):
        """When embedding_provider is provided, embeddings should be computed and stored."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_map = {"Alice": char_a}
        llm.complete_json = AsyncMock(
            return_value=[
                {"character": "Alice", "content": "内容", "category": "major"},
            ]
        )

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
            embedding_provider=embedding_provider,
        )

        assert len(result) == 1
        embedding_provider.embed.assert_called_once()
        memory_repo.set_embedding.assert_called_once()

    @pytest.mark.asyncio
    async def test_embedding_failure_does_not_raise(
        self, module, llm, memory_repo, embedding_provider
    ):
        """Embedding failure should be caught, not raised."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_map = {"Alice": char_a}
        llm.complete_json = AsyncMock(
            return_value=[
                {"character": "Alice", "content": "内容", "category": "major"},
            ]
        )
        embedding_provider.embed = AsyncMock(side_effect=RuntimeError("Embedding error"))

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
            embedding_provider=embedding_provider,
        )

        assert len(result) == 1
        memory_repo.set_embedding.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_returns_none(self, module, llm, memory_repo):
        """When LLM returns None (caught exception), should return empty."""
        char_map = {"Alice": _make_character(CHAR_A_ID, "Alice")}
        # Simulate: exception is caught, result set to None
        llm.complete_json = AsyncMock(side_effect=RuntimeError("LLM error"))

        result = await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_session_id_passed_to_repo(self, module, llm, memory_repo):
        """session_id should be forwarded to memory_repo.add."""
        char_a = _make_character(CHAR_A_ID, "Alice")
        char_map = {"Alice": char_a}
        llm.complete_json = AsyncMock(
            return_value=[
                {"character": "Alice", "content": "内容", "category": "major"},
            ]
        )
        sid = uuid.uuid4()

        await module.generate_short_term_memories(
            session=AsyncMock(),
            world_id=WORLD_ID,
            char_map=char_map,
            dialogue_text="对话内容",
            event_description="事件描述",
            memory_repo=memory_repo,
            session_id=sid,
        )

        call_kwargs = memory_repo.add.call_args[1]
        assert call_kwargs["session_id"] == sid


# ── promote_long_term_memories_for_character ────────────────────────────────


class TestPromoteLongTermMemories:
    @pytest.fixture
    def mock_patches(self, memory_repo, world_repo, relation_repo, char_repo):
        """Set up patches for repos created inside the method."""
        mock_event_index_repo = AsyncMock()
        mock_event_index_repo.list_by_world = AsyncMock(return_value=[])
        mock_event_index_repo.add = AsyncMock(side_effect=lambda **kw: MagicMock(id=uuid.uuid4()))

        def _format_event_index(lst):
            return "暂无事件索引"

        with (
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=mock_event_index_repo,
            ),
            patch(
                "src.utils.memory_format.format_event_index_for_injection",
                side_effect=_format_event_index,
            ),
            patch(
                "src.utils.character_name_cache.get_character_names",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            yield mock_event_index_repo

    @pytest.mark.asyncio
    async def test_normal_promotion(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """Normal two-phase promotion should write long-term memories."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="我经历了暴风雪")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        # Phase 1: select elements
        phase1_result = ["暴风雪"]
        # Phase 2: promote decision
        phase2_result = {
            "promote": [
                {
                    "event_name": "暴风雪事件",
                    "event_code": "new",
                    "event_brief": "暴风雪袭击了王城",
                    "perspective_detail": "我在暴风雪中艰难前行",
                    "reflection": "这是我经历过的最可怕的事",
                    "involved_characters": ["C1"],
                }
            ]
        }

        llm.complete_json = AsyncMock(side_effect=[phase1_result, phase2_result])

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        assert llm.complete_json.call_count == 2
        memory_repo.add_structured_long_term.assert_called_once()
        memory_repo.delete_by_ids.assert_called_once()

    @pytest.mark.asyncio
    async def test_trivial_memories_excluded(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """Trivial memories should not be promoted (filtered at query level)."""
        character = _make_character(CHAR_A_ID, "Alice")
        # get_oldest_short_term returns empty (trivial filtered out)
        memory_repo.get_oldest_short_term = AsyncMock(return_value=[])

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        # Should return early without LLM calls
        llm.complete_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_two_phase_flow(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """Phase 1 selects elements, Phase 2 judges promotion using selected elements."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆1"), _make_mem_obj(content="记忆2")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        # Phase 1 returns element names
        phase1_result = ["暴风雪", "王城"]
        # Phase 2: no promotion this time
        phase2_result = {"promote": []}

        llm.complete_json = AsyncMock(side_effect=[phase1_result, phase2_result])

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        assert llm.complete_json.call_count == 2
        # No promotion, so no delete
        memory_repo.delete_by_ids.assert_not_called()
        memory_repo.add_structured_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_world_doc_none_returns_early(
        self, module, llm, memory_repo, relation_repo, char_repo, mock_patches
    ):
        """When world_doc is None, should return without LLM calls."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        world_repo_none = AsyncMock()
        world_repo_none.get = AsyncMock(return_value=None)

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo_none,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        llm.complete_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_phase1_llm_failure_returns_early(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """When Phase 1 LLM fails, should return without calling Phase 2."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        llm.complete_json = AsyncMock(side_effect=RuntimeError("LLM error"))

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        # Only Phase 1 was attempted
        assert llm.complete_json.call_count == 1
        memory_repo.add_structured_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_phase2_llm_failure_returns_early(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """When Phase 2 LLM fails, should return without writing long-term memories."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        # Phase 1 succeeds, Phase 2 raises
        llm.complete_json = AsyncMock(side_effect=[["暴风雪"], RuntimeError("LLM error")])

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        assert llm.complete_json.call_count == 2
        memory_repo.add_structured_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_phase2_returns_list_instead_of_dict(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """When Phase 2 returns a list instead of dict, should return without writing."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        llm.complete_json = AsyncMock(side_effect=[["暴风雪"], ["unexpected", "list"]])

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        memory_repo.add_structured_long_term.assert_not_called()
        memory_repo.delete_by_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_short_term_memories_returns_early(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """When there are no short-term memories, should return without LLM calls."""
        character = _make_character(CHAR_A_ID, "Alice")
        memory_repo.get_oldest_short_term = AsyncMock(return_value=[])

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        llm.complete_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_index_matching(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo
    ):
        """When phase 2 references an existing event code, it should match by ID."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        existing_event = MagicMock()
        existing_event.id = uuid.uuid4()
        existing_event.event_name = "旧事件"

        mock_event_index_repo = AsyncMock()
        mock_event_index_repo.list_by_world = AsyncMock(return_value=[existing_event])
        mock_event_index_repo.add = AsyncMock(side_effect=lambda **kw: MagicMock(id=uuid.uuid4()))

        with (
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=mock_event_index_repo,
            ),
            patch(
                "src.utils.memory_format.format_event_index_for_injection",
                return_value="E001: 旧事件",
            ),
            patch(
                "src.utils.character_name_cache.get_character_names",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            phase1_result = ["暴风雪"]
            phase2_result = {
                "promote": [
                    {
                        "event_name": "旧事件",
                        "event_code": "E001",
                        "perspective_detail": "我在旧事件中受伤了",
                        "reflection": None,
                        "involved_characters": [],
                    }
                ]
            }
            llm.complete_json = AsyncMock(side_effect=[phase1_result, phase2_result])

            await module.promote_long_term_memories_for_character(
                session=AsyncMock(),
                world_id=WORLD_ID,
                character=character,
                memory_repo=memory_repo,
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )

            # Should use existing event ID, not create a new one
            mock_event_index_repo.add.assert_not_called()
            memory_repo.add_structured_long_term.assert_called_once()
            call_kwargs = memory_repo.add_structured_long_term.call_args[1]
            assert call_kwargs["event_name"] == str(existing_event.id)

    @pytest.mark.asyncio
    async def test_promotion_creates_new_event_when_no_match(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo
    ):
        """When phase 2 event_code doesn't match, should create a new event index entry."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        new_event_id = uuid.uuid4()
        mock_event_index_repo = AsyncMock()
        mock_event_index_repo.list_by_world = AsyncMock(return_value=[])
        mock_event_index_repo.add = AsyncMock(return_value=MagicMock(id=new_event_id))

        with (
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=mock_event_index_repo,
            ),
            patch(
                "src.utils.memory_format.format_event_index_for_injection",
                return_value="暂无事件索引",
            ),
            patch(
                "src.utils.character_name_cache.get_character_names",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            phase1_result = ["暴风雪"]
            phase2_result = {
                "promote": [
                    {
                        "event_name": "新事件",
                        "event_code": "new",
                        "event_brief": "新事件简介",
                        "perspective_detail": "我在新事件中",
                        "reflection": None,
                        "involved_characters": [],
                    }
                ]
            }
            llm.complete_json = AsyncMock(side_effect=[phase1_result, phase2_result])

            await module.promote_long_term_memories_for_character(
                session=AsyncMock(),
                world_id=WORLD_ID,
                character=character,
                memory_repo=memory_repo,
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )

            mock_event_index_repo.add.assert_called_once()
            memory_repo.add_structured_long_term.assert_called_once()
            call_kwargs = memory_repo.add_structured_long_term.call_args[1]
            assert call_kwargs["event_name"] == str(new_event_id)

    @pytest.mark.asyncio
    async def test_empty_promote_list_no_delete(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """When promote list is empty, should not delete short-term memories."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        llm.complete_json = AsyncMock(side_effect=[["暴风雪"], {"promote": []}])

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        memory_repo.delete_by_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_promote_item_skipped(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo, mock_patches
    ):
        """Non-dict items in promote list should be skipped."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        llm.complete_json = AsyncMock(
            side_effect=[
                ["暴风雪"],
                {"promote": ["not_a_dict", 42, {"event_name": "", "perspective_detail": ""}]},
            ]
        )

        await module.promote_long_term_memories_for_character(
            session=AsyncMock(),
            world_id=WORLD_ID,
            character=character,
            memory_repo=memory_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
            char_repo=char_repo,
        )

        memory_repo.add_structured_long_term.assert_not_called()
        memory_repo.delete_by_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_involved_characters_code_mapping(
        self, module, llm, memory_repo, world_repo, relation_repo, char_repo
    ):
        """Character codes (C1, C2) in involved_characters should be mapped to UUIDs."""
        character = _make_character(CHAR_A_ID, "Alice")
        short_term = [_make_mem_obj(content="记忆")]
        memory_repo.get_oldest_short_term = AsyncMock(return_value=short_term)

        mock_event_index_repo = AsyncMock()
        mock_event_index_repo.list_by_world = AsyncMock(return_value=[])
        mock_event_index_repo.add = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

        with (
            patch(
                "src.db.repositories.event_index_repo.EventIndexRepository",
                return_value=mock_event_index_repo,
            ),
            patch(
                "src.utils.memory_format.format_event_index_for_injection",
                return_value="暂无事件索引",
            ),
            patch(
                "src.utils.character_name_cache.get_character_names",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            # char_repo.list_by_world returns [Alice(C1), Bob(C2)]
            phase1_result = ["暴风雪"]
            phase2_result = {
                "promote": [
                    {
                        "event_name": "事件",
                        "event_code": "new",
                        "event_brief": "简介",
                        "perspective_detail": "详情",
                        "reflection": None,
                        "involved_characters": ["C1", "C2"],
                    }
                ]
            }
            llm.complete_json = AsyncMock(side_effect=[phase1_result, phase2_result])

            await module.promote_long_term_memories_for_character(
                session=AsyncMock(),
                world_id=WORLD_ID,
                character=character,
                memory_repo=memory_repo,
                world_repo=world_repo,
                relation_repo=relation_repo,
                char_repo=char_repo,
            )

            memory_repo.add_structured_long_term.assert_called_once()
            call_kwargs = memory_repo.add_structured_long_term.call_args[1]
            involved = call_kwargs["involved_characters"]
            assert len(involved) == 2
            assert str(CHAR_A_ID) in involved
            assert str(CHAR_B_ID) in involved
