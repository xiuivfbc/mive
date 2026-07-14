"""RateLimitGate 测试"""

import asyncio
import heapq

import pytest

from src.llm.rate_limit_gate import RateLimitGate, _QueueItem


@pytest.fixture
def mock_request_factory():
    """创建 mock 请求工厂。"""

    def factory(status_sequence):
        """status_sequence: 返回的 status 列表，每次调用依次取一个。"""
        idx = 0

        async def do_request():
            nonlocal idx
            status = status_sequence[idx % len(status_sequence)]
            idx += 1
            return {"status": status, "text": "", "retry_after": 1.0 if status == 429 else None}

        return do_request

    return factory


# === 基础功能 ===


@pytest.mark.asyncio
async def test_basic_acquire_releases():
    """RPM=600 时 acquire 应在 ticker 放行后返回。"""
    gate = RateLimitGate(rpm=600)
    await gate.start()
    try:

        async def task():
            await gate.acquire(priority=2)
            return "done"

        result = await asyncio.wait_for(task(), timeout=3.0)
        assert result == "done"
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_release_order_fifo_same_priority():
    """同优先级的请求应按 FIFO 顺序放行。"""
    gate = RateLimitGate(rpm=100)
    await gate.start()
    results = []
    try:

        async def worker(i):
            await gate.acquire(priority=2)
            results.append(i)

        tasks = [asyncio.create_task(worker(i)) for i in range(3)]
        # 确保所有 task 进入 acquire 等待
        await asyncio.sleep(0.05)
        await asyncio.gather(*tasks)
        assert results == [0, 1, 2]
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_priority_multiple_queued():
    """多个不同优先级入队时，_pick_next 应先放行最高优先级（数值最小）。"""
    gate = RateLimitGate(rpm=100)
    evt_chat = asyncio.Event()
    evt_bg = asyncio.Event()

    # 手动往堆里放两个项（bg 先入，chat 后入，但 chat 优先级更高）
    gate._seq_counter += 1
    item_bg = _QueueItem(priority=2, _seq=gate._seq_counter, event=evt_bg)
    heapq.heappush(gate._heap, item_bg)
    gate._seq_counter += 1
    item_chat = _QueueItem(priority=0, _seq=gate._seq_counter, event=evt_chat)
    heapq.heappush(gate._heap, item_chat)

    gate._pick_next()
    assert evt_chat.is_set()
    assert not evt_bg.is_set()


# === 429 重试 ===


