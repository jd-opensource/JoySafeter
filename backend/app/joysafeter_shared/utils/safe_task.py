"""
safe_create_task — drop-in replacement for asyncio.create_task with error logging.

Usage:
    from app.joysafeter_shared.utils.safe_task import safe_create_task

    safe_create_task(some_coroutine(), name="my-task")
"""

import asyncio

from loguru import logger


def safe_create_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create an asyncio task with automatic exception logging via done-callback."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_log_task_exception)
    return task


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(
            f"Background task '{task.get_name()}' failed: {exc}",
            exc_info=exc,
        )
