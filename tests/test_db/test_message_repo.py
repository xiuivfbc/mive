"""Tests for MessageRepository."""

import uuid
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import text

from src.db.models import M1World, M4ChatSession
from src.db.repositories.message_repo import MessageRepository
from src.models.message import Message
from tests.conftest import TestSession

WORLD_ID = uuid.uuid4()
CHAR_ID_1 = uuid.uuid4()


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m1_worlds CASCADE"))
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


def _make_message(**kwargs) -> Message:
    return Message(
        id=str(kwargs.get("id", uuid.uuid4())),
        world_id=str(kwargs.get("world_id", WORLD_ID)),
        type=kwargs.get("type", "dialogue"),
        sender_type=kwargs.get("sender_type", "character"),
        sender_id=kwargs.get("sender_id", str(CHAR_ID_1)),
        content=kwargs.get("content", "测试消息"),
        virtual_time=kwargs.get("virtual_time", datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC)),
        is_key_message=kwargs.get("is_key_message", False),
        user_participated=kwargs.get("user_participated", False),
        session_id=kwargs.get("session_id"),
    )


class TestMessageRepoCreate:
    async def test_create_message(self):
        async with TestSession() as session:
            repo = MessageRepository(session)
            msg = _make_message()
            created = await repo.create(msg)
            assert created.id is not None
            assert created.content == "测试消息"
            assert created.sender_id == str(CHAR_ID_1)

    async def test_create_user_message(self):
        async with TestSession() as session:
            repo = MessageRepository(session)
            msg = _make_message(
                type="user",
                sender_type="user",
                sender_id=None,
                sender_name=None,
                content="用户消息",
            )
            created = await repo.create(msg)
            assert created.type == "user"
            assert created.sender_type == "user"
            assert created.sender_id is None


class TestMessageRepoCreateBatch:
    async def test_create_batch(self):
        async with TestSession() as session:
            repo = MessageRepository(session)
            messages = [
                _make_message(
                    content="消息1", virtual_time=datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC)
                ),
                _make_message(
                    content="消息2", virtual_time=datetime(2024, 1, 1, 8, 5, 0, tzinfo=UTC)
                ),
                _make_message(
                    content="消息3",
                    virtual_time=datetime(2024, 1, 1, 8, 10, 0, tzinfo=UTC),
                ),
            ]
            created = await repo.create_batch(messages)
            assert len(created) == 3
            assert created[0].content == "消息1"
            assert created[2].content == "消息3"


class TestMessageRepoListRecent:
    async def test_list_recent_returns_latest(self):
        async with TestSession() as session:
            repo = MessageRepository(session)
            for i in range(5):
                await repo.create(
                    _make_message(
                        content=f"消息{i}",
                        virtual_time=datetime(2024, 1, 1, 8, i, 0, tzinfo=UTC),
                    )
                )
            await session.commit()

        async with TestSession() as session:
            repo = MessageRepository(session)
            result = await repo.list_recent(str(WORLD_ID), limit=3)
            assert len(result) == 3
            # 按 virtual_time DESC，最新的在前
            assert result[0].content == "消息4"
            assert result[2].content == "消息2"

    async def test_list_recent_empty_world(self):
        async with TestSession() as session:
            repo = MessageRepository(session)
            result = await repo.list_recent(str(uuid.uuid4()), limit=10)
            assert result == []


class TestMessageRepoListFiltered:
    async def test_filter_by_sender(self):
        other_char_id = uuid.uuid4()
        async with TestSession() as session:
            repo = MessageRepository(session)
            await repo.create(_make_message(sender_id=str(CHAR_ID_1)))
            await repo.create(_make_message(sender_id=str(other_char_id)))
            await repo.create(_make_message(sender_id=str(CHAR_ID_1)))
            await session.commit()

        async with TestSession() as session:
            repo = MessageRepository(session)
            result = await repo.list_filtered(str(WORLD_ID), sender_id=str(CHAR_ID_1))
            assert len(result) == 2
            assert all(m.sender_id == str(CHAR_ID_1) for m in result)

    async def test_filter_by_type(self):
        async with TestSession() as session:
            repo = MessageRepository(session)
            await repo.create(_make_message(type="dialogue", content="对话"))
            await repo.create(_make_message(type="narration", content="旁白"))
            await repo.create(_make_message(type="dialogue", content="又一个对话"))
            await session.commit()

        async with TestSession() as session:
            repo = MessageRepository(session)
            result = await repo.list_filtered(str(WORLD_ID), type="narration")
            assert len(result) == 1
            assert result[0].content == "旁白"


async def _create_test_chat_session() -> uuid.UUID:
    """Insert a real m4_chat_sessions row and return its id."""
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
