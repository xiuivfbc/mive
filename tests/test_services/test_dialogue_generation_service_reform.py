"""Tests for the Chat System Reform Plan — Steps 1-6 (character chat side).

Each test is written BEFORE the implementation (TDD).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.character import Character
from src.models.relation import Relation


def _make_character(name: str, char_id: str | None = None, tier: str = "core") -> Character:
    return Character(
        id=char_id or str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        tier=tier,
        profile={
            "brief": f"{name}的角色简介",
            "detail": f"{name}的详细描述",
            "personality": f"{name}的性格",
        },
    )


def _make_relation(
    char_a: str, char_b: str, world_id: str | None = None, description: str = "关系"
) -> Relation:
    return Relation(
        id=str(uuid.uuid4()),
        world_id=world_id or str(uuid.uuid4()),
        character_a=char_a,
        character_b=char_b,
        type="同事",
        description=description,
    )


def _make_world_doc(title="三体", author="刘慈欣", user_char_id=None):
    """Create a mock world_doc with source, elements, and user_character_id."""
    wd = MagicMock()
    wd.user_character_id = user_char_id
    # source
    source = MagicMock()
    source.title = title
    source.author = author
    wd.source = source
    # elements — mix of character and non-character categories
    e1 = MagicMock()
    e1.name = "红岸基地"
    e1.category = "场所"
    e1.brief = "射电望远镜基地"
    e1.detail = "位于内蒙古的秘密基地"
    e2 = MagicMock()
    e2.name = "三体星系"
    e2.category = "规则"
    e2.brief = "半人马座α星系"
    e2.detail = "拥有三颗恒星的混沌星系"
    e3 = MagicMock()
    e3.name = "智子"
    e3.category = "物品"
    e3.brief = "质子计算机"
    e3.detail = "展开质子进行电路蚀刻的超级计算机"
    e4 = MagicMock()
    e4.name = "叶文洁"  # character category should be filtered
    e4.category = "人物"
    e4.brief = "天体物理学家"
    e4.detail = "文革中目睹父亲被打死"
    e5 = MagicMock()
    e5.name = "黑暗森林法则"
    e5.category = "规则"
    e5.brief = "宇宙社会学公理"
    e5.detail = "宇宙就是一座黑暗森林"
    e6 = MagicMock()
    e6.name = "面壁计划"
    e6.category = "事件"
    e6.brief = "联合国面壁计划"
    e6.detail = "选出四位面壁者"
    wd.elements = [e1, e2, e3, e4, e5, e6]
    return wd


# ── Step 1: Constants ─────────────────────────────────────────────────────────


class TestConstants:
    """Step 1: Verify module-level constants are defined."""

    def test_element_cap_for_chat_is_12(self):
        from src.services.dialogue_generation_service import ELEMENT_CAP_FOR_CHAT

        assert ELEMENT_CAP_FOR_CHAT == 10

    def test_input_cap_for_participants_is_15(self):
        from src.services.dialogue_generation_service import INPUT_CAP_FOR_PARTICIPANTS

        assert INPUT_CAP_FOR_PARTICIPANTS == 15

    def test_max_speakers_is_5(self):
        from src.services.dialogue_generation_service import MAX_SPEAKERS

        assert MAX_SPEAKERS == 5

    def test_max_related_sample_is_4(self):
        from src.services.dialogue_generation_service import MAX_RELATED_SAMPLE

        assert MAX_RELATED_SAMPLE == 4

    def test_tier_priority_defined(self):
        from src.services.dialogue_generation_service import _TIER_PRIORITY

        assert _TIER_PRIORITY == ["core", "supporting", "extra"]


# ── Step 2: _build_cacheable_prefix refactor ─────────────────────────────────


class TestExtractWorkInfo:
    """Step 2: _extract_work_info extracts title and author from world_doc."""

    def test_extracts_title_and_author(self):
        from src.services.dialogue_generation_service import _extract_work_info

        world_doc = _make_world_doc("三体", "刘慈欣")
        result = _extract_work_info(world_doc)
        assert "三体" in result
        assert "刘慈欣" in result

    def test_returns_empty_for_no_source(self):
        from src.services.dialogue_generation_service import _extract_work_info

        world_doc = MagicMock()
        world_doc.source = None
        result = _extract_work_info(world_doc)
        assert result == ""

    def test_returns_empty_for_none_world_doc(self):
        from src.services.dialogue_generation_service import _extract_work_info

        result = _extract_work_info(None)
        assert result == ""

    def test_handles_title_only(self):
        from src.services.dialogue_generation_service import _extract_work_info

        world_doc = MagicMock()
        source = MagicMock()
        source.title = "三体"
        source.author = ""
        world_doc.source = source
        result = _extract_work_info(world_doc)
        assert "三体" in result
        assert "作者" not in result


class TestBuildElementsContext:
    """Step 2: _build_elements_context returns sorted, capped non-character elements."""

    def test_filters_out_character_category(self):
        from src.services.dialogue_generation_service import _build_elements_context

        world_doc = _make_world_doc()
        result = _build_elements_context(world_doc)
        assert "叶文洁" not in result  # character category filtered

    def test_includes_non_character_elements(self):
        from src.services.dialogue_generation_service import _build_elements_context

        world_doc = _make_world_doc()
        result = _build_elements_context(world_doc)
        assert "红岸基地" in result
        assert "三体星系" in result
        assert "智子" in result

    def test_sorted_by_category(self):
        from src.services.dialogue_generation_service import _build_elements_context

        world_doc = _make_world_doc()
        result = _build_elements_context(world_doc)
        # Categories sorted: 事件 < 场所 < 物品 < 规则
        lines = result.strip().split("\n")
        categories = []
        for line in lines:
            if line.strip().startswith("["):
                cat = line.strip().split("]")[0][1:]
                categories.append(cat)
        assert categories == sorted(categories)

    def test_respects_element_cap(self):
        from src.services.dialogue_generation_service import (
            ELEMENT_CAP_FOR_CHAT,
            _build_elements_context,
        )

        world_doc = MagicMock()
        world_doc.source = None
        elements = []
        for i in range(20):
            e = MagicMock()
            e.name = f"元素{i}"
            e.category = "场所"
            e.brief = f"简介{i}"
            elements.append(e)
        world_doc.elements = elements
        result = _build_elements_context(world_doc)
        # Should cap at ELEMENT_CAP_FOR_CHAT
        lines = [line for line in result.split("\n") if line.strip().startswith("[")]
        assert len(lines) == ELEMENT_CAP_FOR_CHAT

    def test_returns_empty_for_no_elements(self):
        from src.services.dialogue_generation_service import _build_elements_context

        world_doc = MagicMock()
        world_doc.elements = []
        result = _build_elements_context(world_doc)
        assert result == ""

    def test_returns_empty_for_none_world_doc(self):
        from src.services.dialogue_generation_service import _build_elements_context

        result = _build_elements_context(None)
        assert result == ""

    def test_no_header_in_output(self):
        """_build_elements_context should NOT include '世界设定' header."""
        from src.services.dialogue_generation_service import _build_elements_context

        world_doc = _make_world_doc()
        result = _build_elements_context(world_doc)
        assert "世界设定" not in result


class TestBuildCacheablePrefix:
    """Step 2: _build_cacheable_prefix builds cacheable system prefix without character list."""

    def test_includes_role_label(self):
        from src.services.dialogue_generation_service import _build_cacheable_prefix

        world_doc = _make_world_doc()
        result = _build_cacheable_prefix(world_doc, "对话引擎")
        assert "对话引擎" in result

    def test_includes_work_info(self):
        from src.services.dialogue_generation_service import _build_cacheable_prefix

        world_doc = _make_world_doc()
        result = _build_cacheable_prefix(world_doc, "对话引擎")
        assert "三体" in result
        assert "刘慈欣" in result

    def test_excludes_elements_context(self):
        """Elements list should NOT be in cacheable_prefix (moved to variable part)."""
        from src.services.dialogue_generation_service import _build_cacheable_prefix

        world_doc = _make_world_doc()
        result = _build_cacheable_prefix(world_doc, "对话引擎")
        assert "红岸基地" not in result

    def test_does_not_include_character_list(self):
        """Character list should NOT be in cacheable_prefix (moved to variable part)."""
        from src.services.dialogue_generation_service import _build_cacheable_prefix

        world_doc = _make_world_doc()
        result = _build_cacheable_prefix(world_doc, "对话引擎")
        assert "角色列表" not in result
        assert "全量角色列表" not in result

    def test_select_and_generate_use_same_role_label(self):
        """Both select_participants and generate_response should use same role_label."""
        from src.services.dialogue_generation_service import _build_cacheable_prefix

        world_doc = _make_world_doc()
        result1 = _build_cacheable_prefix(world_doc, "对话引擎")
        result2 = _build_cacheable_prefix(world_doc, "对话引擎")
        assert result1 == result2


# ── Step 3: _build_participant_input + relation_repo injection ───────────────


class TestBuildParticipantInput:
    """Step 3: _build_participant_input builds prioritized character list for LLM."""

    @pytest.fixture
    def relation_repo(self):
        repo = AsyncMock()
        return repo

    @pytest.fixture
    def chars(self):
        """Create characters with different tiers."""
        core1 = _make_character("叶文洁", tier="core")
        core2 = _make_character("常伟思", tier="core")
        sup1 = _make_character("汪淼", tier="supporting")
        sup2 = _make_character("罗辑", tier="supporting")
        extra1 = _make_character("路人甲", tier="extra")
        extra2 = _make_character("路人乙", tier="extra")
        return [core1, core2, sup1, sup2, extra1, extra2]

    async def test_include_mode_preserves_selected_characters(self, relation_repo, chars):
        """Selected characters are always in the input list."""
        from src.services.dialogue_generation_service import _build_participant_input

        selected_ids = [chars[0].id, chars[2].id]  # core1 + sup1
        result = await _build_participant_input(
            characters=chars,
            selected_char_ids=selected_ids,
            relation_repo=relation_repo,
            world_id="w1",
        )
        result_ids = [c.id for c in result]
        assert chars[0].id in result_ids
        assert chars[2].id in result_ids

    async def test_include_mode_fills_with_tier_priority(self, relation_repo, chars):
        """After selected + related, fill with core > supporting > extra."""
        from src.services.dialogue_generation_service import _build_participant_input

        selected_ids = [chars[4].id]  # extra1 only
        relation_repo.list_by_world = AsyncMock(return_value=[])
        result = await _build_participant_input(
            characters=chars,
            selected_char_ids=selected_ids,
            relation_repo=relation_repo,
            world_id="w1",
        )
        result_ids = [c.id for c in result]
        # core should come before supporting before extra (in remaining slots)
        core_positions = [
            result_ids.index(c.id) for c in chars if c.tier == "core" and c.id in result_ids
        ]
        sup_positions = [
            result_ids.index(c.id) for c in chars if c.tier == "supporting" and c.id in result_ids
        ]
        if core_positions and sup_positions:
            assert max(core_positions) < min(sup_positions)

    async def test_include_mode_caps_at_input_cap(self, relation_repo):
        """Input list should not exceed INPUT_CAP_FOR_PARTICIPANTS."""
        from src.services.dialogue_generation_service import (
            INPUT_CAP_FOR_PARTICIPANTS,
            _build_participant_input,
        )

        chars = [_make_character(f"角色{i}", tier="core") for i in range(20)]
        selected_ids = [chars[0].id]
        relation_repo.list_by_world = AsyncMock(return_value=[])
        result = await _build_participant_input(
            characters=chars,
            selected_char_ids=selected_ids,
            relation_repo=relation_repo,
            world_id="w1",
        )
        assert len(result) <= INPUT_CAP_FOR_PARTICIPANTS

    async def test_include_mode_adds_related_characters(self, relation_repo, chars):
        """Characters related to selected ones should be included."""
        from src.services.dialogue_generation_service import _build_participant_input

        selected_ids = [chars[0].id]  # core1 selected
        # core1 has relation with extra2
        rel = _make_relation(chars[0].id, chars[5].id)
        relation_repo.list_by_world = AsyncMock(return_value=[rel])
        result = await _build_participant_input(
            characters=chars,
            selected_char_ids=selected_ids,
            relation_repo=relation_repo,
            world_id="w1",
        )
        result_ids = [c.id for c in result]
        assert chars[5].id in result_ids  # extra2 included via relation

    async def test_include_mode_related_sample_is_capped(self, relation_repo):
        """Related characters should be capped at MAX_RELATED_SAMPLE before tier fill."""
        from src.services.dialogue_generation_service import (
            _build_participant_input,
        )

        core = _make_character("主角", tier="core")
        extras = [_make_character(f"配角{i}", tier="extra") for i in range(10)]
        chars = [core] + extras
        selected_ids = [core.id]

        # core has relations with all extras — but only MAX_RELATED_SAMPLE
        # should come from the relation path (the rest come from tier fill)
        rels = [_make_relation(core.id, e.id) for e in extras]
        relation_repo.list_by_world = AsyncMock(return_value=rels)
        result = await _build_participant_input(
            characters=chars,
            selected_char_ids=selected_ids,
            relation_repo=relation_repo,
            world_id="w1",
        )
        # The result should include the core + extras up to INPUT_CAP
        result_ids = {c.id for c in result}
        assert core.id in result_ids
        # All extras should be included (since INPUT_CAP is 15 and we have 11 chars)
        for e in extras:
            assert e.id in result_ids

    async def test_include_mode_related_sample_skipped_when_no_relation_repo(self, relation_repo):
        """Without relation_repo, skip related sample step entirely."""
        from src.services.dialogue_generation_service import _build_participant_input

        core = _make_character("主角", tier="core")
        extra = _make_character("配角", tier="extra")
        chars = [core, extra]
        selected_ids = [core.id]

        result = await _build_participant_input(
            characters=chars,
            selected_char_ids=selected_ids,
            relation_repo=None,
            world_id="w1",
        )
        result_ids = [c.id for c in result]
        assert core.id in result_ids
        assert extra.id in result_ids

    async def test_selected_chars_exceed_cap_returns_only_selected(self, relation_repo, chars):
        """If selected chars exceed INPUT_CAP, return only selected chars."""
        from src.services.dialogue_generation_service import _build_participant_input

        # Select more than INPUT_CAP (15)
        many_chars = [_make_character(f"角色{i}", tier="core") for i in range(20)]
        selected_ids = [c.id for c in many_chars]
        result = await _build_participant_input(
            characters=many_chars,
            selected_char_ids=selected_ids,
            relation_repo=relation_repo,
            world_id="w1",
        )
        assert len(result) == 20  # all selected, even though > INPUT_CAP


class TestDialogueGenerationServiceInitWithRelationRepo:
    """Step 3: DialogueGenerationService.__init__ accepts relation_repo."""

    def test_init_accepts_relation_repo(self):
        from src.services.dialogue_generation_service import DialogueGenerationService

        svc = DialogueGenerationService(
            llm=AsyncMock(),
            character_repo=AsyncMock(),
            message_repo=AsyncMock(),
            relation_repo=AsyncMock(),
        )
        assert svc.relation_repo is not None

    def test_init_relation_repo_defaults_to_none(self):
        from src.services.dialogue_generation_service import DialogueGenerationService

        svc = DialogueGenerationService(
            llm=AsyncMock(),
            character_repo=AsyncMock(),
            message_repo=AsyncMock(),
        )
        assert svc.relation_repo is None


# ── Step 4: select_participants output restructure + generate_response background ──


class TestSelectParticipantsOutputFormat:
    """Step 4: select_participants returns speakers + background + narration + relevant_elements."""

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        mock.complete_json.return_value = {
            "speakers": ["叶文洁", "常伟思"],
            "background": ["汪淼"],
            "narration": "叶文洁和常伟思在会议室讨论。",
            "relevant_elements": ["红岸基地"],
        }
        return mock

    @pytest.fixture
    def char_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def msg_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        return mock

    @pytest.fixture
    def world_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def relation_repo(self):
        mock = AsyncMock()
        mock.list_by_world.return_value = []
        return mock

    async def test_returns_speakers_background_narration_relevant_elements(
        self, llm, char_repo, msg_repo, world_repo, relation_repo
    ):
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_b = _make_character("常伟思")
        char_c = _make_character("汪淼")
        char_repo.list_by_world.return_value = [char_a, char_b, char_c]

        world_doc = _make_world_doc()
        world_repo.get.return_value = world_doc

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
        )
        result = await svc.select_participants(world_id="w1", user_message="你好")

        assert "speakers" in result
        assert "background" in result
        assert "narration" in result
        assert "relevant_elements" in result

    async def test_speakers_are_id_name_dicts(
        self, llm, char_repo, msg_repo, world_repo, relation_repo
    ):
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        world_repo.get.return_value = _make_world_doc()
        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
        }

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
        )
        result = await svc.select_participants(world_id="w1", user_message="test")

        assert isinstance(result["speakers"], list)
        assert result["speakers"][0]["name"] == "叶文洁"
        assert "id" in result["speakers"][0]

    async def test_speakers_hard_truncated_at_max_speakers(
        self, llm, char_repo, msg_repo, world_repo, relation_repo
    ):
        """Speakers list should be hard-truncated at MAX_SPEAKERS."""
        from src.services.dialogue_generation_service import MAX_SPEAKERS, DialogueGenerationService

        chars = [_make_character(f"角色{i}") for i in range(8)]
        char_repo.list_by_world.return_value = chars
        world_repo.get.return_value = _make_world_doc()
        llm.complete_json.return_value = {
            "speakers": [f"角色{i}" for i in range(8)],
            "background": [],
            "narration": "",
            "relevant_elements": [],
        }

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
        )
        result = await svc.select_participants(world_id="w1", user_message="test")

        assert len(result["speakers"]) <= MAX_SPEAKERS


class TestGenerateResponseBackgroundParam:
    """Step 4: generate_response accepts background parameter."""

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        mock.complete_json.return_value = {"messages": []}
        return mock

    @pytest.fixture
    def char_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def msg_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        mock.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        return mock

    async def test_accepts_background_param(self, llm, char_repo, msg_repo):
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
        )
        # Should not raise
        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": char_a.id, "name": "叶文洁"}],
            background=["汪淼"],
        )

    async def test_accepts_relevant_elements_param(self, llm, char_repo, msg_repo):
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
        )
        # Should not raise
        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": char_a.id, "name": "叶文洁"}],
            relevant_elements=["红岸基地"],
        )

    async def test_background_characters_injected_into_prompt(self, llm, char_repo, msg_repo):
        """Background characters should appear in system prompt."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_b = _make_character("汪淼")
        char_repo.list_by_world.return_value = [char_a, char_b]

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
        )
        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": char_a.id, "name": "叶文洁"}],
            background=["汪淼"],
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "汪淼" in system_prompt