@pytest.mark.asyncio
async def test_429_retry_after_pause(mock_request_factory):
    """429 后应暂停 retry_after 秒后重试。"""
    gate = RateLimitGate(rpm=100)
    await gate.start()
    try:
        request = mock_request_factory([429, 200])
        result = await gate.run_with_retry(priority=0, do_request=request)
        assert result["status"] == 200
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_429_no_retry_after_uses_exponential_backoff():
    """429 无 retry_after 时应使用指数退避（5s base）。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=100)
    await gate.start()
    try:
        call_count = 0

        async def do_request():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": 429, "text": "", "retry_after": None}
            return {"status": 200, "text": "ok", "retry_after": None}

        real_sleep = asyncio.sleep
        sleep_times = []

        async def mock_sleep(delay):
            sleep_times.append(delay)
            # 用真实的 sleep(0) yield 控制给 ticker
            await real_sleep(0)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await gate.run_with_retry(priority=0, do_request=do_request)

        assert result["status"] == 200
        # 第一次 429 无 retry_after，应等 _429_BASE_WAIT * 2^0 = 5s
        retry_sleeps = [s for s in sleep_times if s > 1]
        assert retry_sleeps[0] == 5.0
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_429_no_retry_after_exponential_sequence():
    """连续 429 无 retry_after 时退避应递增：5s → 10s。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=100, max_retries=2)
    await gate.start()
    try:
        call_count = 0

        async def do_request():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"status": 429, "text": "", "retry_after": None}
            return {"status": 200, "text": "ok", "retry_after": None}

        real_sleep = asyncio.sleep
        sleep_times = []

        async def mock_sleep(delay):
            sleep_times.append(delay)
            await real_sleep(0)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await gate.run_with_retry(priority=0, do_request=do_request)

        assert result["status"] == 200
        # 第 1 次重试：5*2^0=5s，第 2 次重试：5*2^1=10s
        retry_sleeps = [s for s in sleep_times if s > 1]
        assert retry_sleeps == [5.0, 10.0]
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_429_retry_after_zero_not_treated_as_missing():
    """retry_after=0 应被使用（立即重试），而非 fallback 到指数退避。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=100)
    await gate.start()
    try:
        call_count = 0

        async def do_request():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": 429, "text": "", "retry_after": 0}
            return {"status": 200, "text": "ok", "retry_after": None}

        real_sleep = asyncio.sleep
        sleep_times = []

        async def mock_sleep(delay):
            sleep_times.append(delay)
            await real_sleep(0)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await gate.run_with_retry(priority=0, do_request=do_request)

        assert result["status"] == 200
        # retry_after=0 应用 0 秒等待，不应有 >1s 的退避
        retry_sleeps = [s for s in sleep_times if s > 1]
        assert retry_sleeps == []
    finally:
        await gate.stop()


# === 网络错误重试 ===


@pytest.mark.asyncio
async def test_network_error_retry(mock_request_factory):
    """网络错误(0)后应进重试队列，由 ticker 放行。"""
    gate = RateLimitGate(rpm=100)
    await gate.start()
    try:
        request = mock_request_factory([0, 200])
        result = await gate.run_with_retry(priority=0, do_request=request)
        assert result["status"] == 200
    finally:
        await gate.stop()


# === 5xx 重试 ===


@pytest.mark.asyncio
async def test_5xx_retry_after_interval(mock_request_factory):
    """5xx 后应进重试队列，由 ticker 放行。"""
    gate = RateLimitGate(rpm=60)  # interval=1s
    await gate.start()
    try:
        request = mock_request_factory([500, 200])
        result = await gate.run_with_retry(priority=0, do_request=request)
        assert result["status"] == 200
    finally:
        await gate.stop()


# === 非 429 错误行为验证 ===


@pytest.mark.asyncio
async def test_network_error_does_not_trigger_gate_pause():
    """网络错误(0)不应触发门级暂停（不推进退避）。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=100, max_retries=2)
    await gate.start()
    try:
        call_count = 0

        async def do_request():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": 0, "text": "", "retry_after": None}
            return {"status": 200, "text": "ok", "retry_after": None}

        real_sleep = asyncio.sleep

        async def mock_sleep(delay):
            # 在 sleep 期间检查：_backoff_sleep_until 不应被推进
            if delay >= 0.5:
                assert gate._backoff_sleep_until == 0.0, "网络错误不应推进退避"
            await real_sleep(0)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await gate.run_with_retry(priority=0, do_request=do_request)

        assert result["status"] == 200
        # 退避应保持初始状态
        assert gate._backoff_level == 0
        assert gate._backoff_sleep_until == 0.0
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_5xx_does_not_trigger_gate_pause():
    """5xx 错误不应触发门级暂停（不推进退避）。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=100, max_retries=2)
    await gate.start()
    try:
        call_count = 0

        async def do_request():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": 500, "text": "", "retry_after": None}
            return {"status": 200, "text": "ok", "retry_after": None}

        real_sleep = asyncio.sleep

        async def mock_sleep(delay):
            # 在 sleep 期间检查：_backoff_sleep_until 不应被推进
            if delay >= 0.5:
                assert gate._backoff_sleep_until == 0.0, "5xx 不应推进退避"
            await real_sleep(0)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await gate.run_with_retry(priority=0, do_request=do_request)

        assert result["status"] == 200
        # 退避应保持初始状态
        assert gate._backoff_level == 0
        assert gate._backoff_sleep_until == 0.0
    finally:
        await gate.stop()


# === 混合错误类型 ===


@pytest.mark.asyncio
async def test_mixed_errors_retry(mock_request_factory):
    """先 429 再 500 再 200，都走重试队列，应依次重试成功。"""
    gate = RateLimitGate(rpm=60)  # interval=1s
    await gate.start()
    try:
        request = mock_request_factory([429, 500, 200])
        result = await gate.run_with_retry(priority=0, do_request=request)
        assert result["status"] == 200
    finally:
        await gate.stop()


# === 最大重试 ===


@pytest.mark.asyncio
async def test_max_retries_exceeded_raises(mock_request_factory):
    """连续 429 超过 max_retries 应抛 RuntimeError。"""
    gate = RateLimitGate(rpm=100, max_retries=2)
    await gate.start()
    try:
        request = mock_request_factory([429, 429, 429, 429])
        with pytest.raises(RuntimeError, match="failed after"):
            await gate.run_with_retry(priority=0, do_request=request)
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_max_retries_other_errors(mock_request_factory):
    """连续 500 超过 max_retries 应抛 RuntimeError。"""
    gate = RateLimitGate(rpm=100, max_retries=2)
    await gate.start()
    try:
        request = mock_request_factory([500, 500, 500, 500])
        with pytest.raises(RuntimeError, match="failed after"):
            await gate.run_with_retry(priority=0, do_request=request)
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_max_retries_zero():
    """max_retries=0 时首次失败应立即抛异常。"""
    gate = RateLimitGate(rpm=100, max_retries=0)
    await gate.start()
    try:
        idx = 0

        async def do_request():
            nonlocal idx
            idx += 1
            return {"status": 500, "text": "", "retry_after": None}

        with pytest.raises(RuntimeError, match="failed after 1"):
            await gate.run_with_retry(priority=0, do_request=do_request)
        assert idx == 1  # 只调了一次，没有重试
    finally:
        await gate.stop()


# === 队列满 ===


@pytest.mark.asyncio
async def test_queue_full_timeout():
    """队列满时新请求应超时。"""
    gate = RateLimitGate(rpm=1, max_queue=1, queue_wait_timeout=0.3)
    # 不启动 ticker，手动占位
    gate._seq_counter += 1
    item = _QueueItem(priority=2, _seq=gate._seq_counter, event=asyncio.Event())
    heapq.heappush(gate._heap, item)
    with pytest.raises(asyncio.TimeoutError, match="queue full"):
        await gate.acquire(priority=2)


# === 不限速 ===


@pytest.mark.asyncio
async def test_rpm_none_no_rate_limit():
    """rpm=None 时 acquire 应立即返回。"""
    gate = RateLimitGate(rpm=None)
    await gate.start()
    try:
        await asyncio.wait_for(gate.acquire(priority=2), timeout=0.1)
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_rpm_none_run_with_retry(mock_request_factory):
    """不限速模式下 run_with_retry 应正常工作。"""
    gate = RateLimitGate(rpm=None)
    request = mock_request_factory([200])
    result = await gate.run_with_retry(priority=0, do_request=request)
    assert result["status"] == 200


@pytest.mark.asyncio
async def test_rpm_none_retry_on_error(mock_request_factory):
    """不限速模式下 429 重试应正常工作。"""
    gate = RateLimitGate(rpm=None)
    request = mock_request_factory([429, 200])
    result = await gate.run_with_retry(priority=0, do_request=request)
    assert result["status"] == 200


@pytest.mark.asyncio
async def test_rpm_none_429_no_retry_after_exponential_backoff():
    """不限速模式下 429 无 retry_after 时应使用指数退避。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=None, max_retries=2)
    call_count = 0

    async def do_request():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return {"status": 429, "text": "", "retry_after": None}
        return {"status": 200, "text": "ok", "retry_after": None}

    real_sleep = asyncio.sleep
    sleep_times = []

    async def mock_sleep(delay):
        sleep_times.append(delay)
        await real_sleep(0)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        result = await gate.run_with_retry(priority=0, do_request=do_request)

    assert result["status"] == 200
    # rpm=None 分支无 ticker，所有 sleep 都是 retry 的
    # 第 1 次重试：5*2^0=5s，第 2 次重试：5*2^1=10s
    assert sleep_times == [5.0, 10.0]


