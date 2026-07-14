"""ChatSessionRepository 数据库集成测试。"""

import uuid

import pytest_asyncio
from sqlalchemy import text

from src.db.models import M1World
from src.db.repositories.chat_session_repo import ChatSessionRepository
from tests.conftest import TestSession

WORLD_ID = uuid.uuid4()
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        session.add(
            M1World(
                id=WORLD_ID,
                user_id=USER_ID,
                title="会话测试世界",
                world_doc={"world_id": str(WORLD_ID), "source": {}, "meta": {}, "elements": []},
            )
        )
        await session.commit()
    yield
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        await session.commit()


class TestChatSessionRepoCreate:
    async def test_create_session_returns_model(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            sess = await repo.create(str(WORLD_ID), type="character", title="第一个对话")
            await session.commit()

        assert sess.id is not None
        assert sess.world_id == str(WORLD_ID)
        assert sess.type == "character"
        assert sess.title == "第一个对话"

    async def test_create_event_session(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            sess = await repo.create(str(WORLD_ID), type="event", title="风暴之夜")
            await session.commit()

        assert sess.type == "event"

    async def test_create_session_without_title(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            sess = await repo.create(str(WORLD_ID), type="character")
            await session.commit()

        assert sess.title is None


class TestChatSessionRepoGetById:
    async def test_get_existing_session(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            created = await repo.create(str(WORLD_ID), type="character", title="查询测试")
            await session.commit()
            sid = created.id

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            found = await repo.get_by_id(sid)

        assert found is not None
        assert found.id == sid
        assert found.title == "查询测试"

    async def test_get_nonexistent_session_returns_none(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            result = await repo.get_by_id(str(uuid.uuid4()))

        assert result is None


class TestChatSessionRepoListByWorld:
    async def test_list_returns_all_sessions(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            await repo.create(str(WORLD_ID), type="character", title="会话1")
            await repo.create(str(WORLD_ID), type="event", title="会话2")
            await session.commit()

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            sessions = await repo.list_by_world(str(WORLD_ID))

        assert len(sessions) == 2

    async def test_list_empty_world_returns_empty(self):
        other_world_id = str(uuid.uuid4())
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            sessions = await repo.list_by_world(other_world_id)

        assert sessions == []


class TestChatSessionRepoDelete:
    async def test_delete_existing_session_returns_true(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            created = await repo.create(str(WORLD_ID), type="character")
            await session.commit()
            sid = created.id

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            deleted = await repo.delete(sid)
            await session.commit()

        assert deleted is True

    async def test_delete_removes_from_db(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            created = await repo.create(str(WORLD_ID), type="character")
            await session.commit()
            sid = created.id

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            await repo.delete(sid)
            await session.commit()

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            result = await repo.get_by_id(sid)

        assert result is None

    async def test_delete_nonexistent_returns_false(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            deleted = await repo.delete(str(uuid.uuid4()))

        assert deleted is False


class TestChatSessionRepoUpdateTitle:
    async def test_update_title_persists(self):
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            created = await repo.create(str(WORLD_ID), type="character", title="旧标题")
            await session.commit()
            sid = created.id

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            await repo.update_title(sid, "新标题")
            await session.commit()

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            found = await repo.get_by_id(sid)

        assert found.title == "新标题"


class TestChatSessionRepoUpdateParticipants:
    async def test_update_participants_stores_uuid_array(self):
        """Dict participants should be stored as UUID string array."""
        char_id_a = str(uuid.uuid4())
        char_id_b = str(uuid.uuid4())

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            created = await repo.create(str(WORLD_ID), type="character")
            await session.commit()
            sid = created.id

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            await repo.update_participants(
                sid,
                participants=[
                    {"id": char_id_a, "name": "叶文洁"},
                    {"id": char_id_b, "name": "常伟思"},
                ],
                participant_mode="auto",
            )
            await session.commit()

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            found = await repo.get_by_id(sid)

        assert found.participants == [char_id_a, char_id_b]
        assert found.participant_mode == "auto"
        # Verify stored as strings, not dicts
        for p in found.participants:
            assert isinstance(p, str)

    async def test_update_participants_accepts_string_list(self):
        """Already-string UUIDs should be stored directly."""
        char_id = str(uuid.uuid4())

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            created = await repo.create(str(WORLD_ID), type="character")
            await session.commit()
            sid = created.id

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            await repo.update_participants(
                sid,
                participants=[char_id],
                participant_mode="auto",
            )
            await session.commit()

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            found = await repo.get_by_id(sid)

        assert found.participants == [char_id]

    async def test_update_participants_empty_list(self):
        """Empty participants list should clear participants."""
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            created = await repo.create(str(WORLD_ID), type="character")
            await session.commit()
            sid = created.id

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            await repo.update_participants(
                sid,
                participants=[],
                participant_mode="auto",
            )
            await session.commit()

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            found = await repo.get_by_id(sid)

        assert found.participants == []

    async def test_update_participants_filters_invalid_entries(self):
        """Dicts without 'id' should be filtered out."""
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            created = await repo.create(str(WORLD_ID), type="character")
            await session.commit()
            sid = created.id

        valid_id = str(uuid.uuid4())
        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            await repo.update_participants(
                sid,
                participants=[
                    {"id": valid_id, "name": "有效角色"},
                    {"name": "没有ID的角色"},  # no 'id' key
                ],
                participant_mode="auto",
            )
            await session.commit()

        async with TestSession() as session:
            repo = ChatSessionRepository(session)
            found = await repo.get_by_id(sid)

        assert found.participants == [valid_id]
