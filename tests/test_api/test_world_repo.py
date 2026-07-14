"""Integration tests for WorldRepository - requires Docker PostgreSQL."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from src.db.repositories.world_repo import WorldRepository
from src.models.world import Element, WorldDoc, WorldMeta, WorldSource
from tests.conftest import TestSession


@pytest_asyncio.fixture
def sample_world():
    return WorldDoc(
        world_id=str(uuid.uuid4()),
        version="1.0",
        source=WorldSource(title="三体", author="刘慈欣"),
        meta=WorldMeta(),
        elements=[
            Element(
                id="e1", category="势力阵营", name="ETO", brief="地球三体组织", detail="详细..."
            ),
        ],
    )


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    """每个测试后清理 m1_worlds 及所有依赖表（TRUNCATE CASCADE）。"""
    yield
    async with TestSession() as session:
        # TRUNCATE CASCADE drops all FK-dependent rows in one shot
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        await session.commit()


@pytest.mark.asyncio
class TestWorldRepoSave:
    async def test_save_returns_world_id(self, sample_world):
        """save() 应返回 world_id。"""
        async with TestSession() as session:
            repo = WorldRepository(session)
            world_id = await repo.save(sample_world, user_id=str(uuid.uuid4()))
            assert world_id == sample_world.world_id

    async def test_save_persists_to_db(self, sample_world):
        """save 后应能通过 get 拿到。"""
        user_id = str(uuid.uuid4())
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(sample_world, user_id=user_id)
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            loaded = await repo.get(sample_world.world_id)
            assert loaded is not None
            assert loaded.world_id == sample_world.world_id
            assert loaded.source.title == "三体"


@pytest.mark.asyncio
class TestWorldRepoGet:
    async def test_get_nonexistent_returns_none(self):
        """查询不存在的 world 应返回 None。"""
        async with TestSession() as session:
            repo = WorldRepository(session)
            result = await repo.get(str(uuid.uuid4()))
            assert result is None

    async def test_get_preserves_elements(self, sample_world):
        """get 应完整还原 elements。"""
        user_id = str(uuid.uuid4())
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(sample_world, user_id=user_id)
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            loaded = await repo.get(sample_world.world_id)
            assert len(loaded.elements) == 1
            assert loaded.elements[0].name == "ETO"
            assert loaded.elements[0].category == "势力阵营"

    async def test_save_update_overwrites(self, sample_world):
        """再次 save 同一 world_id 应更新而非创建新记录。"""
        user_id = str(uuid.uuid4())
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(sample_world, user_id=user_id)
            await session.commit()

        sample_world.elements.append(
            Element(id="e2", category="历史背景", name="大低谷", brief="...", detail="...")
        )
        async with TestSession() as session:
            repo = WorldRepository(session)
            await repo.save(sample_world, user_id=user_id)
            await session.commit()

        async with TestSession() as session:
            repo = WorldRepository(session)
            loaded = await repo.get(sample_world.world_id)
            assert len(loaded.elements) == 2
