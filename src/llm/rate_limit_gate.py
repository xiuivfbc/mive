"""LLM 调用速率门（Rate Limit Gate）

按 RPM 定时放行，优先级排队，统一处理 429/5xx/网络错误重试。
"""

import asyncio
import heapq
import logging
from collections import deque
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 2  # 默认最多重试次数（首次 + 2 次重试 = 最多 3 次尝试）
_QUEUE_WAIT_TIMEOUT = 120.0  # 队列满时等待入队的最大秒数
_BACKOFF_STEPS = (5.0, 10.0)  # 门级退避阶梯：5s → 10s → 封顶 10s
_429_BASE_WAIT = _BACKOFF_STEPS[0]  # rpm=None 分支旧逻辑使用的 base wait


@dataclass(order=True)
class _QueueItem:
    """heapq 的元素，支持按 (priority, seq) 排序。"""

    priority: int
    _seq: int
    event: asyncio.Event = field(compare=False)
    cancelled: bool = field(compare=False, default=False)


@dataclass
class _RetryItem:
    """重试队列中的元素。"""

    priority: int
    _seq: int
    retries: int
    event: asyncio.Event
    cancelled: bool = False


class RateLimitGate:
    """定时放行 + 优先级堆 + 统一重试的速率门。

    参数
    ----
    rpm : int | None
        每分钟最大请求数。None 表示不限速，acquire 立即返回。
    max_retries : int
        最多重试次数。默认 2（首次 + 2 次 = 最多 3 次尝试）。
    max_queue : int
        队列最大长度。超出时新来的调用等待空位，超 120s 抛 TimeoutError。
    max_inflight : int | None
        在飞请求数上限（已发出、正在等待/生成响应、未完成的请求数）。
        None 表示不限制在飞数（如 BYOK 场景，靠 ticker rpm + 429 退避兜底）。
    """

    def __init__(
        self,
        rpm: int | None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        max_queue: int = 50,
        queue_wait_timeout: float = _QUEUE_WAIT_TIMEOUT,
        max_inflight: int | None = None,
    ):
        self.rpm = rpm
        self.max_retries = max_retries
        self.max_queue = max_queue
        self._queue_wait_timeout = queue_wait_timeout
        self._interval = (60.0 / rpm) if rpm else 0.0
        # 优先级堆：_QueueItem 按 (priority, seq) 排序
        self._heap: list[_QueueItem] = []
        self._seq_counter = 0  # 同优先级 FIFO 的自增序号
        self._ticker_task: asyncio.Task | None = None
        self._stopped = False
        # 门级退避状态
        self._backoff_level = 0  # 当前退避阶梯索引
        self._backoff_sleep_until: float = 0.0  # 退避暂停截止时间戳
        # 重试队列（FIFO）
        self._retry_queue: deque[_RetryItem] = deque()
        # 在飞请求数控制（与 ticker 节奏并行的第二重准入条件）
        self.max_inflight = max_inflight
        self._inflight = 0
        # 注意：Condition 唤醒顺序不保证遵循 acquire() 阶段的 priority 排序
        # （低优先级请求可能先于高优先级请求抢到在飞名额），这是有意接受的
        # 小概率公平性损失（量级小，5~6 个名额时影响可忽略）
        self._inflight_cv = asyncio.Condition()

    # ─────────────────── 在飞请求数控制 ───────────────────

    async def _acquire_inflight_slot(self) -> None:
        """获取一个在飞名额；max_inflight=None 时直接返回。"""
        if self.max_inflight is None:
            return
        async with self._inflight_cv:
            while self._inflight >= self.max_inflight:
                await self._inflight_cv.wait()
            self._inflight += 1

    async def _release_inflight_slot(self) -> None:
        """归还一个在飞名额；max_inflight=None 时直接返回。"""
        if self.max_inflight is None:
            return
        async with self._inflight_cv:
            self._inflight -= 1
            self._inflight_cv.notify(1)

    # ─────────────────── 生命周期 ───────────────────

    async def start(self) -> None:
        """启动 ticker 循环。"""
        self._stopped = False
        self._ticker_task = asyncio.create_task(self._ticker())

    def __del__(self) -> None:
        if self._ticker_task and not self._ticker_task.done():
            self._ticker_task.cancel()

    async def stop(self) -> None:
        """停止 ticker 并清理重试队列。"""
        self._stopped = True
        if self._ticker_task:
            self._ticker_task.cancel()
            try:
                await self._ticker_task
            except asyncio.CancelledError:
                pass
        # 唤醒所有等待中的重试协程，避免泄漏
        while self._retry_queue:
            item = self._retry_queue.popleft()
            item.cancelled = True
            item.event.set()
        # 唤醒所有在堆里 await evt.wait() 的协程，避免泄漏
        while self._heap:
            item = heapq.heappop(self._heap)
            item.cancelled = True
            item.event.set()

    # ─────────────────── 核心入口 ───────────────────

    async def acquire(self, priority: int = 2) -> None:
        """入队等待放行。

        不限速（rpm=None）时立即返回。
        队列满时等待空位，超 120s 抛 asyncio.TimeoutError。
        """
        if self.rpm is None:
            return

        # 懒启动 ticker（支持无需显式调用 start() 的短生命周期 gate，如 BYOK per-request gate）
        if self._ticker_task is None and not self._stopped:
            self._ticker_task = asyncio.create_task(self._ticker())

        # 等待堆有空位
        deadline = asyncio.get_running_loop().time() + self._queue_wait_timeout
        while len(self._heap) >= self.max_queue:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("rate_limit_gate: queue full, timed out waiting for slot")
            await asyncio.sleep(min(0.05, remaining))

        evt = asyncio.Event()
        self._seq_counter += 1
        item = _QueueItem(priority=priority, _seq=self._seq_counter, event=evt)
        heapq.heappush(self._heap, item)
        await evt.wait()
        if item.cancelled:
            raise asyncio.CancelledError("rate_limit_gate: gate stopped while waiting in queue")

    async def run_with_retry(
        self,
        priority: int,
        do_request,  # Callable[[], Awaitable[dict]]
    ) -> dict:
        """完整的 acquire→execute→retry 流程。

        do_request 应返回 {"status": int, "text": str, "retry_after": float | None}。
        - 200：直接返回，退避重置
        - 429：进重试队列，门级退避后由 ticker 放行
        - 网络错误(0) / 5xx：进重试队列，不暂停门，由 ticker 放行
        超过 self.max_retries 次重试则抛异常。
        rpm=None 时走旧的 inline 重试逻辑。
        """
        if self.rpm is None:
            # 不限速：直接执行，仍做重试
            # 在飞名额覆盖整个 run_with_retry 生命周期（含同一逻辑请求的所有重试尝试）
            await self._acquire_inflight_slot()
            try:
                retries = 0
                while True:
                    result = await do_request()
                    status = result.get("status", 0)
                    if status == 200:
                        return result
                    retry_after = result.get("retry_after")
                    if retries >= self.max_retries:
                        raise RuntimeError(
                            f"rate_limit_gate: request failed after "
                            f"{self.max_retries + 1} attempts, last status={status}"
                        )
                    retries += 1
                    if status == 429:
                        wait = (
                            retry_after
                            if retry_after is not None
                            else _429_BASE_WAIT * (2 ** (retries - 1))
                        )
                        _log.warning(
                            "gate(rpm=None): 429，%.1fs 后重试（第 %d 次）",
                            wait,
                            retries,
                        )
                        await asyncio.sleep(wait)
                    else:
                        await asyncio.sleep(0.1)
            finally:
                await self._release_inflight_slot()

        # 限速模式：入队等待放行
        await self.acquire(priority)

        # 在飞名额必须在 acquire() 成功返回之后获取：acquire 因队列满超时抛
        # TimeoutError 时不应计入在飞，且此时还未进入 try 块
        await self._acquire_inflight_slot()
        try:
            retries = 0
            while True:
                result = await do_request()
                status = result.get("status", 0)
                if status == 200:
                    self._reset_backoff()
                    return result

                if status == 429:
                    # 429 统一门级重试：入重试队列，退避后由 ticker 放行
                    # 在飞名额在退避期间持续持有（有意为之：顺带抑制新请求涌入）
                    if retries >= self.max_retries:
                        raise RuntimeError(
                            f"rate_limit_gate: request failed after "
                            f"{self.max_retries + 1} attempts, last status=429"
                        )
                    self._seq_counter += 1
                    retry_item = _RetryItem(
                        priority=priority,
                        _seq=self._seq_counter,
                        retries=retries,
                        event=asyncio.Event(),
                    )
                    await self._on_429(retry_item, result.get("retry_after"))
                    # 等待 ticker 从重试队列放行
                    await retry_item.event.wait()
                    if retry_item.cancelled:
                        raise asyncio.CancelledError(
                            "rate_limit_gate: gate stopped while waiting for retry"
                        )
                    retries += 1
                elif status == 0 or status >= 500:
                    # 网络错误(0) / 5xx：进重试队列，不暂停门
                    retries = await self._enqueue_retry(priority, retries, status)
                else:
                    # 4xx 客户端错误（非 429）：不重试，直接抛异常
                    raise RuntimeError(
                        f"rate_limit_gate: request failed with status={status}, not retryable"
                    )
        finally:
            await self._release_inflight_slot()

    # ─────────────────── ticker 循环 ───────────────────

    async def _ticker(self) -> None:
        """定时放行：每 interval 秒，优先从重试队列取，否则从堆取。"""
        while not self._stopped:
            if self._interval > 0:
                await asyncio.sleep(self._interval)
            else:
                # 不限速模式不应该走到这里，但防止 spin
                await asyncio.sleep(0.01)

            if self._stopped:
                break
            # 门级退避期间冻结 ticker
            now = asyncio.get_running_loop().time()
            if self._backoff_sleep_until > now:
                continue
            self._pick_next()

    def _pick_next(self) -> asyncio.Event | None:
        """优先从重试队列取，否则从堆取。返回被唤醒的 Event 或 None。"""
        if self._retry_queue:
            item = self._retry_queue.popleft()
            item.event.set()
            return item.event
        if self._heap:
            item = heapq.heappop(self._heap)
            item.event.set()
            return item.event
        return None

    # ─────────────────── 退避阶梯 ───────────────────

    def _current_backoff(self) -> float:
        """返回当前退避档位对应的等待秒数。"""
        idx = min(self._backoff_level, len(_BACKOFF_STEPS) - 1)
        return _BACKOFF_STEPS[idx]

    def _advance_backoff(self) -> None:
        """推进退避档位（封顶在最后一步）。"""
        if self._backoff_level < len(_BACKOFF_STEPS) - 1:
            self._backoff_level += 1

    def _reset_backoff(self) -> None:
        """重置退避档位到 0（成功请求后调用）。"""
        self._backoff_level = 0
        self._backoff_sleep_until = 0.0

    async def _on_429(self, item: _RetryItem, retry_after: float | None) -> None:
        """429 处理：计算退避、推进档位、入重试队列、gate 级 sleep。"""
        if item.retries >= self.max_retries:
            raise RuntimeError(
                f"rate_limit_gate: request failed after "
                f"{self.max_retries + 1} attempts, last status=429"
            )
        now = asyncio.get_running_loop().time()
        if self._backoff_sleep_until <= now:
            # 新一轮 429：取当前档位退避，推进档位，设置冻结截止
            wait = retry_after if retry_after is not None else self._current_backoff()
            self._advance_backoff()
            self._backoff_sleep_until = now + wait
        else:
            # 已在冻结中：piggyback 现有冻结剩余时间，不推进档位
            remaining = self._backoff_sleep_until - now
            if retry_after is not None and retry_after > remaining:
                # retry_after 要求更长等待时才延长冻结
                self._backoff_sleep_until = now + retry_after
                wait = retry_after
            else:
                wait = remaining

        self._retry_queue.append(item)

        frozen_until = self._backoff_sleep_until - asyncio.get_running_loop().time()
        _log.warning(
            "gate: 429，%.1fs 后恢复放行（第 %d 次）",
            max(frozen_until, 0),
            item.retries + 1,
        )
        await asyncio.sleep(wait)
        # 不显式清零——让时间戳自然过期，避免并发协程互相覆盖

    async def _enqueue_retry(self, priority: int, retries: int, status: int) -> int:
        """非 429 错误入重试队列。检查 max_retries，创建 _RetryItem 并等待 ticker 放行。

        返回更新后的 retries 计数。
        """
        if retries >= self.max_retries:
            raise RuntimeError(
                f"rate_limit_gate: request failed after "
                f"{self.max_retries + 1} attempts, last status={status}"
            )
        self._seq_counter += 1
        retry_item = _RetryItem(
            priority=priority,
            _seq=self._seq_counter,
            retries=retries,
            event=asyncio.Event(),
        )
        retries += 1
        self._retry_queue.append(retry_item)
        _log.warning(
            "gate: 状态码 %d，进重试队列（第 %d 次）",
            status,
            retries,
        )
        await retry_item.event.wait()
        if retry_item.cancelled:
            raise asyncio.CancelledError("rate_limit_gate: gate stopped while waiting for retry")
        return retries
