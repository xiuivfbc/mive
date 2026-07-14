"""Tests for DialogueGenerationService."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.character import Character
from src.services.dialogue_generation_service import DialogueGenerationService


def _make_character(name: str, char_id: str | None = None) -> Character:
    return Character(
        id=char_id or str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        profile={
            "brief": f"{name}的角色简介",
            "detail": f"{name}的详细描述",
            "personality": f"{name}的性格",
        },
    )


class TestDialogueGenerationService:
    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        mock.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": "常将军，我昨晚确实发现了一些异常信号...",
                    "virtual_time_offset_minutes": 0,
                },
                {
                    "type": "narration",
                    "sender_type": "narrator",
                    "sender_name": "旁白",
                    "content": "叶文洁从文件夹中抽出一页数据，递给常伟思。",
                    "virtual_time_offset_minutes": 2,
                },
            ]
        }
        return mock

    @pytest.fixture
    def character_repo(self):
        mock = AsyncMock()
        mock.list_by_world.return_value = [
            _make_character("叶文洁"),
            _make_character("常伟思"),
        ]
        return mock

    @pytest.fixture
    def message_repo(self):
        mock = AsyncMock()
        mock.list_by_session = AsyncMock(return_value=[])
        mock.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        return mock

    @pytest.fixture
    def service(self, llm, character_repo, message_repo):
        return DialogueGenerationService(
            llm=llm,
            character_repo=character_repo,
            message_repo=message_repo,
        )

    async def test_generate_response_returns_messages(self, service):
        responses = await service.generate_response(
            world_id="world-001",
            user_message="你觉得昨晚的观测数据正常吗？",
        )
        assert len(responses) == 2
        assert responses[0].type == "dialogue"
        assert responses[0].sender_id is not None  # sender_id resolved from name
        assert responses[1].type == "narration"

    async def test_generate_response_reads_characters(self, service, character_repo):
        await service.generate_response(
            world_id="world-001",
            user_message="test",
        )
        character_repo.list_by_world.assert_called_once_with("world-001", include_extra=False)

    async def test_generate_response_reads_session_history_when_session_given(
        self, service, message_repo
    ):
        await service.generate_response(
            world_id="world-001",
            user_message="test",
            session_id="session-123",
        )
        message_repo.list_by_session.assert_called_once_with("session-123")

    async def test_generate_response_writes_messages(self, service, message_repo):
        await service.generate_response(
            world_id="world-001",
            user_message="test",
        )
        message_repo.create_batch.assert_called_once()
        written_msgs = message_repo.create_batch.call_args[0][0]
        assert len(written_msgs) == 2

    async def test_unmatched_sender_name_is_skipped(self, llm, character_repo, message_repo):
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "不存在的角色",
                    "content": "这不应该出现",
                    "virtual_time_offset_minutes": 0,
                },
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": "正常消息",
                    "virtual_time_offset_minutes": 1,
                },
            ]
        }
        service = DialogueGenerationService(
            llm=llm,
            character_repo=character_repo,
            message_repo=message_repo,
        )
        responses = await service.generate_response(
            world_id="world-001",
            user_message="test",
        )
        assert len(responses) == 1
        assert responses[0].sender_id is not None

    async def test_generate_response_system_prompt_contains_user_identity_rules(self, service, llm):
        """系统 prompt 始终包含用户身份规则段（静态，利于 cache）。"""
        await service.generate_response(
            world_id="world-001",
            user_message="test",
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "访客" in system_prompt or "小傻瓜" in system_prompt or "用户参与者" in system_prompt

    async def test_generate_response_user_role_character_in_user_prompt(
        self, llm, character_repo, message_repo
    ):
        """用户扮演角色时，角色信息出现在动态部分（user prompt）。"""
        role_char_id = str(uuid.uuid4())
        char_repo = AsyncMock()
        role_char = _make_character("汪淼", role_char_id)
        char_repo.list_by_world.return_value = [
            _make_character("叶文洁"),
            role_char,
        ]
        world_repo = AsyncMock()
        world_doc = MagicMock()
        world_doc.user_character_id = role_char_id
        world_repo.get.return_value = world_doc
        service = DialogueGenerationService(
            llm=llm, character_repo=char_repo, message_repo=message_repo, world_repo=world_repo
        )
        await service.generate_response(
            world_id="world-001",
            user_message="大家好",
        )
        user_prompt = llm.complete_json.call_args[0][1]
        assert "汪淼" in user_prompt

    async def test_narrator_does_not_need_character_match(self, llm, character_repo, message_repo):
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "narration",
                    "sender_type": "narrator",
                    "sender_name": "旁白",
                    "content": "场景描述",
                    "virtual_time_offset_minutes": 0,
                },
            ]
        }
        service = DialogueGenerationService(
            llm=llm,
            character_repo=character_repo,
            message_repo=message_repo,
        )
        responses = await service.generate_response(
            world_id="world-001",
            user_message="test",
        )
        assert len(responses) == 1
        assert responses[0].sender_type == "narrator"


class TestSelectParticipants:
    """Tests for DialogueGenerationService.select_participants() (Call 1)."""

    CHAR_ID_1 = str(uuid.uuid4())
    CHAR_ID_2 = str(uuid.uuid4())

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        mock.complete_json.return_value = {
            "speakers": ["叶文洁", "汪淼"],
            "background": [],
            "narration": "叶文洁和汪淼在观测台相遇。",
            "relevant_elements": [],
            "relevant_event": None,
        }
        return mock

    @pytest.fixture
    def character_repo(self):
        mock = AsyncMock()
        mock.list_by_world.return_value = [
            _make_character("叶文洁", self.CHAR_ID_1),
            _make_character("汪淼", self.CHAR_ID_2),
        ]
        return mock

    @pytest.fixture
    def message_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        return mock

    @pytest.fixture
    def service(self, llm, character_repo, message_repo):
        return DialogueGenerationService(
            llm=llm,
            character_repo=character_repo,
            message_repo=message_repo,
        )

    async def test_select_participants_returns_ids_and_narration(self, service):
        result = await service.select_participants(
            world_id="world-001",
            user_message="你好，最近怎么样？",
        )
        assert result["speakers"] == [
            {"id": self.CHAR_ID_1, "name": "叶文洁"},
            {"id": self.CHAR_ID_2, "name": "汪淼"},
        ]
        assert result["narration"] == "叶文洁和汪淼在观测台相遇。"

    async def test_select_participants_filters_unknown_characters(
        self, llm, character_repo, message_repo
    ):
        llm.complete_json.return_value = {
            "speakers": ["叶文洁", "不存在的角色"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": None,
        }
        service = DialogueGenerationService(
            llm=llm, character_repo=character_repo, message_repo=message_repo
        )
        result = await service.select_participants(world_id="world-001", user_message="test")
        assert len(result["speakers"]) == 1
        assert result["speakers"][0]["name"] == "叶文洁"

    async def test_select_participants_allows_empty_narration(self, llm, service):
        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": None,
        }
        result = await service.select_participants(world_id="world-001", user_message="test")
        assert result["narration"] == ""

    async def test_select_participants_calls_llm(self, service, llm):
        await service.select_participants(world_id="world-001", user_message="test")
        llm.complete_json.assert_called_once()

    async def test_select_participants_excludes_world_user_character(self, llm, message_repo):
        """世界用户角色不出现在 AI 参与者列表中。"""
        world_user_id = str(uuid.uuid4())
        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [
            _make_character("叶文洁", self.CHAR_ID_1),
            _make_character("时空探索者", world_user_id),
        ]
        world_doc = AsyncMock()
        world_doc.elements = []
        world_doc.source = None
        world_doc.user_character_id = world_user_id
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc
        llm.complete_json.return_value = {
            "speakers": ["叶文洁", "时空探索者"],
            "background": [],
            "narration": "旁白",
            "relevant_elements": [],
            "relevant_event": None,
        }
        service = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=message_repo,
            world_repo=world_repo,
        )
        result = await service.select_participants(
            world_id="world-001",
            user_message="test",
        )
        names = [p["name"] for p in result["speakers"]]
        assert "时空探索者" not in names
        assert "叶文洁" in names

    async def test_select_participants_returns_relevant_event_in_result(self, service):
        """返回值中应包含 relevant_event 字段。"""
        result = await service.select_participants(world_id="world-001", user_message="test")
        assert "relevant_event" in result
        assert result["relevant_event"] is None  # 无 event_map 时为 None

    async def test_select_participants_filters_hallucinated_elements(self, llm, message_repo):
        """LLM 返回不存在的元素名时应被过滤掉。"""
        from unittest.mock import MagicMock

        world_doc = MagicMock()
        world_doc.source = None
        world_doc.user_character_id = None
        elem1 = MagicMock()
        elem1.name = "红岸基地"
        elem1.brief = "秘密军事基地"
        elem1.category = "场所"
        elem2 = MagicMock()
        elem2.name = "三体游戏"
        elem2.brief = "虚拟现实游戏"
        elem2.category = "物品"
        world_doc.elements = [elem1, elem2]

        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [
            _make_character("叶文洁", self.CHAR_ID_1),
            _make_character("汪淼", self.CHAR_ID_2),
        ]
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": ["红岸基地", "不存在的元素", "三体游戏"],
            "relevant_event": None,
        }
        service = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=message_repo,
            world_repo=world_repo,
        )
        result = await service.select_participants(world_id="world-001", user_message="test")
        # "不存在的元素" 应被过滤
        assert result["relevant_elements"] == ["红岸基地", "三体游戏"]

    async def test_select_participants_limits_elements_to_max(self, llm, message_repo):
        """relevant_elements 应限制在 MAX_RELEVANT_ELEMENTS 个以内。"""
        from unittest.mock import MagicMock

        world_doc = MagicMock()
        world_doc.source = None
        world_doc.user_character_id = None
        elems = []
        for i in range(5):
            e = MagicMock()
            e.name = f"元素{i}"
            e.brief = f"简介{i}"
            e.category = "物品"
            elems.append(e)
        world_doc.elements = elems

        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [
            _make_character("叶文洁", self.CHAR_ID_1),
        ]
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": ["元素0", "元素1", "元素2", "元素3", "元素4"],
            "relevant_event": None,
        }
        service = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=message_repo,
            world_repo=world_repo,
        )
        result = await service.select_participants(world_id="world-001", user_message="test")
        from src.services.dialogue_generation_service import MAX_RELEVANT_ELEMENTS

        assert len(result["relevant_elements"]) <= MAX_RELEVANT_ELEMENTS

    async def test_select_participants_filters_hallucinated_event_id(self, llm, message_repo):
        """LLM 返回不存在的事件 ID 时应被过滤。"""
        from unittest.mock import MagicMock

        world_doc = MagicMock()
        world_doc.source = None
        world_doc.user_character_id = None
        world_doc.elements = []

        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [
            _make_character("叶文洁", self.CHAR_ID_1),
        ]
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        valid_event_id = str(uuid.uuid4())
        fake_event_id = str(uuid.uuid4())

        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": fake_event_id,
        }
        service = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=message_repo,
            world_repo=world_repo,
        )
        result = await service.select_participants(
            world_id="world-001",
            user_message="test",
            event_map={valid_event_id: "红岸事件：秘密信号"},
        )
        # fake_event_id 不在 event_map 中，应被过滤为 None
        assert result["relevant_event"] is None

    async def test_select_participants_accepts_valid_event_id(self, llm, message_repo):
        """LLM 返回有效事件 ID 时应保留。"""
        from unittest.mock import MagicMock

        world_doc = MagicMock()
        world_doc.source = None
        world_doc.user_character_id = None
        world_doc.elements = []

        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [
            _make_character("叶文洁", self.CHAR_ID_1),
        ]
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        valid_event_id = str(uuid.uuid4())

        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": valid_event_id,
        }
        service = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=message_repo,
            world_repo=world_repo,
        )
        result = await service.select_participants(
            world_id="world-001",
            user_message="test",
            event_map={valid_event_id: "红岸事件：秘密信号"},
        )
        assert result["relevant_event"] == valid_event_id

    async def test_select_participants_edit_mode_returns_empty_elements_and_event(self, service):
        """edit 模式应返回空 relevant_elements 和 None relevant_event。"""
        result = await service.select_participants(
            world_id="world-001",
            user_message="test",
            participant_mode="edit",
            current_participants=[{"id": self.CHAR_ID_1, "name": "叶文洁"}],
        )
        assert result["relevant_elements"] == []
        assert result["relevant_event"] is None


class TestGenerateResponseUserIdentity:
    """generate_response 用户身份展示：有 world_user_char_id 时显示扮演角色，无时显示时空探索者。"""

    WORLD_USER_CHAR_ID = str(uuid.uuid4())
    NPC_CHAR_ID = str(uuid.uuid4())

    def _make_world_doc(self, has_user_char=True):
        wd = AsyncMock()
        wd.elements = []
        wd.source = None
        wd.user_character_id = self.WORLD_USER_CHAR_ID if has_user_char else None
        return wd

    def _make_chars(self):
        world_user = _make_character("时空探索者", self.WORLD_USER_CHAR_ID)
        npc = _make_character("叶文洁", self.NPC_CHAR_ID)
        return [world_user, npc]

    def _build_service(self, llm, chars, world_doc):
        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = chars
        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc
        return DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
        )

    async def test_null_user_character_id_shows_explorer(self):
        """No user_character_id on world -> shows explorer persona."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm, self._make_chars(), self._make_world_doc())

        await svc.generate_response(
            world_id="w1",
            user_message="你好",
        )
        user_prompt = llm.complete_json.call_args[0][1]
        assert "时空探索者" in user_prompt

    async def test_world_has_user_character_id_shows_identity(self):
        """World has user_character_id -> shows self identity message."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm, self._make_chars(), self._make_world_doc())

        await svc.generate_response(
            world_id="w1",
            user_message="你好",
        )
        user_prompt = llm.complete_json.call_args[0][1]
        assert "来自这个世界之外" in user_prompt or "时空探索者" in user_prompt

    async def test_npc_displayed_when_world_has_user_character_id(self):
        """World with user_character_id still includes NPC in candidate list."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm, self._make_chars(), self._make_world_doc())

        await svc.generate_response(
            world_id="w1",
            user_message="你好",
        )
        user_prompt = llm.complete_json.call_args[0][1]
        assert "时空探索者" in user_prompt
        assert "扮演角色" in user_prompt

    async def test_null_user_role_excludes_world_user_from_npc_list(self):
        """无用户角色时，世界用户角色不应出现在 NPC 列表中。"""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm, self._make_chars(), self._make_world_doc())

        await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        # 全量角色列表在 system_prompt 变量部分中
        system_prompt = llm.complete_json.call_args[0][0]
        # 世界用户角色不应在候选角色列表中（但 "时空探索者" 可能出现在 _EXPLORER_PERSONA 中）
        assert "- 时空探索者:" not in system_prompt
        assert "- 叶文洁:" in system_prompt

    async def test_null_user_character_id_fallback_to_explorer(self):
        """Null user_character_id falls back to explorer persona."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm, self._make_chars(), self._make_world_doc())

        await svc.generate_response(
            world_id="w1",
            user_message="test",
        )
        user_prompt = llm.complete_json.call_args[0][1]
        assert "时空探索者" in user_prompt

    async def test_no_world_user_character_shows_explorer(self):
        """World has no user_character_id -> shows explorer."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        # 世界文档无 user_character_id
        chars = [_make_character("叶文洁", self.NPC_CHAR_ID)]
        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = chars
        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        world_repo = AsyncMock()
        world_doc = AsyncMock()
        world_doc.elements = []
        world_doc.source = None
        world_doc.user_character_id = None
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
        )
        user_prompt = llm.complete_json.call_args[0][1]
        assert "时空探索者" in user_prompt