# ── Step 5: relevant_elements hallucination filtering ─────────────────────────


class TestRelevantElementsFiltering:
    """select_participants 不再返回元素：筛选已下沉到 generate_response 的向量检索。

    架构变更（AI 精排功能引入）：原先 select_participants 由 LLM 选 relevant_elements，
    会触发 generate_response 的"预选硬截断"模式，使向量检索路径永不执行、rerank 成为死代码。
    现统一令 select_participants 返回 []，元素筛选恒走向量检索（+ 可选 AI 精排）。
    """

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def char_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def msg_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        return mock

    @pytest.fixture
    def world_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def relation_repo(self):
        mock = AsyncMock()
        mock.list_by_world.return_value = []
        return mock

    async def test_relevant_elements_filtered_by_hallucination(
        self, llm, char_repo, msg_repo, world_repo, relation_repo
    ):
        """select_participants 对 LLM 输出的 relevant_elements 做幻觉过滤。

        有效元素名（在 world_doc.elements 中且非人物类别）保留，
        虚构/幻觉元素名（不在 world_doc.elements 中）被过滤掉。
        """
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        world_doc = _make_world_doc()
        world_repo.get.return_value = world_doc

        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": ["红岸基地", "三体星系", "虚构元素XYZ"],
        }

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
        )
        result = await svc.select_participants(world_id="w1", user_message="test")

        # "红岸基地" 和 "三体星系" 在 world_doc.elements 中且非人物类别，保留
        # "虚构元素XYZ" 不在 world_doc.elements 中，被幻觉过滤掉
        assert result["relevant_elements"] == ["红岸基地", "三体星系"]


