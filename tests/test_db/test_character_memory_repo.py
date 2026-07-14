"""CharacterMemoryRepository 数据库集成测试。"""

import uuid

import pytest_asyncio
from sqlalchemy import text

from src.db.models import M1World, M2Character, M2CharacterMemory
from src.db.repositories.character_memory_repo import CharacterMemoryRepository
from tests.conftest import TestSession

WORLD_ID = uuid.uuid4()
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
CHAR_ID = uuid.uuid4()


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        session.add(
            M1World(
                id=WORLD_ID,
                user_id=USER_ID,
                title="记忆测试世界",
                world_doc={"world_id": str(WORLD_ID), "source": {}, "meta": {}, "elements": []},
            )
        )
        session.add(
            M2Character(
                id=CHAR_ID,
                world_id=WORLD_ID,
                name="测试角色",
                profile={"brief": "测试用"},
            )
        )
        await session.commit()
    yield
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
        await session.commit()


async def _create_chat_session() -> uuid.UUID:
    """Insert a real m4_chat_sessions row and return its id."""
    from src.db.models import M4ChatSession

    sid = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            M4ChatSession(
                id=sid,
                world_id=WORLD_ID,
                type="character",
                title="测试会话",
            )
        )
        await session.commit()
    return sid


async def _add_memory(
    memory_type: str = "short_term",
    content: str = "记忆内容",
    session_id: uuid.UUID | None = None,
) -> M2CharacterMemory:
    async with TestSession() as session:
        repo = CharacterMemoryRepository(session)
        mem = await repo.add(
            character_id=CHAR_ID,
            world_id=WORLD_ID,
            session_id=session_id,
            memory_type=memory_type,
            content=content,
        )
        await session.commit()
        return mem


class TestAddMemory:
    async def test_add_short_term_memory(self):
        mem = await _add_memory("short_term", "短期记忆")
        assert mem.id is not None
        assert mem.content == "短期记忆"
        assert mem.memory_type == "short_term"

    async def test_add_long_term_memory(self):
        mem = await _add_memory("long_term", "长期记忆")
        assert mem.memory_type == "long_term"

    async def test_add_memory_with_session(self):
        sess_id = await _create_chat_session()
        mem = await _add_memory("short_term", "含会话记忆", session_id=sess_id)
        assert mem.session_id == sess_id


class TestListShortTerm:
    async def test_list_returns_short_term_only(self):
        await _add_memory("short_term", "短期1")
        await _add_memory("short_term", "短期2")
        await _add_memory("long_term", "长期1")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_short_term(CHAR_ID, limit=10)

        assert len(result) == 2
        for m in result:
            assert m.memory_type == "short_term"

    async def test_list_respects_limit(self):
        for i in range(5):
            await _add_memory("short_term", f"记忆{i}")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_short_term(CHAR_ID, limit=3)

        assert len(result) == 3

    async def test_list_returns_newest_first(self):
        await _add_memory("short_term", "旧记忆")
        await _add_memory("short_term", "新记忆")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_short_term(CHAR_ID, limit=10)

        assert result[0].content == "新记忆"

    async def test_empty_returns_empty_list(self):
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_short_term(CHAR_ID)

        assert result == []


class TestListLongTerm:
    async def test_list_returns_long_term_only(self):
        await _add_memory("long_term", "长期1")
        await _add_memory("short_term", "短期1")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_long_term(CHAR_ID)

        assert len(result) == 1
        assert result[0].memory_type == "long_term"


class TestGetOldestShortTerm:
    async def test_returns_oldest_first(self):
        await _add_memory("short_term", "旧")
        await _add_memory("short_term", "新")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.get_oldest_short_term(CHAR_ID, limit=1)

        assert len(result) == 1
        assert result[0].content == "旧"


class TestDeleteByIds:
    async def test_delete_removes_specified_memories(self):
        m1 = await _add_memory("short_term", "要删除的")
        _m2 = await _add_memory("short_term", "保留的")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            await repo.delete_by_ids([m1.id])
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            remaining = await repo.list_short_term(CHAR_ID, limit=10)

        assert len(remaining) == 1
        assert remaining[0].content == "保留的"

    async def test_delete_empty_list_no_error(self):
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            await repo.delete_by_ids([])
            await session.commit()