# === 切片 1：退避状态管理 ===


@pytest.mark.asyncio
async def test_backoff_initial_level_is_zero():
    """退避初始档位应为 0。"""
    gate = RateLimitGate(rpm=100)
    assert gate._backoff_level == 0


@pytest.mark.asyncio
async def test_backoff_steps_progression():
    """退避阶梯应为 5s -> 10s -> 10s（封顶）。"""
    gate = RateLimitGate(rpm=100)
    assert gate._current_backoff() == 5.0  # level 0

    gate._advance_backoff()
    assert gate._current_backoff() == 10.0  # level 1

    gate._advance_backoff()
    assert gate._current_backoff() == 10.0  # level 2，封顶在 10s

    gate._advance_backoff()
    assert gate._current_backoff() == 10.0  # 不再增长


@pytest.mark.asyncio
async def test_backoff_reset():
    """退避重置应将档位归零。"""
    gate = RateLimitGate(rpm=100)
    gate._advance_backoff()
    gate._advance_backoff()
    # _BACKOFF_STEPS 只有 2 档，封顶在 index=1
    assert gate._backoff_level == 1

    gate._reset_backoff()
    assert gate._backoff_level == 0
    assert gate._current_backoff() == 5.0


# === 切片 2：重试队列数据结构 ===