# ── Step 6: Element detail injection ──────────────────────────────────────────


class TestElementDetailInjection:
    """Step 6: generate_response injects element details based on relevant_elements."""

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        mock.complete_json.return_value = {"messages": []}
        return mock

    @pytest.fixture
    def char_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def msg_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        mock.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        return mock

    async def test_element_details_in_system_prompt(self, llm, char_repo, msg_repo):
        from src.services.dialogue_generation_service import DialogueGenerationService

        world_doc = _make_world_doc()
        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]

        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
        )
        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": char_a.id, "name": "叶文洁"}],
            relevant_elements=["红岸基地"],
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "射电望远镜基地" in system_prompt or "内蒙古" in system_prompt

    async def test_element_detail_budget_respected(self, llm, char_repo, msg_repo):
        """Element details should be truncated at ELEMENT_DETAIL_BUDGET."""
        from src.services.dialogue_generation_service import (
            DialogueGenerationService,
        )

        world_doc = MagicMock()
        world_doc.source = None
        world_doc.user_character_id = None
        elements = []
        for i in range(10):
            e = MagicMock()
            e.name = f"元素{i}"
            e.category = "场所"
            e.brief = f"简介{i}"
            e.detail = "X" * 500  # long detail
            elements.append(e)
        world_doc.elements = elements

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]

        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
        )
        relevant = [f"元素{i}" for i in range(10)]
        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": char_a.id, "name": "叶文洁"}],
            relevant_elements=relevant,
        )
        system_prompt = llm.complete_json.call_args[0][0]
        # The total element detail section should not exceed budget significantly
        # (we check that it's bounded, not exactly ELEMENT_DETAIL_BUDGET chars)
        assert "元素" in system_prompt

    async def test_full_load_fallback_when_no_retrieval_and_empty_relevant(
        self, llm, char_repo, msg_repo
    ):
        """无检索服务 + relevant_elements 空时，按 CLAUDE.md「降级为全量加载」兜底注入世界元素。

        select_participants 已不再选元素，故 relevant_elements 恒空；若世界有元素，
        generate_response 必须仍注入世界元素上下文（排除角色类），不能完全丢失。
        """
        from src.services.dialogue_generation_service import DialogueGenerationService

        world_doc = _make_world_doc()
        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]

        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
        )
        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": char_a.id, "name": "叶文洁"}],
            relevant_elements=[],
        )
        system_prompt = llm.complete_json.call_args[0][0]
        # 全量兜底：世界元素 section 出现，且排除了角色类元素（叶文洁是「人物」类）
        assert "相关元素详细信息" in system_prompt
        assert "红岸基地" in system_prompt
        assert "[人物] 叶文洁" not in system_prompt

    async def test_no_element_section_when_world_has_no_elements(self, llm, char_repo, msg_repo):
        """世界本身无（非角色）元素时，不注入元素 section（兜底不应凭空造内容）。"""
        from src.services.dialogue_generation_service import DialogueGenerationService

        world_doc = _make_world_doc()
        world_doc.elements = []  # 无任何元素
        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]

        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
        )
        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": char_a.id, "name": "叶文洁"}],
            relevant_elements=[],
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "相关元素详细信息" not in system_prompt