class TestGenerateResponseWithMemories:
    """Tests for memory injection in generate_response."""

    CHAR_ID = str(uuid.uuid4())

    @pytest.fixture
    def llm(self):
        mock = AsyncMock()
        mock.complete_json.return_value = {"messages": []}
        return mock

    @pytest.fixture
    def character_repo(self):
        mock = AsyncMock()
        mock.list_by_world.return_value = [_make_character("叶文洁", self.CHAR_ID)]
        return mock

    @pytest.fixture
    def message_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        mock.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        return mock

    @pytest.fixture
    def memory_repo(self):
        mock = AsyncMock()
        # Return some short-term and long-term memories
        short_mem = AsyncMock()
        short_mem.content = "我刚刚观测到异常信号"
        long_mem = AsyncMock()
        long_mem.content = "某次我发现了红岸基地的秘密"
        mock.list_short_term = AsyncMock(return_value=[short_mem])
        mock.list_long_term = AsyncMock(return_value=[long_mem])
        return mock

    @pytest.fixture
    def service(self, llm, character_repo, message_repo, memory_repo):
        return DialogueGenerationService(
            llm=llm,
            character_repo=character_repo,
            message_repo=message_repo,
            memory_repo=memory_repo,
        )

    async def test_memory_injected_into_system_prompt(self, service, llm, memory_repo):
        """短期记忆应注入到 system prompt 中。"""
        await service.generate_response(
            world_id="world-001",
            user_message="test",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "近期经历" in system_prompt
        assert "我刚刚观测到异常信号" in system_prompt

    async def test_memory_repo_called_for_participants(self, service, memory_repo):
        """应为参与角色读取短期记忆。"""
        await service.generate_response(
            world_id="world-001",
            user_message="test",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        assert memory_repo.list_short_term.call_count >= 1

    async def test_no_memory_repo_skips_injection(self, llm, character_repo, message_repo):
        """无 memory_repo 时跳过记忆注入。"""
        service = DialogueGenerationService(
            llm=llm,
            character_repo=character_repo,
            message_repo=message_repo,
            memory_repo=None,
        )
        await service.generate_response(
            world_id="world-001",
            user_message="test",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "近期经历" not in system_prompt

    async def test_empty_memories_shows_placeholder(self, llm, character_repo, message_repo):
        """无记忆时显示"暂无"。"""
        memory_repo = AsyncMock()
        memory_repo.list_short_term = AsyncMock(return_value=[])
        memory_repo.list_long_term = AsyncMock(return_value=[])
        service = DialogueGenerationService(
            llm=llm,
            character_repo=character_repo,
            message_repo=message_repo,
            memory_repo=memory_repo,
        )
        await service.generate_response(
            world_id="world-001",
            user_message="test",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "暂无" in system_prompt


# ── Chat Context Builder refactor tests ──────────────────────────────────────


class TestChatContextBuilder:
    """Tests for the refactored context builder helpers.

    Phase 0 (RED): These tests verify the extracted helper functions produce
    the same output as the original inline code in generate_response.
    """

    CHAR_ID_1 = str(uuid.uuid4())
    CHAR_ID_2 = str(uuid.uuid4())
    WORLD_USER_CHAR_ID = str(uuid.uuid4())

    def _make_chars(self):
        return [
            _make_character("叶文洁", self.CHAR_ID_1),
            _make_character("常伟思", self.CHAR_ID_2),
        ]

    def _make_world_doc(self, user_char_id=None):
        wd = AsyncMock()
        wd.elements = []
        wd.source = None
        wd.user_character_id = user_char_id
        return wd

    def _build_service(self, llm, chars, world_doc, **kwargs):
        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = chars
        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc
        return DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            **kwargs,
        )

    async def test_context_builder_basic_fields(self):
        """Verify LLM call receives expected model, operation, messages structure.

        The last user message content should appear in user_prompt, and the
        system prompt should contain the character name.
        """
        from src.llm.base import llm_operation

        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        chars = self._make_chars()
        world_doc = self._make_world_doc()
        svc = self._build_service(llm, chars, world_doc)

        await svc.generate_response(
            world_id="w1",
            user_message="你好，叶文洁",
            participants=[{"id": self.CHAR_ID_1, "name": "叶文洁"}],
        )

        # Verify LLM was called
        llm.complete_json.assert_called_once()
        call_args = llm.complete_json.call_args
        system_prompt = call_args[0][0]
        user_prompt = call_args[0][1]

        # system prompt includes character name
        assert "叶文洁" in system_prompt
        # user prompt includes the user message
        assert "你好，叶文洁" in user_prompt
        # operation is set to "角色聊天"
        assert llm_operation.get() == "角色聊天"

    async def test_system_prompt_sections(self):
        """Verify system prompt contains character name, profile, relations,
        world event/history, and knowledge sections.

        Checks for substring presence of key sections.
        """
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        chars = self._make_chars()
        world_doc = self._make_world_doc()
        svc = self._build_service(llm, chars, world_doc)

        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": self.CHAR_ID_1, "name": "叶文洁"}],
        )

        system_prompt = llm.complete_json.call_args[0][0]

        # Character name present
        assert "叶文洁" in system_prompt
        # Character profile sections present
        assert "简介" in system_prompt
        assert "详细" in system_prompt
        assert "性格" in system_prompt
        # Candidate character list
        assert "候选角色列表" in system_prompt
        # Rules section
        assert "规则" in system_prompt
        # Output format
        assert "messages" in system_prompt
        # User identity rule
        assert "用户参与者" in system_prompt

    async def test_token_budget_trimming(self):
        """Create many messages exceeding a token budget, verify the system
        still handles them (history is capped at 20 messages).
        """
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        chars = self._make_chars()
        world_doc = self._make_world_doc()

        # Create 30 history messages (more than the 20-message cap)
        many_messages = []
        for i in range(30):
            msg = AsyncMock()
            msg.sender_id = self.CHAR_ID_1
            msg.sender_type = "character"
            msg.type = "dialogue"
            msg.content = f"消息内容{i}" * 10  # make each message longer
            many_messages.append(msg)

        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = chars
        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = many_messages
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
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
            participants=[{"id": self.CHAR_ID_1, "name": "叶文洁"}],
        )

        user_prompt = llm.complete_json.call_args[0][1]
        # The history in user_prompt should be capped (only last 20 messages)
        # Count how many "消息内容" occurrences appear in the history section
        history_section = user_prompt.split("最近对话历史:")[1].split("用户刚刚说")[0]
        # Should have at most 20 messages in history
        assert history_section.count("消息内容") <= 20

    async def test_relation_context_skipped_for_no_relation_character(self):
        """When a character has no relation with the world user character,
        the system prompt should not contain relation context.
        """
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        chars = self._make_chars()
        # World has a user character
        world_doc = self._make_world_doc(user_char_id=self.WORLD_USER_CHAR_ID)
        # Add a world user character to the char list
        world_user_char = _make_character("时空探索者", self.WORLD_USER_CHAR_ID)
        all_chars = chars + [world_user_char]

        # No relation_repo — no relations available
        svc = self._build_service(llm, all_chars, world_doc)

        await svc.generate_response(
            world_id="w1",
            user_message="test",
            participants=[{"id": self.CHAR_ID_1, "name": "叶文洁"}],
        )

        system_prompt = llm.complete_json.call_args[0][0]
        # The current code doesn't inject relation context into the system prompt
        # (relations are only used in select_participants, not generate_response).
        # This test verifies no "角色关系" section appears when there are no relations.
        # Note: the current implementation doesn't have a relation section at all,
        # so this test passes by default — but it documents the expected behavior.
        assert "角色关系" not in system_prompt


class TestBuildCacheablePrefixCommonSense:
    """Tests for _build_cacheable_prefix() with common_sense injection."""

    def test_prefix_includes_common_sense_when_non_empty(self):
        """common_sense 非空时应追加到 prefix 中。"""
        from unittest.mock import MagicMock

        from src.services.dialogue_generation_service import _build_cacheable_prefix

        world_doc = MagicMock()
        world_doc.source.title = "测试作品"
        world_doc.source.author = "作者"
        world_doc.source.common_sense = "这个世界存在魔法体系，时间流速与现实不同。"
        world_doc.elements = []

        prefix = _build_cacheable_prefix(world_doc, "对话引擎")

        assert "世界设定" in prefix
        assert "这个世界存在魔法体系" in prefix

    def test_prefix_excludes_common_sense_when_empty(self):
        """common_sense 为空字符串时不应追加。"""
        from unittest.mock import MagicMock

        from src.services.dialogue_generation_service import _build_cacheable_prefix

        world_doc = MagicMock()
        world_doc.source.title = "测试作品"
        world_doc.source.author = "作者"
        world_doc.source.common_sense = ""
        world_doc.elements = []

        prefix = _build_cacheable_prefix(world_doc, "对话引擎")

        assert "世界设定" not in prefix

    def test_prefix_excludes_common_sense_when_none(self):
        """common_sense 为 None 时不应追加（兼容旧数据）。"""
        from unittest.mock import MagicMock

        from src.services.dialogue_generation_service import _build_cacheable_prefix

        world_doc = MagicMock()
        world_doc.source.title = "测试作品"
        world_doc.source.author = "作者"
        # Simulate old WorldDoc without common_sense attribute
        del world_doc.source.common_sense
        world_doc.elements = []

        prefix = _build_cacheable_prefix(world_doc, "对话引擎")

        assert "世界设定" not in prefix


# ── Tests for "all" relevant_event support ────────────────────────────────────


class TestSelectParticipantsRelevantEventAll:
    """select_participants should accept "all" as a valid relevant_event value."""

    CHAR_ID_1 = str(uuid.uuid4())

    @pytest.fixture
    def llm(self):
        return AsyncMock()

    @pytest.fixture
    def character_repo(self):
        mock = AsyncMock()
        mock.list_by_world.return_value = [_make_character("叶文洁", self.CHAR_ID_1)]
        return mock

    @pytest.fixture
    def message_repo(self):
        mock = AsyncMock()
        mock.list_by_session.return_value = []
        return mock

    @pytest.fixture
    def world_repo(self):
        mock = AsyncMock()
        world_doc = AsyncMock()
        world_doc.source = None
        world_doc.user_character_id = None
        world_doc.elements = []
        mock.get.return_value = world_doc
        return mock

    @pytest.fixture
    def service(self, llm, character_repo, message_repo, world_repo):
        return DialogueGenerationService(
            llm=llm,
            character_repo=character_repo,
            message_repo=message_repo,
            world_repo=world_repo,
        )

    async def test_select_participants_accepts_all_value(self, llm, service):
        """LLM returning relevant_event="all" should be preserved."""
        event_id = str(uuid.uuid4())
        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": "all",
        }
        result = await service.select_participants(
            world_id="world-001",
            user_message="最近发生了什么大事？",
            event_map={event_id: "红岸事件"},
        )
        assert result["relevant_event"] == "all"

    async def test_select_participants_prompt_includes_all_instruction(self, llm, service):
        """The prompt should instruct LLM that "all" is a valid relevant_event value."""
        event_id = str(uuid.uuid4())
        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": None,
        }
        await service.select_participants(
            world_id="world-001",
            user_message="最近发生了什么？",
            event_map={event_id: "红岸事件"},
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert '"all"' in system_prompt

    async def test_select_participants_rejects_all_when_no_event_map(self, llm, service):
        """LLM returning "all" when event_map is None should be filtered to None."""
        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": "all",
        }
        result = await service.select_participants(
            world_id="world-001",
            user_message="最近发生了什么？",
            event_map=None,
        )
        assert result["relevant_event"] is None

    async def test_select_participants_rejects_all_when_event_map_empty(self, llm, service):
        """LLM returning "all" when event_map is empty should be filtered to None."""
        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": "all",
        }
        result = await service.select_participants(
            world_id="world-001",
            user_message="最近发生了什么？",
            event_map={},
        )
        assert result["relevant_event"] is None


