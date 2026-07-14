import uuid

import pytest_asyncio
from sqlalchemy import text

from src.db.models import M1World, M2Character
from src.db.repositories.character_repo import CharacterRepository
from src.models.character import CreateCharacterRequest, UpdateCharacterRequest
from tests.conftest import TestSession

WORLD_ID = uuid.uuid4()


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    """清理测试数据，使用 TRUNCATE CASCADE 避免 FK 顺序问题"""
    async with TestSession() as session:
        # TRUNCATE CASCADE clears all FK-dependent tables in one shot
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        # 插入测试用的 world
        session.add(
            M1World(
                id=WORLD_ID,
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                title="测试世界",
                world_doc={"world_id": str(WORLD_ID), "source": {}, "meta": {}, "elements": []},
            )
        )
        await session.commit()
    yield
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        await session.commit()


class TestCharacterRepoCreate:
    async def test_create_returns_character(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            result = await repo.create(
                str(WORLD_ID),
                CreateCharacterRequest(name="叶文洁"),
            )
            assert result.name == "叶文洁"
            assert result.id is not None
            assert result.world_id == str(WORLD_ID)

    async def test_create_persists_to_db(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            created = await repo.create(
                str(WORLD_ID),
                CreateCharacterRequest(name="叶文洁"),
            )
            await session.commit()

        async with TestSession() as session:
            repo = CharacterRepository(session)
            fetched = await repo.get_by_id(created.id)
            assert fetched is not None
            assert fetched.name == "叶文洁"

    async def test_create_strips_name_tier_from_profile(self):
        """create() 应从 profile.basic 中 strip 掉 name 和 tier，与 bulk_create 一致。"""
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
        async with TestSession() as session:
            repo = CharacterRepository(session)
            result = await repo.create(
                str(WORLD_ID),
                CreateCharacterRequest(name="叶文洁", profile=profile_with_name_tier),
            )
            await session.commit()

        # profile.basic should NOT contain name or tier
        basic = result.profile.get("basic", {})
        assert "name" not in basic, f"Expected no 'name' in profile.basic, got: {basic}"
        assert "tier" not in basic, f"Expected no 'tier' in profile.basic, got: {basic}"
        # Other basic fields should remain
        assert basic.get("gender") == "女"
        assert basic.get("age") == 30
        assert basic.get("occupation") == "研究员"
        # Row-level tier should be set
        assert result.tier == "core"
        # Other profile-level fields should remain
        assert result.profile.get("brief") == "天体物理学家"

    async def test_create_preserves_profile_without_basic(self):
        """profile 没有 basic 时 create() 不报错。"""
        async with TestSession() as session:
            repo = CharacterRepository(session)
            result = await repo.create(
                str(WORLD_ID),
                CreateCharacterRequest(name="叶文洁", profile={"brief": "只有简介"}),
            )
            assert result.profile == {"brief": "只有简介"}
            assert result.tier is None


class TestCharacterRepoGetById:
    async def test_get_existing(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            created = await repo.create(
                str(WORLD_ID),
                CreateCharacterRequest(name="叶文洁"),
            )
            await session.commit()

        async with TestSession() as session:
            repo = CharacterRepository(session)
            result = await repo.get_by_id(created.id)
            assert result is not None
            assert result.name == "叶文洁"

    async def test_get_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            result = await repo.get_by_id(str(uuid.uuid4()))
            assert result is None


class TestCharacterRepoListByWorld:
    async def test_list_returns_all_for_world(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            await repo.create(str(WORLD_ID), CreateCharacterRequest(name="叶文洁"))
            await repo.create(str(WORLD_ID), CreateCharacterRequest(name="汪淼"))
            await session.commit()

        async with TestSession() as session:
            repo = CharacterRepository(session)
            results = await repo.list_by_world(str(WORLD_ID))
            assert len(results) == 2
            names = {c.name for c in results}
            assert names == {"叶文洁", "汪淼"}

    async def test_list_excludes_other_worlds(self):
        other_world_id = uuid.uuid4()
        async with TestSession() as session:
            session.add(
                M1World(
                    id=other_world_id,
                    user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                    title="另一个世界",
                    world_doc={},
                )
            )
            await session.commit()

        async with TestSession() as session:
            repo = CharacterRepository(session)
            await repo.create(str(WORLD_ID), CreateCharacterRequest(name="叶文洁"))
            await repo.create(str(other_world_id), CreateCharacterRequest(name="罗辑"))
            await session.commit()

        async with TestSession() as session:
            repo = CharacterRepository(session)
            results = await repo.list_by_world(str(WORLD_ID))
            assert all(c.name != "罗辑" for c in results)

            # cleanup
            await session.execute(M2Character.__table__.delete())
            await session.execute(M1World.__table__.delete().where(M1World.id == other_world_id))
            await session.commit()


class TestCharacterRepoUpdate:
    async def test_update_modifies_fields(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            created = await repo.create(
                str(WORLD_ID),
                CreateCharacterRequest(name="叶文洁"),
            )
            await session.commit()

        async with TestSession() as session:
            repo = CharacterRepository(session)
            updated = await repo.update(
                created.id,
                UpdateCharacterRequest(
                    name="叶文洁v2",
                    profile={"brief": "天体物理学家"},
                ),
            )
            assert updated is not None
            assert updated.name == "叶文洁v2"
            assert updated.profile["brief"] == "天体物理学家"

    async def test_update_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            result = await repo.update(
                str(uuid.uuid4()),
                UpdateCharacterRequest(name="不存在"),
            )
            assert result is None


class TestCharacterRepoDelete:
    async def test_delete_existing_returns_true(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            created = await repo.create(
                str(WORLD_ID),
                CreateCharacterRequest(name="叶文洁"),
            )
            await session.commit()

        async with TestSession() as session:
            repo = CharacterRepository(session)
            result = await repo.delete(created.id)
            assert result is True
            await session.commit()

        async with TestSession() as session:
            repo = CharacterRepository(session)
            assert await repo.get_by_id(created.id) is None

    async def test_delete_nonexistent_returns_false(self):
        async with TestSession() as session:
            repo = CharacterRepository(session)
            result = await repo.delete(str(uuid.uuid4()))
            assert result is False


class TestCharacterRepoBulkCreateStripNameTier:
    """bulk_create 应从 profile.basic 中 strip 掉 name 和 tier。"""

    async def test_bulk_create_strips_name_tier_from_profile(self):
        chars = [
            {
                "id": str(uuid.uuid4()),
                "name": "叶文洁",
                "profile": {
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
                },
            },
            {
                "id": str(uuid.uuid4()),
                "name": "罗辑",
                "profile": {
                    "basic": {
                        "name": "罗辑",
                        "gender": "男",
                        "age": 35,
                        "occupation": "社会学教授",
                        "race": "人类",
                        "tier": "supporting",
                    },
                    "brief": "面壁者",
                    "detail": "详细描述",
                },
            },
        ]
        async with TestSession() as session:
            repo = CharacterRepository(session)
            created = await repo.bulk_create(str(WORLD_ID), chars)
            await session.commit()

        # Verify profile.basic does NOT contain name or tier
        for char in created:
            basic = char.profile.get("basic", {})
            assert "name" not in basic, (
                f"Expected no 'name' in profile.basic for {char.name}, got: {basic}"
            )
            assert "tier" not in basic, (
                f"Expected no 'tier' in profile.basic for {char.name}, got: {basic}"
            )
            # Other fields should remain
            assert basic.get("gender") in ("男", "女")
            assert basic.get("age") > 0

        # Verify row-level tier is set
        assert created[0].tier == "core"
        assert created[1].tier == "supporting"

    async def test_bulk_create_preserves_other_profile_fields(self):
        """Strip 后，basic 中其他字段和 profile 层字段不受影响。"""
        chars = [
            {
                "id": str(uuid.uuid4()),
                "name": "程心",
                "profile": {
                    "basic": {
                        "name": "程心",
                        "gender": "女",
                        "age": 28,
                        "occupation": "航天工程师",
                        "race": "人类",
                        "tier": "extra",
                    },
                    "brief": "执剑人",
                    "detail": "详细描述",
                },
            },
        ]
        async with TestSession() as session:
            repo = CharacterRepository(session)
            created = await repo.bulk_create(str(WORLD_ID), chars)
            await session.commit()

        char = created[0]
        basic = char.profile.get("basic", {})
        assert "name" not in basic
        assert "tier" not in basic
        assert basic.get("gender") == "女"
        assert basic.get("occupation") == "航天工程师"
        assert char.profile.get("brief") == "执剑人"
        assert char.profile.get("brief") == "执剑人"
        assert char.tier == "extra"
