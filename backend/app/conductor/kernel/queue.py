import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_PUSH_RETRIES = 3


class QueueBackend(ABC):
    """Matches the QueueBackend trait from conductor-store/src/queue.rs."""

    @abstractmethod
    async def push_to_global(self, task_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def pop_from_global(self) -> uuid.UUID: ...

    @abstractmethod
    async def push_to_sandbox(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def pop_for_sandbox(
        self, sandbox_id: uuid.UUID, cancel: asyncio.Event
    ) -> Optional[uuid.UUID]: ...

    @abstractmethod
    async def drain_and_requeue_sandbox(self, sandbox_id: uuid.UUID) -> None: ...

    @abstractmethod
    def remove_sandbox_queue(self, sandbox_id: uuid.UUID) -> None: ...

    # Extra Python method (not in Rust trait) for failover logic
    async def drain_sandbox(self, sandbox_id: uuid.UUID) -> list[uuid.UUID]:
        """Drain sandbox queue returning task IDs without re-enqueueing."""
        return []


class _TaskQueue:
    """In-memory FIFO queue with async notification, matching Rust's TaskQueue."""

    def __init__(self):
        from collections import deque
        self._inner: deque[uuid.UUID] = deque()
        self._event = asyncio.Event()

    def push(self, task_id: uuid.UUID) -> None:
        self._inner.append(task_id)
        self._event.set()

    async def pop(self) -> uuid.UUID:
        while True:
            # Check if there's an item available
            if self._inner:
                return self._inner.popleft()
            # Wait for notification
            self._event.clear()
            # Double-check after clearing (avoid race)
            if self._inner:
                return self._inner.popleft()
            await self._event.wait()

    def try_pop(self) -> Optional[uuid.UUID]:
        if self._inner:
            return self._inner.popleft()
        return None


class InMemoryRedisQueueBackend(QueueBackend):
    """In-memory primary queue with optional Redis for HA.

    Matches InMemoryRedisQueueBackend from conductor-store/src/queue.rs:
    - In-memory is the primary store
    - Redis is used for cross-instance HA when available
    - On Redis push failure: retry with exponential backoff, then fall back to local
    - On Redis pop failure: check local queue, then sleep and retry
    """

    def __init__(self, redis_coord=None):
        self._global_queue = _TaskQueue()
        self._sandbox_queues: dict[uuid.UUID, _TaskQueue] = {}
        self._redis_coord = redis_coord

    def _get_or_create_sandbox_queue(self, sandbox_id: uuid.UUID) -> _TaskQueue:
        if sandbox_id not in self._sandbox_queues:
            self._sandbox_queues[sandbox_id] = _TaskQueue()
        return self._sandbox_queues[sandbox_id]

    async def push_to_global(self, task_id: uuid.UUID) -> None:
        if self._redis_coord is not None:
            for attempt in range(REDIS_PUSH_RETRIES):
                try:
                    await self._redis_coord.push_to_global_queue(task_id)
                    return
                except Exception as e:
                    delay = 0.5 * (2 ** attempt)
                    logger.error(
                        "Redis push_to_global failed (task=%s, attempt=%d, error=%s), retrying in %.1fs",
                        task_id, attempt + 1, e, delay,
                    )
                    await asyncio.sleep(delay)
            logger.error(
                "Redis push_to_global failed after %d retries, falling back to local queue (task=%s)",
                REDIS_PUSH_RETRIES, task_id,
            )
        self._global_queue.push(task_id)

    async def pop_from_global(self) -> uuid.UUID:
        if self._redis_coord is not None:
            while True:
                try:
                    result = await self._redis_coord.pop_from_global_queue(30.0)
                    if result is not None:
                        return result
                    # Ok(None) -> timeout, continue loop
                    continue
                except Exception as e:
                    logger.warning("Redis global pop failed: %s, checking local queue", e)
                    item = self._global_queue.try_pop()
                    if item is not None:
                        return item
                    await asyncio.sleep(2)
        return await self._global_queue.pop()

    async def push_to_sandbox(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> None:
        if self._redis_coord is not None:
            for attempt in range(REDIS_PUSH_RETRIES):
                try:
                    await self._redis_coord.push_to_sandbox_queue(sandbox_id, task_id)
                    return
                except Exception as e:
                    delay = 0.5 * (2 ** attempt)
                    logger.error(
                        "Redis push_to_sandbox failed (sandbox=%s, task=%s, attempt=%d, error=%s), retrying in %.1fs",
                        sandbox_id, task_id, attempt + 1, e, delay,
                    )
                    await asyncio.sleep(delay)
            logger.error(
                "Redis push_to_sandbox failed after %d retries, falling back to local queue (sandbox=%s, task=%s)",
                REDIS_PUSH_RETRIES, sandbox_id, task_id,
            )
        self._get_or_create_sandbox_queue(sandbox_id).push(task_id)

    async def pop_for_sandbox(
        self, sandbox_id: uuid.UUID, cancel: asyncio.Event
    ) -> Optional[uuid.UUID]:
        if self._redis_coord is not None:
            while True:
                pop_coro = self._redis_coord.pop_from_sandbox_queue(sandbox_id, 30.0)
                pop_task = asyncio.create_task(pop_coro)
                cancel_task = asyncio.create_task(cancel.wait())
                done, pending = await asyncio.wait(
                    {pop_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for p in pending:
                    p.cancel()
                    try:
                        await p
                    except (asyncio.CancelledError, Exception):
                        pass
                if cancel_task in done:
                    return None
                if pop_task in done:
                    try:
                        result = pop_task.result()
                    except Exception as e:
                        logger.warning("Redis pop failed: %s, retrying in 2s (no local fallback)", e)
                        await asyncio.sleep(2)
                        continue
                    if result is not None:
                        return result
                    # Ok(None) -> timeout, refresh sandbox owner and continue
                    try:
                        await self._redis_coord.refresh_sandbox_owner(sandbox_id)
                    except Exception:
                        pass
                    continue

        queue = self._get_or_create_sandbox_queue(sandbox_id)
        pop_task = asyncio.create_task(queue.pop())
        cancel_task = asyncio.create_task(cancel.wait())
        done, pending = await asyncio.wait(
            {pop_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for p in pending:
            p.cancel()
            try:
                await p
            except (asyncio.CancelledError, Exception):
                pass
        if pop_task in done:
            return pop_task.result()
        return None

    async def drain_and_requeue_sandbox(self, sandbox_id: uuid.UUID) -> None:
        # Drain local queue first
        queue = self._sandbox_queues.pop(sandbox_id, None)
        if queue is not None:
            while True:
                task_id = queue.try_pop()
                if task_id is None:
                    break
                logger.info(
                    "Re-enqueueing task %s from disconnected sandbox %s to global queue",
                    task_id, sandbox_id,
                )
                await self.push_to_global(task_id)

        # Then drain Redis queue
        if self._redis_coord is not None:
            try:
                tasks = await self._redis_coord.drain_sandbox_queue(sandbox_id)
                for task_id in tasks:
                    logger.info(
                        "Re-enqueueing Redis task %s from disconnected sandbox %s",
                        task_id, sandbox_id,
                    )
                    await self.push_to_global(task_id)
            except Exception as e:
                logger.warning(
                    "Failed to drain Redis sandbox queue for %s: %s",
                    sandbox_id, e,
                )

    def remove_sandbox_queue(self, sandbox_id: uuid.UUID) -> None:
        self._sandbox_queues.pop(sandbox_id, None)

    async def drain_sandbox(self, sandbox_id: uuid.UUID) -> list[uuid.UUID]:
        """Extra Python method: drain sandbox queue returning task IDs.

        Drains both local and Redis queues, returning collected task IDs
        for individual failover processing.
        """
        result: list[uuid.UUID] = []

        # Drain local queue
        queue = self._sandbox_queues.pop(sandbox_id, None)
        if queue is not None:
            while True:
                task_id = queue.try_pop()
                if task_id is None:
                    break
                result.append(task_id)

        # Drain Redis queue
        if self._redis_coord is not None:
            try:
                tasks = await self._redis_coord.drain_sandbox_queue(sandbox_id)
                result.extend(tasks)
            except Exception as e:
                logger.warning(
                    "Failed to drain Redis sandbox queue for %s: %s",
                    sandbox_id, e,
                )

        return result
