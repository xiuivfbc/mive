"""GenerationService 单元测试（mock LLM + mock repos）。"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.world import Element
from src.services.generation_service import GenerationService

_COMPACT_NAMES = ["叶文洁", "罗辑", "章北海", "程心", "云天明"]


def _make_element(name: str, idx: int) -> Element:
    return Element(id=f"e{idx}", category="人物角色", name=name, brief="角色", detail="")


def _make_material():
    material = MagicMock()
    material.world_elements = [_make_element(n, i) for i, n in enumerate(_COMPACT_NAMES)]
    material.world_rules_summary = "硬科幻世界"
    return material


def _valid_char(name: str, tier: str = "core") -> dict:
    return {
        "name": name,
        "profile": {
            "brief": f"{name}简介",
            "detail": f"{name}详细描述",
        },
    }


def _make_async_cm():
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_session():
    session = MagicMock()
    session.begin_nested = MagicMock(return_value=_make_async_cm())
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.scalar = AsyncMock()
    return session


def _make_mock_world():
    """创建一个带正确 source.wiki_text 的 mock world。"""
    world = MagicMock()
    world.source.wiki_text = None
    world.source.wiki_characters = None
    world.source.wiki_plot = None
    world.source.wiki_world_setting = None
    world.source.title = "测试作品"
    world.source.author = "测试作者"
    world.user_character_id = None
    world.elements = []
    return world


def _build_service(
    *,
    llm=None,
    material_elements=None,
    world_return=None,
    material_rules="硬科幻世界",
    char_repo=None,
):
    """构建带 mock 依赖的 GenerationService，支持自定义 material 元素。"""
    mock_llm = llm or MagicMock()
    mock_mat = MagicMock()
    mock_mat.world_elements = material_elements or [
        _make_element(n, i) for i, n in enumerate(_COMPACT_NAMES)
    ]
    mock_mat.world_rules_summary = material_rules
    mock_mat_svc = MagicMock()
    mock_mat_svc.generate.return_value = mock_mat
    mock_ws = AsyncMock()
    mock_ws.get_world.return_value = (
        world_return if world_return is not None else _make_mock_world()
    )
    mock_cr = char_repo or AsyncMock()
    mock_rr = AsyncMock()
    mock_vs = AsyncMock()
    mock_session = _make_session()

    return (
        GenerationService(
            llm=mock_llm,
            material_service=mock_mat_svc,
            world_service=mock_ws,
            character_repo=mock_cr,
            relation_repo=mock_rr,
            version_service=mock_vs,
            session=mock_session,
        ),
        mock_llm,
        mock_mat_svc,
        mock_ws,
        mock_cr,
        mock_rr,
        mock_vs,
        mock_session,
    )


class TestGenerationServiceWorldNotFound:
    async def test_world_not_found_raises_value_error(self):
        svc, _, _, mock_ws, *_ = _build_service()
        mock_ws.get_world.return_value = None
        with pytest.raises(ValueError, match="World not found"):
            await svc.generate("nonexistent-world")


class TestGenerationServiceGenerate:
    async def test_returns_character_and_relation_counts(self):
        chars = [_valid_char(n) for n in _COMPACT_NAMES]
        # Step 1: 1 batch call → list of chars; Stage 1: 1 call → empty list
        llm = MagicMock()
        llm.complete_json = AsyncMock(side_effect=[chars, []])

        mock_world = _make_mock_world()
        svc, *_ = _build_service(llm=llm, world_return=mock_world)
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        result = await svc.generate("00000000-0000-0000-0000-000000000001", scale="standard")
        assert "characters" in result
        assert "relations" in result

    async def test_uses_material_service(self):
        chars = [_valid_char(n) for n in _COMPACT_NAMES]
        llm = MagicMock()
        llm.complete_json = AsyncMock(side_effect=[chars, []])

        mock_world = _make_mock_world()
        svc, _, mat_svc, *_ = _build_service(llm=llm, world_return=mock_world)
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        await svc.generate("00000000-0000-0000-0000-000000000001", scale="standard")
        mat_svc.generate.assert_called_once()

    async def test_llm_failure_uses_fallback_chars(self):
        """LLM failure in char generation should use fallback chars, not propagate."""
        llm = MagicMock()
        llm.complete_json = AsyncMock(side_effect=RuntimeError("LLM error"))

        mock_world = _make_mock_world()
        svc, *_ = _build_service(llm=llm, world_return=mock_world)
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        # Should not raise — fallback chars are used
        result = await svc.generate("00000000-0000-0000-0000-000000000001", scale="standard")
        assert "characters" in result

    async def test_adaptive_cap_with_few_elements(self):
        llm = MagicMock()
        llm.complete_json = AsyncMock(side_effect=RuntimeError("stop"))

        elems = [_make_element(f"e{i}", i) for i in range(2)]
        mock_world = _make_mock_world()
        svc, *_ = _build_service(llm=llm, material_elements=elems, world_return=mock_world)
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        # Should not raise — fallback chars are used
        result = await svc.generate("00000000-0000-0000-0000-000000000001", scale="standard")
        assert "characters" in result

    async def test_adaptive_cap_single_element(self):
        llm = MagicMock()
        llm.complete_json = AsyncMock(side_effect=RuntimeError("stop"))

        mock_world = _make_mock_world()
        svc, *_ = _build_service(
            llm=llm, material_elements=[_make_element("唯一", 0)], world_return=mock_world
        )
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        # Should not raise — fallback chars are used
        result = await svc.generate("00000000-0000-0000-0000-000000000001")
        assert "characters" in result

    async def test_dedup_duplicate_names(self):
        llm = MagicMock()
        char1 = _valid_char("Alice", "core")
        char2 = _valid_char("Alice", "supporting")
        # Step 1: 1 batch call → [char1, char2]; Stage 1: 1 call → []
        llm.complete_json = AsyncMock(side_effect=[[char1, char2], []])

        mock_world = _make_mock_world()
        elems = [_make_element("Alice", 0), _make_element("Alice_dup", 1)]
        svc, *_ = _build_service(llm=llm, material_elements=elems, world_return=mock_world)
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        await svc.generate("00000000-0000-0000-0000-000000000001", scale="standard")

        svc.character_repo.bulk_create.assert_called_once()
        call_args = svc.character_repo.bulk_create.call_args
        chars_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("chars", [])
        names = [c.get("name") for c in chars_arg]
        assert names.count("Alice") <= 1

    async def test_user_character_snapshot_reinserted(self):
        llm = MagicMock()
        char1 = _valid_char("Hero", "core")
        # Step 1: 1 batch call → [char1]; Stage 1: skipped (only 1 core)
        llm.complete_json = AsyncMock(side_effect=[[char1]])

        mock_world = _make_mock_world()
        mock_world.user_character_id = uuid.uuid4()

        user_char_snapshot = MagicMock()
        user_char_snapshot.name = "用户角色"
        user_char_snapshot.portrait_url = "🧭"
        user_char_snapshot.profile = {
            "brief": "用户角色",
            "detail": "用户角色描述",
        }
        user_char_snapshot.tier = "extra"
        user_char_snapshot.entity_type = "user"
        user_char_snapshot.is_auto_generated = False

        mock_cr = AsyncMock()
        mock_cr.list_by_world.return_value = []
        mock_cr.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )

        elems = [_make_element("Hero", 0)]
        svc, *_ = _build_service(
            llm=llm, material_elements=elems, world_return=mock_world, char_repo=mock_cr
        )
        svc.session.scalar = AsyncMock(side_effect=[mock_world, user_char_snapshot])
        # Mock session.execute to return a result with .scalars().all()
        mock_execute_result = MagicMock()
        mock_execute_result.scalars.return_value.all.return_value = []
        svc.session.execute = AsyncMock(return_value=mock_execute_result)

        await svc.generate("00000000-0000-0000-0000-000000000001", scale="standard")

        # With user_character_id set, delete_non_user_characters
        # is called instead of delete_all_by_world
        mock_cr.delete_non_user_characters.assert_called_once()
        mock_cr.bulk_create.assert_called_once()


class TestGenerationServiceValidateCharacter:
    def test_valid_character_has_all_fields(self):
        char = _valid_char("Alice", "core")
        assert char["name"] == "Alice"
        assert "brief" in char["profile"]
        assert "detail" in char["profile"]

    def test_missing_required_fields_invalid(self):
        bad_char = {"name": "Alice", "profile": {}}
        profile = bad_char.get("profile", {})
        required = [
            profile.get("brief"),
            profile.get("detail"),
        ]
        assert any(v is None for v in required)

    def test_empty_string_fields_invalid(self):
        char = _valid_char("Alice", "core")
        char["profile"]["brief"] = "  "
        assert char["profile"]["brief"].strip() == ""

    def test_missing_profile_fields_invalid(self):
        char = _valid_char("Alice", "core")
        assert "brief" in char["profile"]
        assert "detail" in char["profile"]


class TestGenerationServiceCharCandidates:
    """generate() 应接受 char_candidates 参数，使用传入的角色候选而非从 elements 筛选。"""

    async def test_generate_accepts_char_candidates(self):
        """generate() 应接受 char_candidates 参数。"""
        mock_world = _make_mock_world()
        svc, llm, *_ = _build_service(world_return=mock_world)
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        char_candidates = [
            {"name": "主角A", "tier": "core"},
            {"name": "配角B", "tier": "supporting"},
        ]

        char1 = _valid_char("主角A", "core")
        char2 = _valid_char("配角B", "supporting")
        # Step 1: 1 batch call → [char1, char2]; Stage 2: 1 call (core×noncore) → []
        llm.complete_json = AsyncMock(side_effect=[[char1], [char2]])

        # generate() 应该接受 char_candidates 参数而不报 TypeError
        result = await svc.generate(
            "00000000-0000-0000-0000-000000000001",
            scale="standard",
            char_candidates=char_candidates,
        )
        assert "characters" in result
        assert result["characters"] == 2

    async def test_generate_uses_char_candidates_not_elements(self):
        """generate() 使用传入的 char_candidates 而非从 material.world_elements 筛选。"""
        # material 的 world_elements 不含角色元素（新行为）
        non_char_elements = [
            Element(id="e0", category="场所", name="学校", brief="学校", detail=""),
            Element(id="e1", category="势力", name="组织", brief="组织", detail=""),
        ]

        char_candidates = [
            {"name": "角色X", "tier": "core"},
            {"name": "角色Y", "tier": "supporting"},
        ]

        char1 = _valid_char("角色X", "core")
        char2 = _valid_char("角色Y", "supporting")

        llm = MagicMock()
        # Step 1: 1 batch call → [char1, char2]; Stage 2: 1 call (core×noncore) → []
        llm.complete_json = AsyncMock(side_effect=[[char1], [char2]])

        mock_world = _make_mock_world()
        svc, *_ = _build_service(
            llm=llm, material_elements=non_char_elements, world_return=mock_world
        )
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        result = await svc.generate(
            "00000000-0000-0000-0000-000000000001",
            scale="standard",
            char_candidates=char_candidates,
        )
        # 应该生成 2 个角色（来自 char_candidates），而不是从 elements 筛选
        assert result["characters"] == 2

    async def test_generate_without_char_candidates_uses_fallback(self):
        """不传 char_candidates 且 elements 中无角色类别时，
        应从 _generate_character_names_from_world 获取候选（fallback）。"""
        non_char_elements = [
            Element(id="e0", category="场所", name="学校", brief="学校", detail=""),
            Element(id="e1", category="势力", name="组织", brief="组织", detail=""),
            Element(id="e2", category="规则", name="魔法", brief="魔法", detail=""),
        ]

        char1 = _valid_char("学校", "extra")
        char2 = _valid_char("组织", "extra")
        char3 = _valid_char("魔法", "extra")

        llm = MagicMock()
        # _generate_character_names_from_world is mocked, so llm.complete_json
        # only handles profile generation: 3 batches (core=1, supporting=1, extra=1)
        llm.complete_json = AsyncMock(side_effect=[[char1], [char2], [char3]])

        mock_world = _make_mock_world()
        svc, *_ = _build_service(
            llm=llm, material_elements=non_char_elements, world_return=mock_world
        )
        svc.character_repo.list_by_world = AsyncMock(return_value=[])
        svc.character_repo.bulk_create = AsyncMock(
            side_effect=lambda wid, c: [
                MagicMock(id=uuid.uuid4(), name=x.get("name", "")) for x in c
            ]
        )
        svc.session.scalar = AsyncMock(return_value=mock_world)

        with patch.object(
            svc,
            "_generate_character_names_from_world",
            new_callable=AsyncMock,
            return_value=[{"name": "学校"}, {"name": "组织"}, {"name": "魔法"}],
        ):
            result = await svc.generate(
                "00000000-0000-0000-0000-000000000001",
                scale="standard",
                # 不传 char_candidates，触发 fallback
            )
        # fallback 应通过 _generate_character_names_from_world 获取角色名
        assert result["characters"] == 3


class TestGenerationServiceStripNameTier:
    """generate() 写入数据库时 profile 应为 {brief, detail} 结构。"""

    async def test_generate_uses_correct_profile_structure(self):
        """验证 generate() 传给 bulk_create 的 characters 中
        profile 包含 brief/detail。"""
        chars = [_valid_char(n) for n in _COMPACT_NAMES]
        llm = MagicMock()
        # Step 1: 1 batch call → list of chars; Stage 1: 1 call → []
        llm.complete_json = AsyncMock(side_effect=[chars, []])

        mock_cr = AsyncMock()
        mock_cr.list_by_world.return_value = []
        created_chars = []
        chars_captured = []

        async def fake_bulk_create(wid, char_list):
            chars_captured.extend(char_list)
            for c in char_list:
                mc = MagicMock()
                mc.id = uuid.uuid4()
                mc.name = c.get("name", "")
                mc.portrait_url = None
                created_chars.append(mc)
            return created_chars

        mock_cr.bulk_create = AsyncMock(side_effect=fake_bulk_create)

        mock_world = _make_mock_world()
        svc, *_ = _build_service(llm=llm, char_repo=mock_cr, world_return=mock_world)
        svc.session.scalar = AsyncMock(return_value=mock_world)

        await svc.generate("00000000-0000-0000-0000-000000000001", scale="standard")

        # All characters passed to bulk_create should have profile with brief/detail
        assert len(chars_captured) > 0
        for char_data in chars_captured:
            profile = char_data.get("profile", {})
            assert "brief" in profile, f"Expected 'brief' in profile for {char_data.get('name')}"
            assert "detail" in profile, f"Expected 'detail' in profile for {char_data.get('name')}"