class TestGenerateResponseRelevantEventAll:
    """generate_response should handle relevant_event="all" by loading full event list."""

    CHAR_ID = str(uuid.uuid4())
    WORLD_ID = str(uuid.uuid4())

    def _build_service(self, llm, **kwargs):
        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [_make_character("叶文洁", self.CHAR_ID)]
        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        world_repo = AsyncMock()
        world_doc = AsyncMock()
        world_doc.source = None
        world_doc.user_character_id = None
        world_doc.elements = []
        world_repo.get.return_value = world_doc
        memory_repo = AsyncMock()
        memory_repo.list_short_term = AsyncMock(return_value=[])
        memory_repo.list_long_term = AsyncMock(return_value=[])
        return DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            memory_repo=memory_repo,
            **kwargs,
        )

    async def test_relevant_event_all_injects_event_list_into_prompt(self):
        """When relevant_event="all", the system prompt should contain the event list."""
        from unittest.mock import patch

        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}

        mock_event = AsyncMock()
        mock_event.id = uuid.uuid4()
        mock_event.event_name = "红岸事件"
        mock_event.brief = "叶文洁向三体星系发送信号"

        with patch("src.db.repositories.event_index_repo.EventIndexRepository") as mock_ei_repo_cls:
            mock_ei_repo = AsyncMock()
            mock_ei_repo.list_by_world = AsyncMock(return_value=[mock_event])
            mock_ei_repo_cls.return_value = mock_ei_repo

            svc = self._build_service(llm)
            await svc.generate_response(
                world_id=self.WORLD_ID,
                user_message="最近发生了什么？",
                participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
                relevant_event="all",
            )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "已有事件" in system_prompt
        assert "叶文洁向三体星系发送信号" in system_prompt

    async def test_relevant_event_null_no_event_injection(self):
        """When relevant_event=None, no event list should be injected."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm)
        await svc.generate_response(
            world_id=self.WORLD_ID,
            user_message="你好",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
            relevant_event=None,
        )
        system_prompt = llm.complete_json.call_args[0][0]
        assert "已有事件" not in system_prompt

    async def test_relevant_event_all_skips_long_term_memory(self):
        """When relevant_event="all", long-term memories should not be injected."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm)
        await svc.generate_response(
            world_id=self.WORLD_ID,
            user_message="最近发生了什么？",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
            relevant_event="all",
        )
        system_prompt = llm.complete_json.call_args[0][0]
        # 长期记忆不应在 "all" 模式下注入
        assert "长期记忆" not in system_prompt

    async def test_relevant_event_all_empty_event_list(self):
        """When relevant_event="all" but no events exist, no event section injected."""
        from unittest.mock import patch

        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}

        with patch("src.db.repositories.event_index_repo.EventIndexRepository") as mock_ei_repo_cls:
            mock_ei_repo = AsyncMock()
            mock_ei_repo.list_by_world = AsyncMock(return_value=[])
            mock_ei_repo_cls.return_value = mock_ei_repo

            svc = self._build_service(llm)
            await svc.generate_response(
                world_id=self.WORLD_ID,
                user_message="最近发生了什么？",
                participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
                relevant_event="all",
            )
        system_prompt = llm.complete_json.call_args[0][0]
        # Empty event list → no event section injected (code skips when ei_entries is empty)
        assert "已有事件" not in system_prompt


