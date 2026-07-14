"""Integration tests for RelationRepository - requires Docker PostgreSQL."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from src.db.models import M1World, M2Character, M2Relation
from src.db.repositories.relation_repo import RelationRepository
from src.models.relation import CreateRelationRequest, UpdateRelationRequest
from tests.conftest import TestSession

WORLD_ID = uuid.uuid4()
CHAR_A_ID = uuid.uuid4()
CHAR_B_ID = uuid.uuid4()


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    async with TestSession() as session:
        await session.execute(M2Relation.__table__.delete())
        await session.execute(M2Character.__table__.delete())
        await session.execute(M1World.__table__.delete().where(M1World.id == WORLD_ID))
        session.add(
            M1World(
                id=WORLD_ID,
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                title="测试世界",
                world_doc={},
            )
        )
        # 创建两个测试角色
        session.add(
            M2Character(
                id=CHAR_A_ID,
                world_id=WORLD_ID,
                name="叶文洁",
                profile={},
            )
        )
        session.add(
            M2Character(
                id=CHAR_B_ID,
                world_id=WORLD_ID,
                name="汪淼",
                profile={},
            )
        )
        await session.commit()
    yield
    async with TestSession() as session:
        await session.execute(M2Relation.__table__.delete())
        await session.execute(M2Character.__table__.delete())
        await session.execute(M1World.__table__.delete().where(M1World.id == WORLD_ID))
        await session.commit()


class TestRelationRepoCreate:
    async def test_create_returns_relation(self):
        async with TestSession() as session:
            repo = RelationRepository(session)
            result = await repo.create(
                str(WORLD_ID),
                CreateRelationRequest(
                    character_a=str(CHAR_A_ID),
                    character_b=str(CHAR_B_ID),
                    type="同事",
                ),
            )
            assert result.type == "同事"
            assert result.character_a == str(CHAR_A_ID)
            assert result.id is not None

    async def test_create_enforces_unique_active_pair(self):
        async with TestSession() as session:
            repo = RelationRepository(session)
            await repo.create(
                str(WORLD_ID),
                CreateRelationRequest(
                    character_a=str(CHAR_A_ID),
                    character_b=str(CHAR_B_ID),
                    type="同事",
                ),
            )
            await session.commit()

        # 同一对再创建 active 关系应失败
        async with TestSession() as session:
            repo = RelationRepository(session)
            with pytest.raises(IntegrityError):
                await repo.create(
                    str(WORLD_ID),
                    CreateRelationRequest(
                        character_a=str(CHAR_A_ID),
                        character_b=str(CHAR_B_ID),
                        type="上下级",
                    ),
                )


class TestRelationRepoGetById:
    async def test_get_existing(self):
        async with TestSession() as session:
            repo = RelationRepository(session)
            created = await repo.create(
                str(WORLD_ID),
                CreateRelationRequest(
                    character_a=str(CHAR_A_ID),
                    character_b=str(CHAR_B_ID),
                    type="同事",
                ),
            )
            await session.commit()

        async with TestSession() as session:
            repo = RelationRepository(session)
            result = await repo.get_by_id(created.id)
            assert result is not None
            assert result.type == "同事"

    async def test_get_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = RelationRepository(session)
            result = await repo.get_by_id(str(uuid.uuid4()))
            assert result is None


class TestRelationRepoListByWorld:
    async def test_list_all(self):
        async with TestSession() as session:
            repo = RelationRepository(session)
            await repo.create(
                str(WORLD_ID),
                CreateRelationRequest(
                    character_a=str(CHAR_A_ID),
                    character_b=str(CHAR_B_ID),
                    type="同事",
                ),
            )
            await session.commit()

        async with TestSession() as session:
            repo = RelationRepository(session)
            results = await repo.list_by_world(str(WORLD_ID))
            assert len(results) == 1

    async def test_list_filter_by_character_id(self):
        char_c = uuid.uuid4()
        async with TestSession() as session:
            session.add(M2Character(id=char_c, world_id=WORLD_ID, name="罗辑", profile={}))
            await session.commit()

        async with TestSession() as session:
            repo = RelationRepository(session)
            await repo.create(
                str(WORLD_ID),
                CreateRelationRequest(
                    character_a=str(CHAR_A_ID),
                    character_b=str(CHAR_B_ID),
                    type="同事",
                ),
            )
            await repo.create(
                str(WORLD_ID),
                CreateRelationRequest(
                    character_a=str(char_c),
                    character_b=str(CHAR_B_ID),
                    type="上下级",
                ),
            )
            await session.commit()

        async with TestSession() as session:
            repo = RelationRepository(session)
            results = await repo.list_by_world(str(WORLD_ID), character_id=str(CHAR_A_ID))
            assert len(results) == 1
            assert results[0].type == "同事"


class TestRelationRepoUpdate:
    async def test_update_modifies_fields(self):
        async with TestSession() as session:
            repo = RelationRepository(session)
            created = await repo.create(
                str(WORLD_ID),
                CreateRelationRequest(
                    character_a=str(CHAR_A_ID),
                    character_b=str(CHAR_B_ID),
                    type="同事",
                ),
            )
            await session.commit()

        async with TestSession() as session:
            repo = RelationRepository(session)
            updated = await repo.update(
                created.id,
                UpdateRelationRequest(description="紧密合作"),
            )
            assert updated is not None
            assert updated.description == "紧密合作"

    async def test_update_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = RelationRepository(session)
            result = await repo.update(
                str(uuid.uuid4()),
                UpdateRelationRequest(description="不存在"),
            )
            assert result is None
