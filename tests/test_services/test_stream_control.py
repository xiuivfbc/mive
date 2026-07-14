"""StreamControl 单元测试（纯内存，无 IO）。"""

import asyncio

from src.services.stream_control import (
    StreamControl,
    end_stream,
    get_control,
    start_stream,
)


class TestStreamControlState:
    def test_new_control_is_not_stopped(self):
        ctrl = StreamControl()
        assert ctrl.stopped is False

    def test_stop_sets_stopped(self):
        ctrl = StreamControl()
        ctrl.stop()
        assert ctrl.stopped is True

    def test_pause_then_resume_does_not_stop(self):
        ctrl = StreamControl()
        ctrl.pause()
        ctrl.resume()
        assert ctrl.stopped is False

    def test_stop_after_pause_sets_stopped(self):
        ctrl = StreamControl()
        ctrl.pause()
        ctrl.stop()
        assert ctrl.stopped is True


class TestStreamControlWaitIfPaused:
    async def test_not_paused_returns_false_immediately(self):
        ctrl = StreamControl()
        result = await ctrl.wait_if_paused()
        assert result is False

    async def test_stopped_returns_true(self):
        ctrl = StreamControl()
        ctrl.stop()
        result = await ctrl.wait_if_paused()
        assert result is True

    async def test_paused_then_resumed_returns_false(self):
        ctrl = StreamControl()
        ctrl.pause()

        async def _resume_after():
            await asyncio.sleep(0.01)
            ctrl.resume()

        asyncio.create_task(_resume_after())
        result = await ctrl.wait_if_paused()
        assert result is False

    async def test_paused_then_stopped_returns_true(self):
        ctrl = StreamControl()
        ctrl.pause()

        async def _stop_after():
            await asyncio.sleep(0.01)
            ctrl.stop()

        asyncio.create_task(_stop_after())
        result = await ctrl.wait_if_paused()
        assert result is True

    async def test_multiple_waits_after_resume(self):
        ctrl = StreamControl()
        # Should return immediately both times since not paused
        r1 = await ctrl.wait_if_paused()
        r2 = await ctrl.wait_if_paused()
        assert r1 is False
        assert r2 is False


class TestStreamRegistry:
    def setup_method(self):
        # Clean up any leftover keys from previous tests
        from src.services import stream_control as sc

        sc._controls.clear()

    def test_start_stream_returns_control(self):
        ctrl = start_stream("world-1")
        assert isinstance(ctrl, StreamControl)

    def test_get_control_returns_registered(self):
        ctrl = start_stream("world-2")
        assert get_control("world-2") is ctrl

    def test_get_control_unknown_returns_none(self):
        assert get_control("no-such-world") is None

    def test_end_stream_removes_control(self):
        start_stream("world-3")
        end_stream("world-3")
        assert get_control("world-3") is None

    def test_end_stream_nonexistent_no_error(self):
        end_stream("world-nonexistent")  # should not raise

    def test_start_stream_replaces_old_control(self):
        ctrl1 = start_stream("world-4")
        ctrl2 = start_stream("world-4")
        assert get_control("world-4") is ctrl2
        assert ctrl1 is not ctrl2

    def test_multiple_worlds_independent(self):
        ctrl_a = start_stream("world-a")
        ctrl_b = start_stream("world-b")
        ctrl_a.stop()
        assert ctrl_b.stopped is False