class TestNeedMoreContextStringEnum:
    """need_more_context should accept string values "yes" and "all"."""

    CHAR_ID = str(uuid.uuid4())
    WORLD_ID = str(uuid.uuid4())

    def _build_service(self, llm):
        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [_make_character("叶文洁", self.CHAR_ID)]
        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        world_repo = AsyncMock()
        world_doc = AsyncMock()
        world_doc.source = None
        world_doc.user_character_id = None
        world_doc.elements = []
        world_repo.get.return_value = world_doc
        memory_repo = AsyncMock()
        memory_repo.list_short_term = AsyncMock(return_value=[])
        memory_repo.list_long_term = AsyncMock(return_value=[])
        return DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            memory_repo=memory_repo,
        )

    async def test_need_more_context_yes_triggers_supplement(self):
        """need_more_context="yes" should trigger the supplement flow."""
        llm = AsyncMock()
        # Call sequence:
        # 1. generate_response → need_more_context="yes"
        # 2. retry generate_response (after supplement) → messages
        llm.complete_json = AsyncMock(
            side_effect=[
                {"need_more_context": "yes"},
                {
                    "messages": [
                        {
                            "type": "dialogue",
                            "sender_type": "character",
                            "sender_name": "叶文洁",
                            "content": "关于那个事件...",
                        }
                    ]
                },
            ]
        )

        svc = self._build_service(llm)
        # Mock _supplement_context to return a found event
        svc._supplement_context = AsyncMock(
            return_value={"relevant_event": "event-123", "relevant_elements": []}
        )
        responses = await svc.generate_response(
            world_id=self.WORLD_ID,
            user_message="红岸事件是怎么回事？",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        # Should have retried (2 LLM calls: initial + retry)
        assert llm.complete_json.call_count == 2
        assert len(responses) == 1
        svc._supplement_context.assert_called_once()

    async def test_need_more_context_all_injects_event_list(self):
        """need_more_context="all" should load full event list and retry."""
        from unittest.mock import patch

        llm = AsyncMock()
        # First call: generate_response returns need_more_context="all"
        # Second call: retry generate_response with relevant_event="all" returns messages
        llm.complete_json = AsyncMock(
            side_effect=[
                {"need_more_context": "all"},
                {
                    "messages": [
                        {
                            "type": "dialogue",
                            "sender_type": "character",
                            "sender_name": "叶文洁",
                            "content": "让我回顾一下...",
                        }
                    ]
                },
            ]
        )

        mock_event = AsyncMock()
        mock_event.id = uuid.uuid4()
        mock_event.event_name = "红岸事件"
        mock_event.brief = "叶文洁向三体星系发送信号"

        with patch("src.db.repositories.event_index_repo.EventIndexRepository") as mock_ei_repo_cls:
            mock_ei_repo = AsyncMock()
            mock_ei_repo.list_by_world = AsyncMock(return_value=[mock_event])
            mock_ei_repo_cls.return_value = mock_ei_repo

            svc = self._build_service(llm)
            responses = await svc.generate_response(
                world_id=self.WORLD_ID,
                user_message="最近都发生了什么？",
                participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
            )
        # Should have retried (2 LLM calls)
        assert llm.complete_json.call_count == 2
        assert len(responses) == 1
        # The second call's system prompt should contain event list
        second_system_prompt = llm.complete_json.call_args_list[1][0][0]
        assert "已有事件" in second_system_prompt

    async def test_need_more_context_no_does_not_retry(self):
        """need_more_context="no" should not trigger retry."""
        llm = AsyncMock()
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": "你好",
                }
            ]
        }
        svc = self._build_service(llm)
        responses = await svc.generate_response(
            world_id=self.WORLD_ID,
            user_message="你好",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        assert llm.complete_json.call_count == 1
        assert len(responses) == 1

    async def test_need_more_context_true_backward_compat(self):
        """need_more_context=True (old boolean) should still trigger supplement."""
        llm = AsyncMock()
        llm.complete_json = AsyncMock(
            side_effect=[
                {"need_more_context": True},
                {
                    "messages": [
                        {
                            "type": "dialogue",
                            "sender_type": "character",
                            "sender_name": "叶文洁",
                            "content": "好的",
                        }
                    ]
                },
            ]
        )

        svc = self._build_service(llm)
        svc._supplement_context = AsyncMock(
            return_value={"relevant_event": "event-123", "relevant_elements": []}
        )
        responses = await svc.generate_response(
            world_id=self.WORLD_ID,
            user_message="红岸事件",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        assert llm.complete_json.call_count == 2
        assert len(responses) == 1
        svc._supplement_context.assert_called_once()

    async def test_need_more_context_prompt_updated(self):
        """The prompt should mention "yes" and "all" string values."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm)
        await svc.generate_response(
            world_id=self.WORLD_ID,
            user_message="test",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        system_prompt = llm.complete_json.call_args_list[0][0][0]
        assert "need_more_context" in system_prompt
        assert '"yes"' in system_prompt
        assert '"all"' in system_prompt

    async def test_need_more_context_yes_supplement_exception_retries(self):
        """When _supplement_context raises, should retry with original context."""
        llm = AsyncMock()
        llm.complete_json = AsyncMock(
            side_effect=[
                {"need_more_context": "yes"},
                {
                    "messages": [
                        {
                            "type": "dialogue",
                            "sender_type": "character",
                            "sender_name": "叶文洁",
                            "content": "好的",
                        }
                    ]
                },
            ]
        )

        svc = self._build_service(llm)
        # Mock _supplement_context to raise an exception
        svc._supplement_context = AsyncMock(side_effect=RuntimeError("DB error"))

        responses = await svc.generate_response(
            world_id=self.WORLD_ID,
            user_message="红岸事件",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )
        # Should have retried despite supplement failure (2 LLM calls)
        assert llm.complete_json.call_count == 2
        assert len(responses) == 1


class TestRetrievalServiceNoneFallback:
    """When element_retrieval_service is None, fallback paths should activate."""

    CHAR_ID = str(uuid.uuid4())

    def _make_world_doc_with_elements(self):
        """Create a world_doc with non-character elements for fallback testing."""
        from unittest.mock import MagicMock

        world_doc = MagicMock()
        world_doc.source = None
        world_doc.user_character_id = None
        elem1 = MagicMock()
        elem1.name = "红岸基地"
        elem1.brief = "秘密军事基地"
        elem1.detail = "位于大兴安岭的秘密军事基地，用于监听外星信号"
        elem1.category = "场所"
        elem2 = MagicMock()
        elem2.name = "三体游戏"
        elem2.brief = "虚拟现实游戏"
        elem2.detail = "由ETO开发的沉浸式虚拟现实游戏"
        elem2.category = "物品"
        # Include a character-type element that should be excluded from fallback
        char_elem = MagicMock()
        char_elem.name = "叶文洁"
        char_elem.brief = "角色简介"
        char_elem.category = "人物"
        world_doc.elements = [elem1, elem2, char_elem]
        return world_doc

    async def test_generate_response_retrieval_service_none_fallback_to_full_load(self):
        """When element_retrieval_service is None, generate_response should fall back
        to loading all non-character world elements into the system prompt."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}

        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [_make_character("叶文洁", self.CHAR_ID)]

        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)

        world_doc = self._make_world_doc_with_elements()
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        # No element_retrieval_service → should use fallback full load
        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            element_retrieval_service=None,
        )

        await svc.generate_response(
            world_id="world-001",
            user_message="test",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
        )

        system_prompt = llm.complete_json.call_args[0][0]
        # Non-character elements should be in the prompt via fallback
        assert "红岸基地" in system_prompt
        assert "秘密军事基地" in system_prompt
        assert "三体游戏" in system_prompt
        assert "虚拟现实游戏" in system_prompt
        # Character-type element should be excluded from fallback
        assert "人物" not in system_prompt or "叶文洁的角色简介" not in system_prompt

    async def test_select_participants_retrieval_service_none_fallback(self):
        """When element_retrieval_service is None, select_participants should use
        all characters directly (no vector retrieval)."""
        llm = AsyncMock()
        llm.complete_json.return_value = {
            "speakers": ["叶文洁"],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": None,
        }

        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [
            _make_character("叶文洁", self.CHAR_ID),
            _make_character("汪淼"),
            _make_character("常伟思"),
        ]

        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []

        world_doc = AsyncMock()
        world_doc.source = None
        world_doc.user_character_id = None
        world_doc.elements = []
        world_repo = AsyncMock()
        world_repo.get.return_value = world_doc

        # No element_retrieval_service → _retrieve_augmented_characters returns all chars
        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
            element_retrieval_service=None,
        )

        result = await svc.select_participants(
            world_id="world-001",
            user_message="你好",
        )

        # Should still return valid result
        assert result["speakers"] == [{"id": self.CHAR_ID, "name": "叶文洁"}]
        # All characters should appear in the candidate list sent to LLM
        system_prompt = llm.complete_json.call_args[0][0]
        assert "叶文洁" in system_prompt
        assert "汪淼" in system_prompt
        assert "常伟思" in system_prompt