@pytest.mark.asyncio
async def test_retry_queue_initially_empty():
    """重试队列初始应为空。"""
    gate = RateLimitGate(rpm=100)
    assert len(gate._retry_queue) == 0


@pytest.mark.asyncio
async def test_retry_item_has_retries_count():
    """_RetryItem 应有 retries 计数字段。"""
    from src.llm.rate_limit_gate import _RetryItem

    evt = asyncio.Event()
    item = _RetryItem(priority=0, _seq=1, retries=0, event=evt)
    assert item.retries == 0
    item2 = _RetryItem(priority=0, _seq=2, retries=3, event=evt)
    assert item2.retries == 3


@pytest.mark.asyncio
async def test_retry_queue_fifo_order():
    """重试队列应保持 FIFO 顺序。"""
    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100)
    items = []
    for i in range(3):
        item = _RetryItem(priority=0, _seq=i, retries=i, event=asyncio.Event())
        gate._retry_queue.append(item)
        items.append(item)

    # FIFO: 先进先出
    assert gate._retry_queue.popleft() is items[0]
    assert gate._retry_queue.popleft() is items[1]
    assert gate._retry_queue.popleft() is items[2]


# === 切片 3：ticker 优先取重试队列 ===


@pytest.mark.asyncio
async def test_pick_next_prefers_retry_queue():
    """_pick_next 应优先从重试队列取，而非堆。"""
    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100)

    # 放一个新请求到堆
    heap_evt = asyncio.Event()
    gate._seq_counter += 1
    item_heap = _QueueItem(priority=0, _seq=gate._seq_counter, event=heap_evt)
    heapq.heappush(gate._heap, item_heap)

    # 放一个重试请求到重试队列
    retry_evt = asyncio.Event()
    retry_item = _RetryItem(priority=2, _seq=99, retries=1, event=retry_evt)
    gate._retry_queue.append(retry_item)

    # _pick_next 应返回重试队列的 item
    picked = gate._pick_next()
    assert picked is retry_evt
    assert retry_evt.is_set()
    assert not heap_evt.is_set()  # 堆里的不应被放行


@pytest.mark.asyncio
async def test_pick_next_falls_back_to_heap():
    """重试队列为空时 _pick_next 应从堆取。"""
    gate = RateLimitGate(rpm=100)

    heap_evt = asyncio.Event()
    gate._seq_counter += 1
    item_heap = _QueueItem(priority=0, _seq=gate._seq_counter, event=heap_evt)
    heapq.heappush(gate._heap, item_heap)

    picked = gate._pick_next()
    assert picked is heap_evt
    assert heap_evt.is_set()


