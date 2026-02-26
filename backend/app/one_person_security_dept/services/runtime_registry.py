"""Runtime task registry for Security Dept background execution."""

from __future__ import annotations

import asyncio

from app.core.settings import settings


class SecurityDeptRuntimeRegistry:
    """Tracks in-process asyncio tasks for cancellation and lifecycle."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(settings.security_dept_max_concurrent_tasks)

    async def register(self, task_id: str, task: asyncio.Task) -> None:
        async with self._lock:
            self._tasks[task_id] = task

    async def unregister(self, task_id: str) -> None:
        async with self._lock:
            self._tasks.pop(task_id, None)

    async def cancel(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.done():
                self._tasks.pop(task_id, None)
                return False
            task.cancel()
            return True

    async def is_running(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            return bool(task and not task.done())


security_dept_runtime_registry = SecurityDeptRuntimeRegistry()
