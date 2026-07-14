"""Tests for MessageService selection inertia (probabilistic Redis-persisted counter).

The counter logic in send_message():
- auto/include mode: with no existing participants, always call select_participants.
- Otherwise, roll `random.random() < base_prob + counter * prob_step` (capped at 1.0).
  - If triggered: call select_participants and reset the persisted counter to 0.
  - If not triggered: skip select_participants, reuse existing participants, and
    increment the persisted counter by 1.
- The counter is persisted in Redis (key `selection_counter:{chat_session_id}`,
  TTL 24h) so it survives across per-request MessageService instances.
- edit mode: always reset the counter (gives a fresh exemption period on return to auto).
- If Redis is unavailable (or errors), always call select_participants (safe fallback,
  never permanently freezes participants).
- Different chat sessions have independent counters.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from src.services.message_service import MessageService


class FakeRedis:
    """Minimal in-memory async fake backing a shared dict, for cross-instance tests."""

    def __init__(self, store: dict | None = None):
        self.store = store if store is not None else {}

    async def get(self, key):
        val = self.store.get(key)
        if val is None:
            return None
        return str(val).encode("utf-8")

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


def _make_message_service(dialogue_service=None, redis=None):
    """Create a MessageService with mocked dependencies."""
    message_repo = AsyncMock()
    message_repo.create = AsyncMock(side_effect=lambda m: m)
    message_repo.list_by_session = AsyncMock(return_value=[])

    chat_session_repo = AsyncMock()
    chat_session_repo.get_by_id = AsyncMock(return_value=None)
    chat_session_repo.update_participants = AsyncMock()

    ds = dialogue_service or AsyncMock()
    ds.select_participants = AsyncMock(
        return_value={
            "speakers": [{"id": "c1", "name": "Alice"}],
            "background": [],
            "narration": "",
            "relevant_elements": [],
            "relevant_event": None,
        }
    )
    ds.generate_response = AsyncMock(return_value=[])

    svc = MessageService(
        message_repo=message_repo,
        dialogue_service=ds,
        llm=None,
        session_factory=None,
        chat_session_repo=chat_session_repo,
        redis=redis,
    )
    return svc, ds


_EXISTING_PARTICIPANTS = [{"id": "c1", "name": "Alice"}]


class TestSelectionInertiaCrossInstancePersistence:
    """计数器需通过 Redis 跨 MessageService 实例（per-request）持久化。"""

    @pytest.mark.asyncio
    async def test_counter_persists_across_instances(self, monkeypatch):
        store: dict = {}
        session_id = str(uuid.uuid4())

        # First call: counter=0 -> prob=0.10, random.random()=0.5 -> no reselect, counter -> 1
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.5)
        svc1, ds1 = _make_message_service(redis=FakeRedis(store))
        await svc1.send_message(
            world_id="w1",
            content="msg0",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_id,
        )
        ds1.select_participants.assert_not_called()
        assert store[f"selection_counter:{session_id}"] == 1

        # Second call (new instance): counter=1 -> prob=0.15, random.random()=0.5 -> no reselect
        svc2, ds2 = _make_message_service(redis=FakeRedis(store))
        await svc2.send_message(
            world_id="w1",
            content="msg1",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_id,
        )
        ds2.select_participants.assert_not_called()
        assert store[f"selection_counter:{session_id}"] == 2


class TestSelectionInertiaProbabilityFormula:
    """概率公式: prob = base + counter * step，触发后归零、未触发则计数器 +1。"""

    @pytest.mark.asyncio
    async def test_counter_zero_low_random_triggers_reselect(self, monkeypatch):
        store: dict = {}
        session_id = str(uuid.uuid4())

        # counter=0 -> prob=0.10; random()=0.05 < 0.10 -> reselect, counter reset to 0
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.05)
        svc, ds = _make_message_service(redis=FakeRedis(store))
        await svc.send_message(
            world_id="w1",
            content="msg",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_id,
        )
        ds.select_participants.assert_called_once()
        assert store[f"selection_counter:{session_id}"] == 0

    @pytest.mark.asyncio
    async def test_counter_zero_high_random_skips_reselect(self, monkeypatch):
        store: dict = {}
        session_id = str(uuid.uuid4())

        # counter=0 -> prob=0.10; random()=0.5 >= 0.10 -> skip, counter -> 1
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.5)
        svc, ds = _make_message_service(redis=FakeRedis(store))
        await svc.send_message(
            world_id="w1",
            content="msg",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_id,
        )
        ds.select_participants.assert_not_called()
        assert store[f"selection_counter:{session_id}"] == 1

    @pytest.mark.asyncio
    async def test_counter_one_prob_increases(self, monkeypatch):
        session_id = str(uuid.uuid4())
        store = {f"selection_counter:{session_id}": 1}

        # counter=1 -> prob=0.15; random()=0.12 < 0.15 -> reselect, counter reset to 0
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.12)
        svc, ds = _make_message_service(redis=FakeRedis(store))
        await svc.send_message(
            world_id="w1",
            content="msg",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_id,
        )
        ds.select_participants.assert_called_once()
        assert store[f"selection_counter:{session_id}"] == 0

    @pytest.mark.asyncio
    async def test_counter_one_high_random_increments_to_two(self, monkeypatch):
        session_id = str(uuid.uuid4())
        store = {f"selection_counter:{session_id}": 1}

        # counter=1 -> prob=0.15; random()=0.5 >= 0.15 -> skip, counter -> 2
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.5)
        svc, ds = _make_message_service(redis=FakeRedis(store))
        await svc.send_message(
            world_id="w1",
            content="msg",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_id,
        )
        ds.select_participants.assert_not_called()
        assert store[f"selection_counter:{session_id}"] == 2

    @pytest.mark.asyncio
    async def test_probability_capped_at_one(self, monkeypatch):
        session_id = str(uuid.uuid4())
        # counter large enough that base + counter*step > 1.0
        store = {f"selection_counter:{session_id}": 100}

        # random()=0.99 should still trigger reselect since prob is capped at 1.0
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.99)
        svc, ds = _make_message_service(redis=FakeRedis(store))
        await svc.send_message(
            world_id="w1",
            content="msg",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_id,
        )
        ds.select_participants.assert_called_once()
        assert store[f"selection_counter:{session_id}"] == 0


class TestSelectionInertiaRedisUnavailable:
    """Redis 不可用时，始终调用 select_participants（安全兜底）。"""

    @pytest.mark.asyncio
    async def test_redis_none_always_reselects(self, monkeypatch):
        session_id = str(uuid.uuid4())

        # Even a "would not trigger" random value should not matter
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.99)
        svc, ds = _make_message_service(redis=None)

        for i in range(3):
            await svc.send_message(
                world_id="w1",
                content=f"msg{i}",
                participant_mode="auto",
                participants=_EXISTING_PARTICIPANTS,
                session_id=session_id,
            )

        assert ds.select_participants.call_count == 3

    @pytest.mark.asyncio
    async def test_redis_get_error_always_reselects(self, monkeypatch):
        session_id = str(uuid.uuid4())

        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.99)

        bad_redis = AsyncMock()
        bad_redis.get = AsyncMock(side_effect=Exception("boom"))
        bad_redis.set = AsyncMock(side_effect=Exception("boom"))
        bad_redis.delete = AsyncMock(side_effect=Exception("boom"))

        svc, ds = _make_message_service(redis=bad_redis)

        for i in range(2):
            await svc.send_message(
                world_id="w1",
                content=f"msg{i}",
                participant_mode="auto",
                participants=_EXISTING_PARTICIPANTS,
                session_id=session_id,
            )

        assert ds.select_participants.call_count == 2

    @pytest.mark.asyncio
    async def test_selection_inertia_redis_unavailable_always_reselects(self, monkeypatch):
        """Redis 异常时，无论随机值如何都始终重选参与者。"""
        session_id = str(uuid.uuid4())

        # random()=0.99 远大于基础概率 0.10，正常情况不会触发重选
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.99)

        bad_redis = AsyncMock()
        bad_redis.get = AsyncMock(side_effect=ConnectionError("connection refused"))
        bad_redis.set = AsyncMock(side_effect=ConnectionError("connection refused"))
        bad_redis.delete = AsyncMock(side_effect=ConnectionError("connection refused"))

        svc, ds = _make_message_service(redis=bad_redis)

        # 连续发 4 条消息，每条都应触发重选
        for i in range(4):
            await svc.send_message(
                world_id="w1",
                content=f"msg{i}",
                participant_mode="auto",
                participants=_EXISTING_PARTICIPANTS,
                session_id=session_id,
            )

        assert ds.select_participants.call_count == 4

    @pytest.mark.asyncio
    async def test_selection_inertia_redis_error_resets_counter(self, monkeypatch):
        """Redis 可用时积累计数器，Redis 出错后退化为始终重选（计数器丢失等效归零）。"""
        session_id = str(uuid.uuid4())
        store: dict = {}

        # random()=0.5 始终不触发概率重选（counter=0 时 prob=0.10）
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.5)

        good_redis = FakeRedis(store)
        svc1, ds1 = _make_message_service(redis=good_redis)

        # 前 2 条消息：Redis 正常，计数器从 0 累积到 2
        for i in range(2):
            await svc1.send_message(
                world_id="w1",
                content=f"msg{i}",
                participant_mode="auto",
                participants=_EXISTING_PARTICIPANTS,
                session_id=session_id,
            )
        assert ds1.select_participants.call_count == 0
        assert store[f"selection_counter:{session_id}"] == 2

        # 模拟 Redis 故障：get 抛异常 → _get_selection_counter 返回 -1 → 始终重选
        bad_redis = AsyncMock()
        bad_redis.get = AsyncMock(side_effect=ConnectionError("connection lost"))
        bad_redis.set = AsyncMock(side_effect=ConnectionError("connection lost"))
        bad_redis.delete = AsyncMock(side_effect=ConnectionError("connection lost"))

        svc2, ds2 = _make_message_service(redis=bad_redis)

        for i in range(3):
            await svc2.send_message(
                world_id="w1",
                content=f"msg{i}",
                participant_mode="auto",
                participants=_EXISTING_PARTICIPANTS,
                session_id=session_id,
            )

        # Redis 故障后每条消息都触发重选
        assert ds2.select_participants.call_count == 3


class TestSelectionInertiaNoExistingParticipants:
    """首条消息（无现有参与者）始终调用 select_participants。"""

    @pytest.mark.asyncio
    async def test_no_participants_forces_select(self, monkeypatch):
        session_id = str(uuid.uuid4())

        # Even a "would trigger" random value is irrelevant here
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.99)
        svc, ds = _make_message_service(redis=FakeRedis({}))

        await svc.send_message(
            world_id="w1",
            content="first msg",
            participant_mode="auto",
            participants=None,
            session_id=session_id,
        )

        ds.select_participants.assert_called_once()


class TestSelectionInertiaEditMode:
    """edit 模式下计数器归零；select_participants 仍被调用（其内部 edit 快捷路径不发起 LLM 请求，
    但会计算 background 关联角色），不受概率门控影响。"""

    @pytest.mark.asyncio
    async def test_edit_mode_resets_counter(self, monkeypatch):
        session_id = str(uuid.uuid4())
        store = {f"selection_counter:{session_id}": 5}

        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.99)
        svc, ds = _make_message_service(redis=FakeRedis(store))

        await svc.send_message(
            world_id="w1",
            content="edit msg",
            participant_mode="edit",
            participants=[{"id": "c1", "name": "Alice"}],
            session_id=session_id,
        )

        ds.select_participants.assert_called_once()
        call_kwargs = ds.select_participants.call_args[1]
        assert call_kwargs["participant_mode"] == "edit"
        assert f"selection_counter:{session_id}" not in store

    @pytest.mark.asyncio
    async def test_edit_mode_always_calls_select_participants_without_inertia(self, monkeypatch):
        session_id = str(uuid.uuid4())
        store: dict = {}

        # Even a "would trigger reselect" random value is irrelevant: edit mode
        # bypasses the probability gate entirely.
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.01)
        svc, ds = _make_message_service(redis=FakeRedis(store))

        for i in range(5):
            await svc.send_message(
                world_id="w1",
                content=f"edit{i}",
                participant_mode="edit",
                participants=[{"id": "c1", "name": "Alice"}],
                session_id=session_id,
            )

        assert ds.select_participants.call_count == 5
        # Counter never accumulates in edit mode
        assert f"selection_counter:{session_id}" not in store


class TestSelectionInertiaPerSession:
    """不同 session 的计数器在共享 Redis 中相互独立。"""

    @pytest.mark.asyncio
    async def test_different_sessions_have_independent_counters(self, monkeypatch):
        store: dict = {}
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        # counter=0 -> prob=0.10; random()=0.5 -> skip, counter -> 1
        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.5)
        svc, ds = _make_message_service(redis=FakeRedis(store))

        await svc.send_message(
            world_id="w1",
            content="a0",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_a,
        )
        await svc.send_message(
            world_id="w1",
            content="b0",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_b,
        )

        ds.select_participants.assert_not_called()
        assert store[f"selection_counter:{session_a}"] == 1
        assert store[f"selection_counter:{session_b}"] == 1

        # Now bump session A's counter again, B should remain unaffected
        await svc.send_message(
            world_id="w1",
            content="a1",
            participant_mode="auto",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_a,
        )
        assert store[f"selection_counter:{session_a}"] == 2
        assert store[f"selection_counter:{session_b}"] == 1


class TestSelectionInertiaIncludeMode:
    """include 模式与 auto 模式行为一致（都走概率计数器逻辑）。"""

    @pytest.mark.asyncio
    async def test_include_mode_respects_probability(self, monkeypatch):
        session_id = str(uuid.uuid4())
        store: dict = {}

        monkeypatch.setattr("src.services.message_service.random.random", lambda: 0.5)
        svc, ds = _make_message_service(redis=FakeRedis(store))

        await svc.send_message(
            world_id="w1",
            content="inc0",
            participant_mode="include",
            participants=_EXISTING_PARTICIPANTS,
            session_id=session_id,
        )

        ds.select_participants.assert_not_called()
        assert store[f"selection_counter:{session_id}"] == 1