@pytest.mark.asyncio
async def test_pick_next_returns_none_when_empty():
    """两个队列都为空时 _pick_next 应返回 None。"""
    gate = RateLimitGate(rpm=100)
    picked = gate._pick_next()
    assert picked is None


# === 切片 4：429 退避暂停 ===


@pytest.mark.asyncio
async def test_backoff_sleep_until_initially_zero():
    """_backoff_sleep_until 初始应为 0。"""
    gate = RateLimitGate(rpm=100)
    assert gate._backoff_sleep_until == 0.0


@pytest.mark.asyncio
async def test_on_429_enqueues_and_advances_backoff():
    """_on_429 应将 item 入重试队列并推进退避档位。"""
    from unittest.mock import patch

    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100)
    real_sleep = asyncio.sleep
    sleep_calls = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)
        # 检查 sleep 前的状态
        assert len(gate._retry_queue) == 1
        assert gate._retry_queue[0] is item
        assert gate._backoff_level == 1
        assert gate._backoff_sleep_until > 0
        await real_sleep(0)

    evt = asyncio.Event()
    item = _RetryItem(priority=0, _seq=1, retries=0, event=evt)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        await gate._on_429(item, retry_after=None)

    # sleep 时长：先取 level 0 的退避 = 5s，再 advance 0→1
    assert sleep_calls == [5.0]


@pytest.mark.asyncio
async def test_on_429_uses_retry_after_when_provided():
    """_on_429 有 retry_after 时应使用它而非门级退避。"""
    from unittest.mock import patch

    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100)
    real_sleep = asyncio.sleep
    sleep_calls = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)
        await real_sleep(0)

    evt = asyncio.Event()
    item = _RetryItem(priority=0, _seq=1, retries=0, event=evt)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        await gate._on_429(item, retry_after=3.0)

    # 应使用 retry_after=3.0 而非门级退避
    assert sleep_calls == [3.0]


@pytest.mark.asyncio
async def test_on_429_uses_backoff_when_no_retry_after():
    """_on_429 无 retry_after 时应使用门级退避。"""
    from unittest.mock import patch

    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100)
    real_sleep = asyncio.sleep
    sleep_calls = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)
        await real_sleep(0)

    evt = asyncio.Event()
    item = _RetryItem(priority=0, _seq=1, retries=0, event=evt)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        await gate._on_429(item, retry_after=None)

    # 先取 level 0 的退避 = 5s，再 advance 0→1
    assert sleep_calls == [5.0]


@pytest.mark.asyncio
async def test_on_429_concurrent_only_advances_once():
    """并发 429 时退避只应推进一次（已在暂停中不再推进）。"""
    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100)

    item1 = _RetryItem(priority=0, _seq=1, retries=0, event=asyncio.Event())
    item2 = _RetryItem(priority=0, _seq=2, retries=0, event=asyncio.Event())

    # 用 mock_sleep 避免真实等待
    from unittest.mock import patch

    real_sleep = asyncio.sleep

    async def fast_sleep(_):
        await real_sleep(0)

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await gate._on_429(item1, retry_after=None)
        # 第一次：level 0 → 1，backoff = 5s
        assert gate._backoff_level == 1

        await gate._on_429(item2, retry_after=None)
        # 第二次：已在暂停中（_backoff_sleep_until > 0），不应再推进
        assert gate._backoff_level == 1  # 仍然是 1，不是 2

    # 两个 item 都应入队
    assert len(gate._retry_queue) == 2


# === 切片 5：run_with_retry 改造 ===


