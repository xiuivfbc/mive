"""GraphCommandService 单元测试（mock LLM + repo）。"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from src.services.graph_command_service import GraphCommandService, _clean_command

WORLD_ID = "00000000-0000-0000-0000-000000000001"
CHAR_A_ID = str(uuid.uuid4())
CHAR_B_ID = str(uuid.uuid4())


def _make_char(name: str, cid: str = None):
    c = MagicMock()
    c.id = cid or str(uuid.uuid4())
    c.name = name
    c.profile = {"brief": f"{name} brief"}
    return c


def _make_rel(char_a: str, char_b: str, rel_type: str = "朋友"):
    r = MagicMock()
    r.id = str(uuid.uuid4())
    r.character_a = char_a
    r.character_b = char_b
    r.type = rel_type
    r.description = ""
    r.direction = "bidirectional"
    return r


def _make_nested_cm():
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_service(llm_response: dict | None = None):
    llm = AsyncMock()
    llm.complete_json = AsyncMock(
        return_value=llm_response or {"operations": [], "summary": "无操作"}
    )

    mock_session = AsyncMock()
    mock_session.begin_nested = MagicMock(return_value=_make_nested_cm())

    char_repo = AsyncMock()
    char_repo.session = mock_session
    rel_repo = AsyncMock()

    svc = GraphCommandService(llm=llm, char_repo=char_repo, rel_repo=rel_repo)

    # Patch internal services so we control them
    svc.char_service = AsyncMock()
    svc.rel_service = AsyncMock()

    return svc, llm


class TestCleanCommand:
    def test_removes_at_sign(self):
        assert "@" not in _clean_command("@Alice 和 @Bob 相爱")

    def test_collapses_repeated_comma(self):
        result = _clean_command("删除，，，关系")
        assert "，，" not in result

    def test_collapses_repeated_period(self):
        result = _clean_command("完成。。。")
        assert "。。" not in result

    def test_strips_whitespace(self):
        result = _clean_command("  hello  world  ")
        assert result == "hello world"

    def test_preserves_chinese_text(self):
        result = _clean_command("添加角色 Alice")
        assert "添加角色" in result
        assert "Alice" in result


class TestParse:
    async def test_parse_returns_operations(self):
        ops = [{"op": "add_character", "name": "Alice", "tier": "core"}]
        svc, llm = _make_service({"operations": ops, "summary": "添加角色"})
        svc.char_service.list_by_world = AsyncMock(return_value=[])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])

        result = await svc.parse(WORLD_ID, "添加角色Alice")

        assert result["operations"] == ops
        llm.complete_json.assert_called_once()

    async def test_parse_injects_char_list_into_prompt(self):
        char = _make_char("叶文洁")
        svc, llm = _make_service({"operations": [], "summary": ""})
        svc.char_service.list_by_world = AsyncMock(return_value=[char])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])

        await svc.parse(WORLD_ID, "删除@叶文洁")

        call_kwargs = llm.complete_json.call_args
        prompt_text = str(call_kwargs)
        assert "叶文洁" in prompt_text

    async def test_parse_filters_relevant_relations_for_mentioned_chars(self):
        char_a = _make_char("Alice", CHAR_A_ID)
        char_b = _make_char("Bob", CHAR_B_ID)
        rel = _make_rel(CHAR_A_ID, CHAR_B_ID, "朋友")

        svc, llm = _make_service({"operations": [], "summary": ""})
        svc.char_service.list_by_world = AsyncMock(return_value=[char_a, char_b])
        svc.rel_service.list_by_world = AsyncMock(return_value=[rel])

        await svc.parse(WORLD_ID, "@Alice 与 @Bob 分手")

        prompt_text = str(llm.complete_json.call_args)
        assert "Alice" in prompt_text
        assert "朋友" in prompt_text

    async def test_parse_empty_command_returns_no_ops(self):
        svc, llm = _make_service({"operations": [], "summary": "无"})
        svc.char_service.list_by_world = AsyncMock(return_value=[])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])

        result = await svc.parse(WORLD_ID, "")
        assert result["operations"] == []


class TestApply:
    async def test_apply_add_character(self):
        char_a = _make_char("Alice", CHAR_A_ID)
        new_char = _make_char("NewGuy")
        ops = [
            {
                "op": "add_character",
                "name": "NewGuy",
                "tier": "extra",
                "gender": "unknown",
                "age": None,
                "occupation": "学生",
                "brief": "新角色",
            }
        ]

        svc, _ = _make_service()
        svc.char_service.list_by_world = AsyncMock(return_value=[char_a])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])
        svc.char_service.create = AsyncMock(return_value=new_char)

        result = await svc.apply(WORLD_ID, ops)

        assert "NewGuy" in result["added_chars"]
        svc.char_service.create.assert_called_once()

    async def test_apply_delete_character(self):
        char_a = _make_char("Alice", CHAR_A_ID)
        ops = [{"op": "delete_character", "name": "Alice"}]

        svc, _ = _make_service()
        svc.char_service.list_by_world = AsyncMock(return_value=[char_a])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])
        svc.rel_service.delete_by_character = AsyncMock()
        svc.char_service.delete = AsyncMock()

        result = await svc.apply(WORLD_ID, ops)

        assert result["errors"] == []
        svc.char_service.delete.assert_called_once_with(char_a.id)

    async def test_apply_delete_nonexistent_character_returns_error(self):
        ops = [{"op": "delete_character", "name": "GhostChar"}]

        svc, _ = _make_service()
        svc.char_service.list_by_world = AsyncMock(return_value=[])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])

        result = await svc.apply(WORLD_ID, ops)

        assert len(result["errors"]) == 1
        assert "GhostChar" in result["errors"][0]

    async def test_apply_add_relation(self):
        char_a = _make_char("Alice", CHAR_A_ID)
        char_b = _make_char("Bob", CHAR_B_ID)
        ops = [
            {
                "op": "add_relation",
                "character_a": "Alice",
                "character_b": "Bob",
                "type": "友人",
                "description": "旧识",
                "direction": "bidirectional",
            }
        ]

        svc, _ = _make_service()
        svc.char_service.list_by_world = AsyncMock(return_value=[char_a, char_b])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])
        svc.rel_service.create = AsyncMock(return_value=MagicMock())

        result = await svc.apply(WORLD_ID, ops)

        assert result["errors"] == []
        svc.rel_service.create.assert_called_once()

    async def test_apply_delete_relation(self):
        char_a = _make_char("Alice", CHAR_A_ID)
        char_b = _make_char("Bob", CHAR_B_ID)
        rel = _make_rel(CHAR_A_ID, CHAR_B_ID, "仇敌")
        ops = [{"op": "delete_relation", "character_a": "Alice", "character_b": "Bob"}]

        svc, _ = _make_service()
        svc.char_service.list_by_world = AsyncMock(return_value=[char_a, char_b])
        svc.rel_service.list_by_world = AsyncMock(return_value=[rel])
        svc.rel_service.delete = AsyncMock()

        result = await svc.apply(WORLD_ID, ops)

        assert result["errors"] == []
        svc.rel_service.delete.assert_called_once_with(rel.id)

    async def test_apply_update_character(self):
        char_a = _make_char("Alice", CHAR_A_ID)
        ops = [{"op": "update_character", "name": "Alice", "changes": {"brief": "新简介"}}]

        svc, _ = _make_service()
        svc.char_service.list_by_world = AsyncMock(return_value=[char_a])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])
        svc.char_service.update = AsyncMock(return_value=char_a)

        result = await svc.apply(WORLD_ID, ops)

        assert result["errors"] == []
        svc.char_service.update.assert_called_once()

    async def test_apply_multiple_ops(self):
        char_a = _make_char("Alice", CHAR_A_ID)
        new_char = _make_char("Bob")
        ops = [
            {
                "op": "add_character",
                "name": "Bob",
                "tier": "supporting",
                "gender": "male",
                "age": None,
                "occupation": "",
                "brief": "",
            },
            {"op": "delete_character", "name": "Alice"},
        ]

        svc, _ = _make_service()
        svc.char_service.list_by_world = AsyncMock(return_value=[char_a])
        svc.rel_service.list_by_world = AsyncMock(return_value=[])
        svc.char_service.create = AsyncMock(return_value=new_char)
        svc.rel_service.delete_by_character = AsyncMock()
        svc.char_service.delete = AsyncMock()

        result = await svc.apply(WORLD_ID, ops)

        assert result["errors"] == []
        assert "Bob" in result["added_chars"]
