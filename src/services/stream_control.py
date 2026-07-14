import asyncio
from dataclasses import dataclass, field


@dataclass
class StreamControl:
    _pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    _stopped: bool = False

    def __post_init__(self) -> None:
        self._pause_event.set()

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def stop(self) -> None:
        self._stopped = True
        self._pause_event.set()  # 解除可能正在等待的 wait()

    @property
    def stopped(self) -> bool:
        return self._stopped

    async def wait_if_paused(self) -> bool:
        """暂停时挂起，恢复后返回。返回 True 表示应当终止生成。"""
        await self._pause_event.wait()
        return self._stopped


_controls: dict[str, StreamControl] = {}


def start_stream(world_id: str) -> StreamControl:
    ctrl = StreamControl()
    _controls[world_id] = ctrl
    return ctrl


def get_control(world_id: str) -> StreamControl | None:
    return _controls.get(world_id)


def end_stream(world_id: str) -> None:
    _controls.pop(world_id, None)