@pytest.mark.asyncio
async def test_run_with_retry_429_advances_backoff_level():
    """429 后 run_with_retry 应推进退避档位（新行为）。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=100, max_retries=2)
    await gate.start()
    try:
        call_count = 0

        async def do_request():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": 429, "text": "", "retry_after": None}
            return {"status": 200, "text": "ok", "retry_after": None}

        real_sleep = asyncio.sleep

        async def mock_sleep(delay):
            gate._backoff_sleep_until = 0.0
            await real_sleep(0)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            # 429 前退避为 0
            assert gate._backoff_level == 0
            result = await gate.run_with_retry(priority=0, do_request=do_request)

        assert result["status"] == 200
        # 成功后退避应重置为 0
        assert gate._backoff_level == 0
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_run_with_retry_two_429s_uses_gate_level_backoff():
    """连续两次 429 应使用门级退避阶梯（5s, 10s），不是旧的指数退避。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=100, max_retries=2)
    await gate.start()
    try:
        call_count = 0

        async def do_request():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"status": 429, "text": "", "retry_after": None}
            return {"status": 200, "text": "ok", "retry_after": None}

        real_sleep = asyncio.sleep
        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)
            gate._backoff_sleep_until = 0.0
            await real_sleep(0)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            result = await gate.run_with_retry(priority=0, do_request=do_request)

        assert result["status"] == 200
        # 门级退避：第一次 5s（level 0），第二次 10s（level 1）
        # 过滤掉 ticker interval（< 1s）只看退避 sleep
        backoff_sleeps = [s for s in sleep_calls if s > 1.0]
        assert backoff_sleeps == [5.0, 10.0]
    finally:
        await gate.stop()


# === 切片 6：请求独立 retries 计数 ===


@pytest.mark.asyncio
async def test_on_429_raises_when_max_retries_exceeded():
    """_on_429 在 retries >= max_retries 时应抛异常。"""
    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100, max_retries=2)
    evt = asyncio.Event()
    # retries=2 已达 max_retries，应立即抛异常
    item = _RetryItem(priority=0, _seq=1, retries=2, event=evt)

    with pytest.raises(RuntimeError, match="failed after"):
        await gate._on_429(item, retry_after=None)

    # 不应入队
    assert len(gate._retry_queue) == 0


@pytest.mark.asyncio
async def test_on_429_allows_retries_below_max():
    """_on_429 在 retries < max_retries 时应正常入队。"""
    from unittest.mock import patch

    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100, max_retries=2)
    real_sleep = asyncio.sleep

    async def fast_sleep(_):
        await real_sleep(0)

    # retries=1 < max_retries=2，应正常入队
    item = _RetryItem(priority=0, _seq=1, retries=1, event=asyncio.Event())

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await gate._on_429(item, retry_after=None)

    assert len(gate._retry_queue) == 1


# === 切片 8：边界与兼容 ===


@pytest.mark.asyncio
async def test_stop_clears_retry_queue():
    """stop() 应清理重试队列。"""
    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100)
    await gate.start()

    # 往重试队列里放几个 item
    for i in range(3):
        gate._retry_queue.append(_RetryItem(priority=0, _seq=i, retries=0, event=asyncio.Event()))
    assert len(gate._retry_queue) == 3

    await gate.stop()
    assert len(gate._retry_queue) == 0


