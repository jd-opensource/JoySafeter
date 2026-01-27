"""
任务管理器

用于跟踪和管理正在运行的对话任务，支持停止操作
"""

import asyncio

from loguru import logger


class TaskManager:
    """任务管理器，用于跟踪和管理正在运行的对话任务"""

    def __init__(self):
        """初始化任务管理器"""
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._stop_flags: set[str] = set()
        self._lock = asyncio.Lock()

    async def register_task(self, thread_id: str, task: asyncio.Task) -> None:
        """
        注册一个正在运行的任务

        Args:
            thread_id: 会话线程ID
            task: 异步任务对象
        """
        async with self._lock:
            self._running_tasks[thread_id] = task
            # 清除之前的停止标志（如果有）
            self._stop_flags.discard(thread_id)
            logger.debug(f"Registered task for thread_id: {thread_id}")

    async def unregister_task(self, thread_id: str) -> None:
        """
        注销一个任务

        Args:
            thread_id: 会话线程ID
        """
        async with self._lock:
            self._running_tasks.pop(thread_id, None)
            self._stop_flags.discard(thread_id)
            logger.debug(f"Unregistered task for thread_id: {thread_id}")

    async def stop_task(self, thread_id: str) -> bool:
        """
        停止指定线程的任务

        Args:
            thread_id: 会话线程ID

        Returns:
            bool: 是否成功停止（True表示任务存在且已标记停止，False表示任务不存在）
        """
        async with self._lock:
            if thread_id in self._running_tasks:
                self._stop_flags.add(thread_id)
                logger.info(f"Stop flag set for thread_id: {thread_id}")
                return True
            return False

    async def is_stopped(self, thread_id: str) -> bool:
        """
        检查指定线程的任务是否已被标记为停止

        Args:
            thread_id: 会话线程ID

        Returns:
            bool: 是否已停止
        """
        async with self._lock:
            return thread_id in self._stop_flags

    async def cancel_task(self, thread_id: str) -> bool:
        """
        取消指定线程的任务（强制取消）

        Args:
            thread_id: 会话线程ID

        Returns:
            bool: 是否成功取消
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
        获取所有正在运行的线程ID

        Returns:
            Set[str]: 正在运行的线程ID集合
        """
        async with self._lock:
            return set(self._running_tasks.keys())


# 全局任务管理器实例
task_manager = TaskManager()