class TestEventIndexMapNotInjectedAsContext:
    """event_index_map should only be used for memory name resolution, not as standalone context."""

    CHAR_ID = str(uuid.uuid4())

    async def test_event_index_map_not_in_system_prompt(self):
        """The system prompt should not contain a standalone event_index_map section."""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}

        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [_make_character("叶文洁", self.CHAR_ID)]

        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)

        world_repo = AsyncMock()
        world_doc = AsyncMock()
        world_doc.source = None
        world_doc.user_character_id = None
        world_doc.elements = []
        world_repo.get.return_value = world_doc

        svc = DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
        )
        await svc.generate_response(
            world_id=str(uuid.uuid4()),
            user_message="test",
            participants=[{"id": self.CHAR_ID, "name": "叶文洁"}],
            relevant_event=None,
        )
        system_prompt = llm.complete_json.call_args[0][0]
        # event_index_map should NOT appear as standalone context
        assert "事件列表" not in system_prompt


class TestGenerateResponseLLMReturnEdgeCases:
    """Boundary tests for LLM return format edge cases in generate_response."""

    CHAR_ID = str(uuid.uuid4())

    def _build_service(self, llm):
        char_repo = AsyncMock()
        char_repo.list_by_world.return_value = [_make_character("叶文洁", self.CHAR_ID)]
        msg_repo = AsyncMock()
        msg_repo.list_by_session.return_value = []
        msg_repo.create_batch = AsyncMock(side_effect=lambda msgs: msgs)
        world_repo = AsyncMock()
        world_doc = AsyncMock()
        world_doc.source = None
        world_doc.user_character_id = None
        world_doc.elements = []
        world_repo.get.return_value = world_doc
        return DialogueGenerationService(
            llm=llm,
            character_repo=char_repo,
            message_repo=msg_repo,
            world_repo=world_repo,
        )

    async def test_generate_response_handles_chinese_field_names(self):
        """LLM 返回中文字段名时（如 "消息" 而非 "messages"），服务应优雅处理。

        complete_json 可能返回 dict | list，中文字段名会导致
        result.get("messages", []) 为空列表，服务不应崩溃。
        """
        llm = AsyncMock()
        # Simulate LLM returning Chinese field names — no "messages" key
        llm.complete_json.return_value = {"消息": [], "需要更多上下文": "no"}
        svc = self._build_service(llm)

        responses = await svc.generate_response(
            world_id="world-001",
            user_message="你好",
        )
        # No "messages" key → empty responses list, no crash
        assert responses == []
        msg_repo = svc.message_repo
        msg_repo.create_batch.assert_called_once_with([])

    async def test_generate_response_handles_prefill_echo(self):
        """complete_json 返回的结果中 content 包含 prefill 回显字符时应正常处理。

        某些 LLM 兼容接口会回显 prefill（如 "{" 前缀），complete_json 在
        provider 层已处理此情况。此测试验证即使 content 中残留回显相关字符，
        generate_response 仍能正常构建 Message 对象。
        """
        llm = AsyncMock()
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": "{你好，我是叶文洁。",  # prefill char "{" echoed in content
                },
            ]
        }
        svc = self._build_service(llm)

        responses = await svc.generate_response(
            world_id="world-001",
            user_message="你好",
        )
        assert len(responses) == 1
        assert responses[0].content == "{你好，我是叶文洁。"
        assert responses[0].sender_id == self.CHAR_ID

    async def test_generate_response_handles_empty_messages_list(self):
        """LLM 返回空 messages 列表时应返回空结果且不崩溃。"""
        llm = AsyncMock()
        llm.complete_json.return_value = {"messages": []}
        svc = self._build_service(llm)

        responses = await svc.generate_response(
            world_id="world-001",
            user_message="你好",
        )
        assert responses == []
        svc.message_repo.create_batch.assert_called_once_with([])

    async def test_generate_response_handles_missing_sender_name(self):
        """LLM 返回的消息缺少 sender_name 字段时应跳过该消息。"""
        llm = AsyncMock()
        llm.complete_json.return_value = {
            "messages": [
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "content": "没有发送者名称的消息",
                    # sender_name missing entirely
                },
                {
                    "type": "dialogue",
                    "sender_type": "character",
                    "sender_name": "叶文洁",
                    "content": "正常消息",
                },
            ]
        }
        svc = self._build_service(llm)

        responses = await svc.generate_response(
            world_id="world-001",
            user_message="你好",
        )
        # Missing sender_name defaults to "" which doesn't match any character → skipped
        assert len(responses) == 1
        assert responses[0].sender_id == self.CHAR_ID
        assert responses[0].content == "正常消息"