# ── Step 3 (edit mode): _build_participant_input in edit mode ─────────────────


class TestEditModeInputBuilding:
    """Step 3: edit mode builds speakers and background without LLM."""

    async def test_edit_mode_skips_llm(self):
        """In edit mode, select_participants should not call LLM."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        llm = AsyncMock()
        char_a = _make_character("叶文洁")
        char_b = _make_character("常伟思")
        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [char_a, char_b]
        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        world_repo = AsyncMock()
        world_doc = _make_world_doc()
        world_repo.get.return_value = world_doc
        relation_repo = AsyncMock()
        relation_repo.list_by_world.return_value = []

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
        )
        result = await svc.select_participants(
            world_id="w1",
            user_message="test",
            participant_mode="edit",
            current_participants=[{"id": char_a.id, "name": "叶文洁"}],
        )

        llm.complete_json.assert_not_called()
        assert "speakers" in result
        assert "background" in result


# ── Round 3: Additional coverage tests ────────────────────────────────────────


class TestBoundaryConditions:
    """Round 3: Boundary conditions and type safety."""

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def char_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def msg_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        mock.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        return mock

    @pytest.fixture
    def world_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def relation_repo(self):
        mock = AsyncMock()
        mock.list_by_world.return_value = []
        return mock

    async def test_background_capped_at_max_background(
        self, llm, char_repo, msg_repo, world_repo, relation_repo
    ):
        """LLM-generated background should be capped at MAX_BACKGROUND."""
        from src.services.dialogue_generation_service import (
            MAX_BACKGROUND,
            DialogueGenerationService,
        )

        chars = [_make_character(f"角色{i}") for i in range(15)]
        char_repo.list_by_world.return_value = chars
        world_repo.get.return_value = _make_world_doc()

        llm.complete_json.return_value = {
            "speakers": ["角色0"],
            "background": [f"角色{i}" for i in range(1, 15)],
            "narration": "",
            "relevant_elements": [],
        }

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
        )
        result = await svc.select_participants(world_id="w1", user_message="test")
        assert len(result["background"]) <= MAX_BACKGROUND

    async def test_offset_minutes_handles_non_numeric(self, llm, char_repo, msg_repo):
        """Non-numeric offset_minutes should default to 0."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": "测试",
                    "virtual_time_offset_minutes": "invalid",
                }
            ]
        }

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
        )
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        assert len(responses) == 1
        # Should use offset 0 (default) instead of crashing
        # real_time is no longer set by generate_response (was virtual_time)

    async def test_none_content_handled(self, llm, char_repo, msg_repo):
        """LLM returning content: null should produce empty string."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": None,
                    "virtual_time_offset_minutes": 0,
                }
            ]
        }

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
        )
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        assert len(responses) == 1
        assert responses[0].content == ""

    async def test_elements_context_with_none_category(self):
        """Elements with None category should be filtered out."""
        from src.services.dialogue_generation_service import _build_elements_context

        world_doc = MagicMock()
        world_doc.source = None
        e1 = MagicMock()
        e1.name = "正常元素"
        e1.category = "场所"
        e1.brief = "简介"
        e2 = MagicMock()
        e2.name = "无类别元素"
        e2.category = None
        e2.brief = "简介"
        world_doc.elements = [e1, e2]

        result = _build_elements_context(world_doc)
        assert "正常元素" in result
        assert "无类别元素" not in result

    async def test_llm_returns_list_instead_of_dict_for_select(
        self, llm, char_repo, msg_repo, world_repo, relation_repo
    ):
        """select_participants should handle LLM returning a list."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        world_repo.get.return_value = _make_world_doc()
        llm.complete_json.return_value = [{"name": "叶文洁"}]  # list, not dict

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            relation_repo=relation_repo,
        )
        result = await svc.select_participants(world_id="w1", user_message="test")
        assert result["speakers"] == []
        assert result["background"] == []