@pytest.mark.asyncio
async def test_rpm_none_old_logic_unchanged():
    """rpm=None 应完全走旧逻辑，不使用重试队列。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=None, max_retries=2)
    call_count = 0

    async def do_request():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return {"status": 429, "text": "", "retry_after": None}
        return {"status": 200, "text": "ok", "retry_after": None}

    real_sleep = asyncio.sleep
    sleep_times = []

    async def mock_sleep(delay):
        sleep_times.append(delay)
        await real_sleep(0)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        result = await gate.run_with_retry(priority=0, do_request=do_request)

    assert result["status"] == 200
    # rpm=None 走旧逻辑：指数退避 5s, 10s
    assert sleep_times == [5.0, 10.0]
    # 重试队列不应被使用
    assert len(gate._retry_queue) == 0


@pytest.mark.asyncio
async def test_retry_after_overrides_backoff():
    """retry_after 应覆盖门级退避时间。"""
    from unittest.mock import patch

    from src.llm.rate_limit_gate import _RetryItem

    gate = RateLimitGate(rpm=100)
    real_sleep = asyncio.sleep
    sleep_calls = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)
        await real_sleep(0)

    item = _RetryItem(priority=0, _seq=1, retries=0, event=asyncio.Event())

    with patch("asyncio.sleep", side_effect=mock_sleep):
        await gate._on_429(item, retry_after=7.5)

    # retry_after=7.5 应覆盖门级退避（本应是 5s）
    assert 7.5 in sleep_calls


# === 在飞请求数控制（max_inflight）===


@pytest.mark.asyncio
async def test_inflight_basic_pairing(mock_request_factory):
    """基本配对：成功请求后 _inflight 应归零。"""
    gate = RateLimitGate(rpm=None, max_inflight=5)
    request = mock_request_factory([200])

    assert gate._inflight == 0
    result = await gate.run_with_retry(priority=0, do_request=request)
    assert result["status"] == 200
    assert gate._inflight == 0


@pytest.mark.asyncio
async def test_inflight_limit_enforced():
    """max_inflight=2 时，任意时刻在飞数不超过 2，第 3 个请求应排队等待。"""
    gate = RateLimitGate(rpm=None, max_inflight=2)
    started = asyncio.Event()
    release = asyncio.Event()
    concurrent_count = 0
    max_concurrent_seen = 0
    lock = asyncio.Lock()

    async def do_request():
        nonlocal concurrent_count, max_concurrent_seen
        async with lock:
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            if concurrent_count == 2:
                started.set()
        await release.wait()
        async with lock:
            concurrent_count -= 1
        return {"status": 200, "text": "", "retry_after": None}

    tasks = [
        asyncio.create_task(gate.run_with_retry(priority=0, do_request=do_request))
        for _ in range(5)
    ]

    # 等待两个请求进入 do_request（达到上限）
    await asyncio.wait_for(started.wait(), timeout=2.0)
    await asyncio.sleep(0.05)

    assert gate._inflight == 2
    assert max_concurrent_seen <= 2
    # 第 3 个请求应仍在排队（未进入 do_request）
    assert concurrent_count == 2

    release.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5.0)
    assert all(r["status"] == 200 for r in results)
    assert max_concurrent_seen <= 2
    assert gate._inflight == 0


@pytest.mark.asyncio
async def test_inflight_not_double_counted_on_429_retry(mock_request_factory):
    """429 重试不应重复占用在飞名额：整个流程 _inflight 净变化为 0。"""
    gate = RateLimitGate(rpm=None, max_inflight=3, max_retries=2)
    request = mock_request_factory([429, 200])

    snapshots = []
    real_request = request

    async def tracking_request():
        snapshots.append(gate._inflight)
        return await real_request()

    from unittest.mock import patch

    real_sleep = asyncio.sleep

    async def mock_sleep(delay):
        await real_sleep(0)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        result = await gate.run_with_retry(priority=0, do_request=tracking_request)

    assert result["status"] == 200
    # 整个重试过程中应一直占用同一个名额（不会变成 0 或 2）
    assert snapshots == [1, 1]
    assert gate._inflight == 0


@pytest.mark.asyncio
async def test_inflight_released_on_4xx_non_retryable(mock_request_factory):
    """4xx 非重试错误：finally 应释放在飞名额。

    注意：「not retryable」分支只存在于限速模式（rpm 非 None）；
    rpm=None 的 inline 重试逻辑对所有非 200 状态码一视同仁地重试。
    """
    gate = RateLimitGate(rpm=6000, max_inflight=2)
    await gate.start()
    try:
        request = mock_request_factory([400])

        with pytest.raises(RuntimeError, match="not retryable"):
            await gate.run_with_retry(priority=0, do_request=request)

        assert gate._inflight == 0
    finally:
        await gate.stop()


@pytest.mark.asyncio
async def test_inflight_released_on_max_retries_429(mock_request_factory):
    """超过 max_retries 的 429：finally 应释放在飞名额。"""
    from unittest.mock import patch

    gate = RateLimitGate(rpm=None, max_inflight=2, max_retries=1)
    request = mock_request_factory([429, 429, 429])

    real_sleep = asyncio.sleep

    async def mock_sleep(delay):
        await real_sleep(0)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        with pytest.raises(RuntimeError, match="failed after"):
            await gate.run_with_retry(priority=0, do_request=request)

    assert gate._inflight == 0


@pytest.mark.asyncio
async def test_inflight_released_on_max_retries_5xx(mock_request_factory):
    """超过 max_retries 的 5xx：finally 应释放在飞名额。"""
    gate = RateLimitGate(rpm=None, max_inflight=2, max_retries=1)
    request = mock_request_factory([500, 500, 500])

    with pytest.raises(RuntimeError, match="failed after"):
        await gate.run_with_retry(priority=0, do_request=request)

    assert gate._inflight == 0


@pytest.mark.asyncio
async def test_inflight_released_on_gate_stop_with_inflight_requests():
    """gate.stop() 时仍有在飞请求：等待中的协程应被唤醒并释放名额。"""
    gate = RateLimitGate(rpm=100, max_inflight=2)
    await gate.start()

    hold = asyncio.Event()

    async def slow_request():
        await hold.wait()
        return {"status": 200, "text": "", "retry_after": None}

    task = asyncio.create_task(gate.run_with_retry(priority=0, do_request=slow_request))
    await asyncio.sleep(0.1)

    await gate.stop()
    hold.set()

    with pytest.raises((asyncio.CancelledError, RuntimeError)):
        await asyncio.wait_for(task, timeout=2.0)

    assert gate._inflight == 0


# === 取消场景 ===


@pytest.mark.asyncio
async def test_inflight_released_on_cancel_during_do_request():
    """do_request 执行期间被 wait_for 超时取消：应正确释放在飞名额。"""
    gate = RateLimitGate(rpm=None, max_inflight=2)

    async def slow_request():
        await asyncio.sleep(10)
        return {"status": 200, "text": "", "retry_after": None}

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            gate.run_with_retry(priority=0, do_request=slow_request), timeout=0.2
        )

    # 等待 cancel 传播完成（finally 块执行）
    await asyncio.sleep(0.05)
    assert gate._inflight == 0


@pytest.mark.asyncio
async def test_inflight_released_on_cancel_while_waiting_for_slot():
    """在 _inflight_cv.wait() 等待名额期间被 wait_for 超时取消：应正确释放名额。"""
    gate = RateLimitGate(rpm=None, max_inflight=1)
    hold = asyncio.Event()

    async def first_request():
        await hold.wait()
        return {"status": 200, "text": "", "retry_after": None}

    async def quick_request():
        return {"status": 200, "text": "", "retry_after": None}

    # 第一个请求占用唯一名额并挂起
    first_task = asyncio.create_task(gate.run_with_retry(priority=0, do_request=first_request))
    await asyncio.sleep(0.05)
    assert gate._inflight == 1

    # 第二个请求应阻塞在 _acquire_inflight_slot 的 cv.wait() 上，被取消
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            gate.run_with_retry(priority=0, do_request=quick_request), timeout=0.2
        )

    await asyncio.sleep(0.05)
    # 取消的协程不应增加 _inflight（仍为 1，被第一个请求占用）
    assert gate._inflight == 1

    hold.set()
    result = await asyncio.wait_for(first_task, timeout=2.0)
    assert result["status"] == 200
    assert gate._inflight == 0


# === 压力测试 ===


@pytest.mark.asyncio
async def test_inflight_stress_many_requests():
    """循环 N 个成功请求（N 远大于上限），_inflight 全程不为负、不超限、最终归零。"""
    gate = RateLimitGate(rpm=None, max_inflight=4)
    n = 50
    max_seen = 0
    min_seen = 0
    lock = asyncio.Lock()

    async def do_request():
        nonlocal max_seen, min_seen
        async with lock:
            max_seen = max(max_seen, gate._inflight)
            min_seen = min(min_seen, gate._inflight)
        await asyncio.sleep(0.01)
        return {"status": 200, "text": "", "retry_after": None}

    tasks = [
        asyncio.create_task(gate.run_with_retry(priority=0, do_request=do_request))
        for _ in range(n)
    ]
    results = await asyncio.gather(*tasks)

    assert all(r["status"] == 200 for r in results)
    assert min_seen >= 0
    assert max_seen <= 4
    assert gate._inflight == 0
