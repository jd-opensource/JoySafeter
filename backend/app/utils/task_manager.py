"""
Task Manager

Track and manage running conversation tasks with stop support.
"""

import asyncio

from loguru import logger


class TaskManager:
    """Track and manage running conversation tasks."""

    def __init__(self):
        """Initialize the task manager."""
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._stop_flags: set[str] = set()
        self._lock = asyncio.Lock()

    async def register_task(self, thread_id: str, task: asyncio.Task) -> None:
        """
        Register a running task.

        Args:
            thread_id: conversation thread ID
            task: async task object
        """
        async with self._lock:
            self._running_tasks[thread_id] = task
            # clear any previous stop flag
            self._stop_flags.discard(thread_id)
            logger.debug(f"Registered task for thread_id: {thread_id}")

    async def unregister_task(self, thread_id: str) -> None:
        """
        Unregister a task.

        Args:
            thread_id: conversation thread ID
        """
        async with self._lock:
            self._running_tasks.pop(thread_id, None)
            self._stop_flags.discard(thread_id)
            logger.debug(f"Unregistered task for thread_id: {thread_id}")

    async def stop_task(self, thread_id: str) -> bool:
        """
        Stop the task for a given thread.

        Args:
            thread_id: conversation thread ID

        Returns:
            bool: True if the task exists and was flagged for stop, False if not found
        """
        async with self._lock:
            if thread_id in self._running_tasks:
                self._stop_flags.add(thread_id)
                logger.info(f"Stop flag set for thread_id: {thread_id}")
                return True
            return False

    async def is_stopped(self, thread_id: str) -> bool:
        """
        Check whether the task for a given thread has been flagged for stop.

        Args:
            thread_id: conversation thread ID

        Returns:
            bool: whether the task is stopped
        """
        async with self._lock:
            return thread_id in self._stop_flags

    async def cancel_task(self, thread_id: str) -> bool:
        """
        Force-cancel the task for a given thread.

        Args:
            thread_id: conversation thread ID

        Returns:
            bool: whether the task was successfully cancelled
        """
        async with self._lock:
            task = self._running_tasks.get(thread_id)
            if task and not task.done():
                task.cancel()
                self._running_tasks.pop(thread_id, None)
                self._stop_flags.discard(thread_id)
                logger.info(f"Cancelled task for thread_id: {thread_id}")
                return True
            return False

    async def get_running_threads(self) -> set[str]:
        """
        Return all currently running thread IDs.

        Returns:
            Set[str]: set of running thread IDs
        """
        async with self._lock:
            return set(self._running_tasks.keys())


# global task manager instance
task_manager = TaskManager()
