import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio

from src.db.models import M1World, M3Event
from src.db.repositories.event_repo import EventRepository
from tests.conftest import TestSession

WORLD_ID = uuid.uuid4()
OTHER_WORLD_ID = uuid.uuid4()


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    """清理测试数据"""
    async with TestSession() as session:
        await session.execute(M3Event.__table__.delete().where(M3Event.world_id == WORLD_ID))
        await session.execute(M3Event.__table__.delete().where(M3Event.world_id == OTHER_WORLD_ID))
        await session.execute(M1World.__table__.delete().where(M1World.id == WORLD_ID))
        await session.execute(M1World.__table__.delete().where(M1World.id == OTHER_WORLD_ID))
        session.add(
            M1World(
                id=WORLD_ID,
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                title="测试世界",
                world_doc={"world_id": str(WORLD_ID), "source": {}, "meta": {}, "elements": []},
            )
        )
        session.add(
            M1World(
                id=OTHER_WORLD_ID,
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                title="另一个世界",
                world_doc={},
            )
        )
        await session.commit()
    yield
    async with TestSession() as session:
        await session.execute(M3Event.__table__.delete().where(M3Event.world_id == WORLD_ID))
        await session.execute(M3Event.__table__.delete().where(M3Event.world_id == OTHER_WORLD_ID))
        await session.execute(M1World.__table__.delete().where(M1World.id == WORLD_ID))
        await session.execute(M1World.__table__.delete().where(M1World.id == OTHER_WORLD_ID))
        await session.commit()


def _make_event_data(name="瘟疫爆发", priority="medium", offset_hours=0):  # noqa: ARG001  # offset_hours kept for call site compatibility
    """辅助：创建事件字典"""
    return {
        "event_type": "user_injected",
        "name": name,
        "description": f"{name}的详细描述",
        "priority": priority,
    }


class TestEventRepoCreate:
    async def test_create_returns_event(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            result = await repo.create(str(WORLD_ID), _make_event_data())
            assert result.name == "瘟疫爆发"
            assert result.id is not None
            assert result.world_id == str(WORLD_ID)
            assert result.status == "scheduled"

    async def test_create_persists_to_db(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            created = await repo.create(str(WORLD_ID), _make_event_data())
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            fetched = await repo.get_by_id(created.id)
            assert fetched is not None
            assert fetched.name == "瘟疫爆发"


class TestEventRepoGetById:
    async def test_get_existing(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            created = await repo.create(str(WORLD_ID), _make_event_data())
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            result = await repo.get_by_id(created.id)
            assert result is not None
            assert result.name == "瘟疫爆发"

    async def test_get_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            result = await repo.get_by_id(str(uuid.uuid4()))
            assert result is None


class TestEventRepoListByWorld:
    async def test_list_returns_all_for_world(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            await repo.create(str(WORLD_ID), _make_event_data("事件A"))
            await repo.create(str(WORLD_ID), _make_event_data("事件B"))
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            results = await repo.list_by_world(str(WORLD_ID))
            assert len(results) == 2
            names = {e.name for e in results}
            assert names == {"事件A", "事件B"}

    async def test_list_excludes_other_worlds(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            await repo.create(str(WORLD_ID), _make_event_data("本世界事件"))
            await repo.create(str(OTHER_WORLD_ID), _make_event_data("其他世界事件"))
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            results = await repo.list_by_world(str(WORLD_ID))
            assert len(results) == 1
            assert results[0].name == "本世界事件"

    async def test_list_filter_by_status(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            evt = await repo.create(str(WORLD_ID), _make_event_data("待处理"))
            await repo.create(str(WORLD_ID), _make_event_data("另一个"))
            # 将第一个标记为 completed
            await repo.update_status(evt.id, "completed")
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            scheduled = await repo.list_by_world(str(WORLD_ID), status="scheduled")
            assert len(scheduled) == 1
            assert scheduled[0].name == "另一个"

    async def test_list_filter_by_time_range(self):

        now = datetime.now(UTC)
        async with TestSession() as session:
            repo = EventRepository(session)
            await repo.create(str(WORLD_ID), _make_event_data("窗口内事件"))
            await repo.create(str(WORLD_ID), _make_event_data("窗口外事件"))
            await session.commit()

        # Query with a window ending just after now (covers both events)
        async with TestSession() as session:
            repo = EventRepository(session)
            results_all = await repo.list_by_world(
                str(WORLD_ID),
                from_time=now - timedelta(hours=1),
                to_time=now + timedelta(hours=1),
            )
            names_all = {e.name for e in results_all}
            assert "窗口内事件" in names_all
            assert "窗口外事件" in names_all

        # Query with a window far in the past (matches nothing)
        async with TestSession() as session:
            repo = EventRepository(session)
            results_empty = await repo.list_by_world(
                str(WORLD_ID),
                from_time=now - timedelta(days=365),
                to_time=now - timedelta(days=364),
            )
            assert len(results_empty) == 0


class TestEventRepoUpdateStatus:
    async def test_update_status_marks_executed_at(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            created = await repo.create(str(WORLD_ID), _make_event_data())
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            updated = await repo.update_status(created.id, "completed")
            assert updated is not None
            assert updated.status == "completed"
            assert updated.executed_at is not None

    async def test_update_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            result = await repo.update_status(str(uuid.uuid4()), "completed")
            assert result is None


class TestEventRepoMarkKeyEvent:
    async def test_mark_key_event(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            created = await repo.create(str(WORLD_ID), _make_event_data())
            assert created.is_key_event is False
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            updated = await repo.mark_key_event(created.id, True)
            assert updated is not None
            assert updated.is_key_event is True

    async def test_unmark_key_event(self):
        async with TestSession() as session:
            repo = EventRepository(session)
            created = await repo.create(str(WORLD_ID), _make_event_data())
            await repo.mark_key_event(created.id, True)
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            updated = await repo.mark_key_event(created.id, False)
            assert updated is not None
            assert updated.is_key_event is False


class TestEventRepoFindDueEvents:
    async def test_find_due_events_in_window(self):

        now = datetime.now(UTC)
        async with TestSession() as session:
            repo = EventRepository(session)
            await repo.create(str(WORLD_ID), _make_event_data("窗口内事件"))
            await repo.create(str(WORLD_ID), _make_event_data("窗口内事件2"))
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            due = await repo.find_due_events(
                str(WORLD_ID),
                from_time=now - timedelta(hours=1),
                to_time=now + timedelta(hours=1),
            )
            assert len(due) == 2

    async def test_find_due_excludes_non_scheduled(self):

        now = datetime.now(UTC)
        async with TestSession() as session:
            repo = EventRepository(session)
            evt = await repo.create(str(WORLD_ID), _make_event_data("已完成事件"))
            await repo.update_status(evt.id, "completed")
            await repo.create(str(WORLD_ID), _make_event_data("待处理事件"))
            await session.commit()

        async with TestSession() as session:
            repo = EventRepository(session)
            due = await repo.find_due_events(
                str(WORLD_ID),
                from_time=now - timedelta(hours=1),
                to_time=now + timedelta(hours=1),
            )
            assert len(due) == 1
            assert due[0].name == "待处理事件"