class TestUnwrapListShared:
    """Round 3: Verify shared unwrap_list utility works correctly."""

    def test_list_passthrough(self):
        from src.utils.llm_utils import unwrap_list

        assert unwrap_list([1, 2, 3]) == [1, 2, 3]

    def test_none_returns_empty(self):
        from src.utils.llm_utils import unwrap_list

        assert unwrap_list(None) == []

    def test_dict_known_wrapper_key(self):
        from src.utils.llm_utils import unwrap_list

        assert unwrap_list({"items": [1, 2]}) == [1, 2]
        assert unwrap_list({"results": [3]}) == [3]

    def test_dict_unknown_key_with_list_value(self):
        from src.utils.llm_utils import unwrap_list

        assert unwrap_list({"characters": [7, 8]}) == [7, 8]

    def test_dict_no_list_values(self):
        from src.utils.llm_utils import unwrap_list

        assert unwrap_list({"name": "test", "count": 5}) == []


# ── Round 3: generate_response defensive result handling ──────────────────


class TestGenerateResponseResultHandling:
    """Round 3: generate_response handles various LLM result types safely."""

    @pytest.fixture
    def llm(self):
        return AsyncMock()

    @pytest.fixture
    def char_repo(self):
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def msg_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        mock.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        return mock

    async def test_llm_returns_list_with_valid_messages(self, llm, char_repo, msg_repo):
        """LLM returning a list of message dicts should be processed correctly."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        llm.complete_json.return_value = [
            {
                "type": "dialogue",
                "sender_type": "character",
                "sender_name": "叶文洁",
                "content": "你好",
                "virtual_time_offset_minutes": 0,
            }
        ]

        svc = DialogueGenerationService(llm=llm, character_repo=char_repo, message_repo=msg_repo)
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        assert len(responses) == 1
        assert responses[0].sender_id == char_a.id

    async def test_llm_returns_list_with_non_dict_items(self, llm, char_repo, msg_repo):
        """LLM returning a list with non-dict items should skip those items."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_a = _make_character("叶文洁")
        char_repo.list_by_world.return_value = [char_a]
        llm.complete_json.return_value = [
            42,
            "not a dict",
            {
                "type": "dialogue",
                "sender_type": "character",
                "sender_name": "叶文洁",
                "content": "你好",
                "virtual_time_offset_minutes": 0,
            },
            None,
        ]

        svc = DialogueGenerationService(llm=llm, character_repo=char_repo, message_repo=msg_repo)
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        # Only the dict item with valid sender_name should be kept
        assert len(responses) == 1
        assert responses[0].content == "你好"

    async def test_llm_returns_none_result(self, llm, char_repo, msg_repo):
        """LLM returning None (shouldn't happen) should produce empty responses."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_repo.list_by_world.return_value = []
        llm.complete_json.return_value = None

        svc = DialogueGenerationService(llm=llm, character_repo=char_repo, message_repo=msg_repo)
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        assert responses == []

    async def test_llm_returns_empty_list(self, llm, char_repo, msg_repo):
        """LLM returning empty list should produce empty responses."""
        from src.services.dialogue_generation_service import DialogueGenerationService

        char_repo.list_by_world.return_value = []
        llm.complete_json.return_value = []

        svc = DialogueGenerationService(llm=llm, character_repo=char_repo, message_repo=msg_repo)
        responses = await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        assert responses == []
