"""Tests for M6 TaskManager."""

import threading

from src.services.task_manager import TaskManager, TaskStatus


class TestTaskManager:
    def setup_method(self):
        # 每个测试用独立实例，避免单例污染
        self.tm = TaskManager.__new__(TaskManager)
        self.tm._tasks = {}
        self.tm._task_lock = threading.Lock()

    def test_create_task_returns_id(self):
        task_id = self.tm.create_task("graph_build")
        assert task_id is not None
        assert isinstance(task_id, str)
        assert len(task_id) > 0

    def test_task_starts_as_pending(self):
        task_id = self.tm.create_task("graph_build")
        task = self.tm.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0
        assert task.task_type == "graph_build"

    def test_update_task_progress(self):
        task_id = self.tm.create_task("graph_build")
        self.tm.update_task(task_id, progress=50, message="building...")
        task = self.tm.get_task(task_id)
        assert task.progress == 50
        assert task.message == "building..."

    def test_update_task_status(self):
        task_id = self.tm.create_task("graph_build")
        self.tm.update_task(task_id, status=TaskStatus.PROCESSING)
        task = self.tm.get_task(task_id)
        assert task.status == TaskStatus.PROCESSING

    def test_complete_task(self):
        task_id = self.tm.create_task("graph_build")
        self.tm.complete_task(task_id, {"graph_id": "abc123"})
        task = self.tm.get_task(task_id)
        assert task.status == TaskStatus.COMPLETED
        assert task.progress == 100
        assert task.result == {"graph_id": "abc123"}

    def test_fail_task(self):
        task_id = self.tm.create_task("graph_build")
        self.tm.fail_task(task_id, "connection timeout")
        task = self.tm.get_task(task_id)
        assert task.status == TaskStatus.FAILED
        assert task.error == "connection timeout"

    def test_get_nonexistent_returns_none(self):
        assert self.tm.get_task("nonexistent") is None

    def test_metadata_stored(self):
        task_id = self.tm.create_task("graph_build", metadata={"world_id": "w1"})
        task = self.tm.get_task(task_id)
        assert task.metadata == {"world_id": "w1"}

    def test_thread_safety(self):
        """并发更新不会崩溃"""
        task_id = self.tm.create_task("graph_build")
        errors = []

        def worker(val):
            try:
                self.tm.update_task(task_id, progress=val)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        task = self.tm.get_task(task_id)
        assert task.progress in range(100)