class TestDeleteBySession:
    async def test_delete_by_session_removes_only_that_session(self):
        sess1 = await _create_chat_session()
        sess2 = await _create_chat_session()
        await _add_memory("short_term", "会话1记忆", session_id=sess1)
        await _add_memory("short_term", "会话2记忆", session_id=sess2)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            await repo.delete_by_session(sess1)
            await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            remaining = await repo.list_short_term(CHAR_ID, limit=10)

        assert len(remaining) == 1
        assert remaining[0].content == "会话2记忆"


class TestGetById:
    async def test_get_existing_memory(self):
        mem = await _add_memory("short_term", "查询测试")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.get_by_id(mem.id)

        assert result is not None
        assert result.content == "查询测试"

    async def test_get_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.get_by_id(uuid.uuid4())

        assert result is None


class TestGetLatestBySession:
    async def test_returns_latest_memory_for_session(self):
        sess_id = await _create_chat_session()
        await _add_memory("short_term", "旧记忆", session_id=sess_id)
        await _add_memory("short_term", "新记忆", session_id=sess_id)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.get_latest_by_session(sess_id)

        assert result is not None
        assert result.content == "新记忆"
        assert result.session_id == sess_id

    async def test_returns_none_when_no_memories_for_session(self):
        sess_id = await _create_chat_session()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.get_latest_by_session(sess_id)

        assert result is None

    async def test_returns_none_for_nonexistent_session(self):
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.get_latest_by_session(uuid.uuid4())

        assert result is None

    async def test_only_returns_memories_for_given_session(self):
        sess1 = await _create_chat_session()
        sess2 = await _create_chat_session()
        await _add_memory("short_term", "会话1记忆", session_id=sess1)
        await _add_memory("short_term", "会话2新记忆", session_id=sess2)

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.get_latest_by_session(sess1)

        assert result is not None
        assert result.content == "会话1记忆"


CHAR_ID_2 = uuid.uuid4()


class TestListCharactersNeedingPromotion:
    async def _setup_two_characters(self):
        """Insert a second character for multi-char tests."""
        async with TestSession() as session:
            session.add(
                M2Character(
                    id=CHAR_ID_2,
                    world_id=WORLD_ID,
                    name="测试角色2",
                    profile={"brief": "测试用2"},
                )
            )
            await session.commit()

    async def test_returns_character_above_threshold(self):
        await self._setup_two_characters()
        # Add 3 short-term memories for CHAR_ID (threshold=3)
        for i in range(3):
            await _add_memory("short_term", f"记忆{i}")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_characters_needing_promotion([CHAR_ID, CHAR_ID_2], threshold=3)

        assert CHAR_ID in result
        assert CHAR_ID_2 not in result

    async def test_returns_empty_when_below_threshold(self):
        await _add_memory("short_term", "一条记忆")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_characters_needing_promotion([CHAR_ID], threshold=3)

        assert result == set()

    async def test_returns_empty_for_empty_input(self):
        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_characters_needing_promotion([], threshold=3)

        assert result == set()

    async def test_does_not_count_long_term_memories(self):
        await self._setup_two_characters()
        # Add 3 long-term memories (should not count toward threshold)
        for i in range(3):
            await _add_memory("long_term", f"长期{i}")

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_characters_needing_promotion([CHAR_ID], threshold=3)

        assert result == set()

    async def test_multiple_characters_above_threshold(self):
        await self._setup_two_characters()
        # Add memories for both characters
        for i in range(3):
            await _add_memory("short_term", f"角色1记忆{i}")
        for i in range(3):
            async with TestSession() as session:
                repo = CharacterMemoryRepository(session)
                await repo.add(
                    character_id=CHAR_ID_2,
                    world_id=WORLD_ID,
                    session_id=None,
                    memory_type="short_term",
                    content=f"角色2记忆{i}",
                )
                await session.commit()

        async with TestSession() as session:
            repo = CharacterMemoryRepository(session)
            result = await repo.list_characters_needing_promotion([CHAR_ID, CHAR_ID_2], threshold=3)

        assert CHAR_ID in result
        assert CHAR_ID_2 in result
