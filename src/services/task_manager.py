"""M6 TaskManager — 线程安全的后台任务状态管理。"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0
    message: str = ""
    result: dict | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


class TaskManager:
    _instance: "TaskManager | None" = None
    _singleton_lock = threading.Lock()
    _tasks: dict[str, Task]
    _task_lock: threading.Lock

    def __new__(cls):
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._tasks = {}
                    instance._task_lock = threading.Lock()
                    cls._instance = instance
        return cls._instance

    def create_task(self, task_type: str, metadata: dict | None = None) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now()
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        with self._task_lock:
            self._tasks[task_id] = task
        return task_id

    def get_task(self, task_id: str) -> Task | None:
        with self._task_lock:
            return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        progress: int | None = None,
        message: str | None = None,
        result: dict | None = None,
        error: str | None = None,
    ):
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.updated_at = datetime.now()
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = progress
            if message is not None:
                task.message = message
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error

    def complete_task(self, task_id: str, result: dict):
        self.update_task(task_id, status=TaskStatus.COMPLETED, progress=100, result=result)

    def fail_task(self, task_id: str, error: str):
        self.update_task(task_id, status=TaskStatus.FAILED, error=error)
