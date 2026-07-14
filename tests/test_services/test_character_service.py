import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.models.character import Character, CreateCharacterRequest, UpdateCharacterRequest
from src.services.character_service import CharacterService


def _make_character(name="叶文洁") -> Character:
    return Character(
        id=str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        profile={"basic": {"name": name}, "brief": "", "detail": ""},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class TestCharacterServiceCreate:
    async def test_create_returns_character(self):
        expected = _make_character()
        mock_repo = AsyncMock()
        mock_repo.create.return_value = expected
        service = CharacterService(mock_repo)

        result = await service.create(str(uuid.uuid4()), CreateCharacterRequest(name="叶文洁"))

        assert result.name == "叶文洁"
        assert result.id == expected.id

    async def test_create_delegates_to_repo(self):
        mock_repo = AsyncMock()
        mock_repo.create.return_value = _make_character()
        service = CharacterService(mock_repo)

        world_id = str(uuid.uuid4())
        await service.create(world_id, CreateCharacterRequest(name="叶文洁"))

        mock_repo.create.assert_called_once()
        call_args = mock_repo.create.call_args
        assert call_args[0][0] == world_id


class TestCharacterServiceGet:
    async def test_get_returns_character(self):
        expected = _make_character()
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = expected
        service = CharacterService(mock_repo)

        result = await service.get(expected.id)
        assert result is not None
        assert result.name == "叶文洁"

    async def test_get_not_found_returns_none(self):
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None
        service = CharacterService(mock_repo)

        result = await service.get(str(uuid.uuid4()))
        assert result is None


class TestCharacterServiceList:
    async def test_list_returns_characters(self):
        chars = [_make_character("叶文洁"), _make_character("汪淼")]
        mock_repo = AsyncMock()
        mock_repo.list_by_world.return_value = chars
        service = CharacterService(mock_repo)

        result = await service.list_by_world(str(uuid.uuid4()))
        assert len(result) == 2


class TestCharacterServiceUpdate:
    async def test_update_returns_updated_character(self):
        expected = _make_character("叶文洁v2")
        mock_repo = AsyncMock()
        mock_repo.update.return_value = expected
        service = CharacterService(mock_repo)

        result = await service.update(expected.id, UpdateCharacterRequest(name="叶文洁v2"))
        assert result is not None
        assert result.name == "叶文洁v2"

    async def test_update_not_found_returns_none(self):
        mock_repo = AsyncMock()
        mock_repo.update.return_value = None
        service = CharacterService(mock_repo)

        result = await service.update(str(uuid.uuid4()), UpdateCharacterRequest(name="x"))
        assert result is None


class TestCharacterServiceDelete:
    async def test_delete_returns_true(self):
        mock_repo = AsyncMock()
        mock_repo.delete.return_value = True
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result
        service = CharacterService(mock_repo, session=mock_session)

        char_id = str(uuid.uuid4())
        mock_repo.get_by_id.return_value = Character(
            id=char_id,
            world_id=str(uuid.uuid4()),
            name="test",
            profile={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        result = await service.delete(char_id)
        assert result is True

    async def test_delete_not_found_returns_false(self):
        mock_repo = AsyncMock()
        mock_repo.delete.return_value = False
        mock_repo.get_by_id.return_value = None
        service = CharacterService(mock_repo)

        result = await service.delete(str(uuid.uuid4()))
        assert result is False


class TestCharacterServiceStripNameTier:
    """profile.basic 中的 name 和 tier 应被 strip，写入时不再存入 profile JSONB。"""

    async def test_create_strips_name_tier(self):
        """create() 应从 profile.basic 中 strip 掉 name 和 tier。"""
        captured_req = {}

        async def fake_create(world_id, req):
            captured_req["req"] = req
            return _make_character("叶文洁")

        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(side_effect=fake_create)
        service = CharacterService(mock_repo)

        profile_with_name_tier = {
            "basic": {
                "name": "叶文洁",
                "gender": "女",
                "age": 30,
                "occupation": "研究员",
                "race": "人类",
                "tier": "core",
            },
            "brief": "天体物理学家",
            "detail": "详细描述",
        }
        await service.create(
            str(uuid.uuid4()),
            CreateCharacterRequest(name="叶文洁", profile=profile_with_name_tier),
        )

        req = captured_req["req"]
        basic = req.profile.get("basic", {})
        assert "name" not in basic, f"profile.basic should not contain 'name', got: {basic}"
        assert "tier" not in basic, f"profile.basic should not contain 'tier', got: {basic}"
        # Other fields should remain
        assert basic.get("gender") == "女"
        assert basic.get("age") == 30

    async def test_update_strips_name_tier(self):
        """update() 应从 profile.basic 中 strip 掉 name 和 tier。"""
        captured_req = {}

        async def fake_update(char_id, req, fields_set=None):
            captured_req["req"] = req
            return _make_character("叶文洁v2")

        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock(side_effect=fake_update)
        service = CharacterService(mock_repo)

        profile_with_name_tier = {
            "basic": {
                "name": "叶文洁",
                "gender": "女",
                "age": 30,
                "occupation": "研究员",
                "race": "人类",
                "tier": "supporting",
            },
            "brief": "简介",
            "detail": "详情",
        }
        await service.update(
            str(uuid.uuid4()),
            UpdateCharacterRequest(profile=profile_with_name_tier),
        )

        req = captured_req["req"]
        basic = req.profile.get("basic", {})
        assert "name" not in basic, f"profile.basic should not contain 'name', got: {basic}"
        assert "tier" not in basic, f"profile.basic should not contain 'tier', got: {basic}"
        assert basic.get("gender") == "女"

    async def test_update_without_profile_strips_nothing(self):
        """update() 不传 profile 时不做任何 strip。"""
        mock_repo = AsyncMock()
        mock_repo.update.return_value = _make_character("叶文洁")
        service = CharacterService(mock_repo)

        await service.update(str(uuid.uuid4()), UpdateCharacterRequest(name="新名字"))
        mock_repo.update.assert_called_once()

    async def test_update_profile_without_basic_skips_strip(self):
        """profile 没有 basic 时 strip 不报错。"""
        captured_req = {}

        async def fake_update(char_id, req, fields_set=None):
            captured_req["req"] = req
            return _make_character("叶文洁")

        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock(side_effect=fake_update)
        service = CharacterService(mock_repo)

        await service.update(
            str(uuid.uuid4()),
            UpdateCharacterRequest(profile={"brief": "只有简介"}),
        )
        req = captured_req["req"]
        assert req.profile == {"brief": "只有简介"}
