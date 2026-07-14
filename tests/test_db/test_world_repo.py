"""WorldRepository 数据库集成测试。"""

import uuid

import pytest_asyncio
from sqlalchemy import text

from src.db.models import M9User
from src.db.repositories.world_repo import WorldRepository
from src.models.world import Element, WorldDoc, WorldMeta, WorldSource
from tests.conftest import TestSession

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID2 = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        await session.execute(text("TRUNCATE m9_users CASCADE"))
        session.add(
            M9User(id=USER_ID, username="repo_user1", email="u1@test.com", hashed_password="x")
        )
        session.add(
            M9User(id=USER_ID2, username="repo_user2", email="u2@test.com", hashed_password="x")
        )
        await session.commit()
    yield
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        await session.execute(text("TRUNCATE m9_users CASCADE"))
        await session.commit()


def _make_world(title: str = "测试世界", world_id: str | None = None) -> WorldDoc:
    wid = world_id or str(uuid.uuid4())
    return WorldDoc(
        world_id=wid,
        version="1.0",
        source=WorldSource(title=title, author="测试作者"),
        meta=WorldMeta(),
        elements=[],
    )


def _make_world_with_elements(title: str = "有元素的世界") -> WorldDoc:
    wid = str(uuid.uuid4())
    return WorldDoc(
        world_id=wid,
        version="1.0",
        source=WorldSource(title=title, author="作者"),
        meta=WorldMeta(),
        elements=[
            Element(
                id=str(uuid.uuid4()),
                category="地点",
                name="长安城",
                brief="唐朝都城",
                detail="繁华都市",
            ),
            Element(
                id=str(uuid.uuid4()),
                category="势力",
                name="朝廷",
                brief="皇权机构",
                detail="中央集权",
            ),
        ],
    )


class TestWorldRepoSave:
    async def test_save_new_world_returns_world_id(self):
        world = _make_world()
        async with TestSession() as session:
            repo = WorldRepository(session)
            result = await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        assert result == world.world_id

    async def test_save_new_world_can_be_retrieved(self):
        world = _make_world("可检索的世界")
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            doc = await repo.get(world.world_id)

        assert doc is not None
        assert doc.source.title == "可检索的世界"

    async def test_save_existing_world_updates_title(self):
        world = _make_world("原始标题")
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        world.source.title = "更新后标题"
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            doc = await repo.get(world.world_id)

        assert doc.source.title == "更新后标题"

    async def test_save_with_elements_stores_element_summary(self):
        world = _make_world_with_elements()
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        # list_by_user checks element_count from summary
        async with TestSession() as session:
            repo = WorldRepository(session)
            worlds = await repo.list_by_user(str(USER_ID))

        assert len(worlds) == 1
        assert worlds[0]["element_count"] == 2


class TestWorldRepoGet:
    async def test_get_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = WorldRepository(session)
            result = await repo.get(str(uuid.uuid4()))

        assert result is None

    async def test_get_populates_row_level_fields(self):
        world = _make_world()
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            doc = await repo.get(world.world_id)

        # Row-level fields should be populated with defaults
        assert doc.is_banned is False
        assert doc.graph_status == "idle"


class TestWorldRepoListByUser:
    async def test_list_returns_user_worlds_only(self):
        w1 = _make_world("用户1的世界")
        w2 = _make_world("用户2的世界")
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(w1, user_id=str(USER_ID))
            await repo.save(w2, user_id=str(USER_ID2))
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            worlds = await repo.list_by_user(str(USER_ID))

        assert len(worlds) == 1
        assert worlds[0]["source"]["title"] == "用户1的世界"

    async def test_list_empty_user_returns_empty(self):
        async with TestSession() as session:
            repo = WorldRepository(session)
            worlds = await repo.list_by_user(str(USER_ID))

        assert worlds == []

    async def test_list_returns_newest_first(self):
        for i in range(3):
            w = _make_world(f"世界{i}")
            async with TestSession() as session:
                repo = WorldRepository(session)
                await repo.save(w, user_id=str(USER_ID))
                await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            worlds = await repo.list_by_user(str(USER_ID))

        assert len(worlds) == 3
        # latest first
        assert worlds[0]["source"]["title"] == "世界2"

    async def test_list_contains_required_fields(self):
        w = _make_world("字段验证世界")
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(w, user_id=str(USER_ID))
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            worlds = await repo.list_by_user(str(USER_ID))

        item = worlds[0]
        assert "world_id" in item
        assert "source" in item
        assert "element_count" in item
        assert "meta" in item


class TestWorldRepoOwner:
    async def test_get_owner_id(self):
        world = _make_world()
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            owner = await repo.get_owner_id(world.world_id)

        assert owner == str(USER_ID)

    async def test_get_owner_id_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = WorldRepository(session)
            result = await repo.get_owner_id(str(uuid.uuid4()))

        assert result is None

    async def test_get_by_id_returns_m1world(self):
        world = _make_world()
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            row = await repo.get_by_id(world.world_id)

        assert row is not None
        assert str(row.user_id) == str(USER_ID)

    async def test_get_by_id_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = WorldRepository(session)
            result = await repo.get_by_id(str(uuid.uuid4()))

        assert result is None


class TestWorldRepoDelete:
    async def test_delete_world(self):
        world = _make_world()
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(world, user_id=str(USER_ID))
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            deleted = await repo.delete(world.world_id)
            await session.commit()

        assert deleted is True

        async with TestSession() as session:
            repo = WorldRepository(session)
            result = await repo.get(world.world_id)

        assert result is None

    async def test_delete_nonexistent_returns_false(self):
        async with TestSession() as session:
            repo = WorldRepository(session)
            result = await repo.delete(str(uuid.uuid4()))

        assert result is False
