import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional

from redis.exceptions import ConnectionError as RedisConnectionError

from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload

if TYPE_CHECKING:
    from app.joysafeter_orchestrator.kernel.redis_coordinator import RedisCoordinator

logger = logging.getLogger(__name__)

REDIS_PUSH_RETRIES = 3


class QueueBackend(ABC):
    """Matches the QueueBackend trait from joysafeter-store/src/queue.rs."""

    @abstractmethod
    async def push_to_global(self, task_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def pop_from_global(self) -> uuid.UUID: ...

    @abstractmethod
    async def push_to_sandbox(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def pop_for_sandbox(self, sandbox_id: uuid.UUID, cancel: asyncio.Event) -> Optional[uuid.UUID]: ...

    async def wait_for_sandbox_wakeup(
        self,
        sandbox_id: uuid.UUID,
        cancel: asyncio.Event,
        timeout_secs: float = 1.0,
    ) -> None: ...

    @abstractmethod
    async def drain_and_requeue_sandbox(self, sandbox_id: uuid.UUID) -> None: ...

    @abstractmethod
    def remove_sandbox_queue(self, sandbox_id: uuid.UUID) -> None: ...

    # Extra Python method (not in Rust trait) for failover logic
    async def drain_sandbox(self, sandbox_id: uuid.UUID) -> list[uuid.UUID]:
        """Drain sandbox wakeups returning no durable task IDs."""
        return []

    async def has_pending(self, sandbox_id: uuid.UUID) -> bool:
        """Check if a sandbox has pending wakeup work — matches Rust."""
        return False


class _TaskQueue:
    """In-memory FIFO queue with async notification, matching Rust's TaskQueue."""

    def __init__(self):
        from collections import deque

        self._inner: deque[uuid.UUID] = deque()
        self._event = asyncio.Event()

    def push(self, task_id: uuid.UUID) -> None:
        self._inner.append(task_id)
        self._event.set()

    def signal(self) -> None:
        self._inner.clear()
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

    async def wait(self, timeout_secs: float) -> None:
        if self._inner:
            self._inner.popleft()
            return
        self._event.clear()
        if self._inner:
            self._inner.popleft()
            return
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout_secs)
        except asyncio.TimeoutError:
            return
        self.try_pop()


class InMemoryRedisQueueBackend(QueueBackend):
    """In-memory primary queue with optional Redis for HA.

    Matches InMemoryRedisQueueBackend from joysafeter-store/src/queue.rs:
    - In-memory is the primary store
    - Redis is used for cross-instance HA when available
    - On Redis push failure: retry with exponential backoff, then fall back to local
    - On Redis pop failure: check local queue, then sleep and retry
    """

    def __init__(self, redis_coord: "Optional[RedisCoordinator]" = None):
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
                    delay = 0.5 * (2**attempt)
                    logger.error(
                        "Redis push_to_global failed; retrying",
                        extra={
                            "error": async_boundary_error_payload(
                                code="QUEUE_GLOBAL_REDIS_PUSH_RETRYING",
                                message="Redis global queue push failed; retrying",
                                boundary="queue",
                                operation="push_to_global",
                                data={
                                    "task_id": str(task_id),
                                    "attempt": attempt + 1,
                                    "max_attempts": REDIS_PUSH_RETRIES,
                                    "retry_delay_sec": delay,
                                },
                                detail=e.__class__.__name__,
                            )
                        },
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
            logger.error(
                "Redis push_to_global failed after %d retries, falling back to local queue (task=%s)",
                REDIS_PUSH_RETRIES,
                task_id,
                extra={
                    "error": async_boundary_error_payload(
                        code="QUEUE_GLOBAL_REDIS_PUSH_FAILED",
                        message="Redis global queue push failed after retries; falling back to local queue",
                        boundary="queue",
                        operation="push_to_global",
                        data={"task_id": str(task_id), "retries": REDIS_PUSH_RETRIES},
                        detail="RedisPushFailed",
                    )
                },
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
                    logger.warning(
                        "Redis global pop failed; checking local queue",
                        extra={
                            "error": async_boundary_error_payload(
                                code="QUEUE_GLOBAL_REDIS_POP_FAILED",
                                message="Redis global queue pop failed; checking local queue",
                                boundary="queue",
                                operation="pop_from_global",
                                detail=e.__class__.__name__,
                            )
                        },
                        exc_info=True,
                    )
                    item = self._global_queue.try_pop()
                    if item is not None:
                        return item
                    await asyncio.sleep(2)
        return await self._global_queue.pop()

    async def push_to_sandbox(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> None:
        self._get_or_create_sandbox_queue(sandbox_id).signal()
        if self._redis_coord is not None:
            for attempt in range(REDIS_PUSH_RETRIES):
                try:
                    await self._redis_coord.push_to_sandbox_queue(sandbox_id, task_id)
                    return
                except Exception as e:
                    delay = 0.5 * (2**attempt)
                    logger.error(
                        "Redis push_to_sandbox failed; retrying",
                        extra={
                            "error": async_boundary_error_payload(
                                code="QUEUE_SANDBOX_REDIS_PUSH_RETRYING",
                                message="Redis sandbox queue push failed; retrying",
                                boundary="queue",
                                operation="push_to_sandbox",
                                data={
                                    "sandbox_id": str(sandbox_id),
                                    "task_id": str(task_id),
                                    "attempt": attempt + 1,
                                    "max_attempts": REDIS_PUSH_RETRIES,
                                    "retry_delay_sec": delay,
                                },
                                detail=e.__class__.__name__,
                            )
                        },
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
            logger.error(
                "Redis push_to_sandbox failed after %d retries, falling back to local queue (sandbox=%s, task=%s)",
                REDIS_PUSH_RETRIES,
                sandbox_id,
                task_id,
                extra={
                    "error": async_boundary_error_payload(
                        code="QUEUE_SANDBOX_REDIS_PUSH_FAILED",
                        message="Redis sandbox queue push failed after retries; falling back to local queue",
                        boundary="queue",
                        operation="push_to_sandbox",
                        data={
                            "sandbox_id": str(sandbox_id),
                            "task_id": str(task_id),
                            "retries": REDIS_PUSH_RETRIES,
                        },
                        detail="RedisPushFailed",
                    )
                },
            )

    async def pop_for_sandbox(self, sandbox_id: uuid.UUID, cancel: asyncio.Event) -> Optional[uuid.UUID]:
        if self._redis_coord is not None:
            while True:
                pop_coro = self._redis_coord.pop_from_sandbox_queue(sandbox_id, 30.0)
                pop_task = asyncio.create_task(pop_coro)
                cancel_task = asyncio.create_task(cancel.wait())
                done, pending = await asyncio.wait({pop_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
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
                        logger.warning(
                            "Redis sandbox pop failed; retrying without local fallback",
                            extra={
                                "error": async_boundary_error_payload(
                                    code="QUEUE_SANDBOX_REDIS_POP_FAILED",
                                    message="Redis sandbox queue pop failed; retrying without local fallback",
                                    boundary="queue",
                                    operation="pop_for_sandbox",
                                    data={"sandbox_id": str(sandbox_id)},
                                    detail=e.__class__.__name__,
                                )
                            },
                            exc_info=True,
                        )
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
        done, pending = await asyncio.wait({pop_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
            try:
                await p
            except (asyncio.CancelledError, Exception):
                pass
        if pop_task in done:
            return pop_task.result()
        return None

    async def wait_for_sandbox_wakeup(
        self,
        sandbox_id: uuid.UUID,
        cancel: asyncio.Event,
        timeout_secs: float = 1.0,
    ) -> None:
        queue = self._get_or_create_sandbox_queue(sandbox_id)
        wait_tasks: set[asyncio.Task[Any]] = {
            asyncio.create_task(queue.wait(timeout_secs)),
            asyncio.create_task(cancel.wait()),
        }
        if self._redis_coord is not None:
            wait_timeout = max(1, int(timeout_secs))
            wait_tasks.add(asyncio.create_task(self._redis_coord.pop_from_sandbox_queue(sandbox_id, wait_timeout)))

        done, pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
            try:
                await p
            except (asyncio.CancelledError, RedisConnectionError):
                pass
            except Exception as e:
                logger.debug("Sandbox wakeup pending wait ended during cleanup: %s", e)
        for task in done:
            try:
                task.result()
            except RedisConnectionError as e:
                logger.debug("Sandbox wakeup Redis wait interrupted: %s", e)
            except Exception as e:
                logger.warning(
                    "Sandbox wakeup wait failed",
                    extra={
                        "error": async_boundary_error_payload(
                            code="QUEUE_SANDBOX_WAKEUP_WAIT_FAILED",
                            message="Sandbox wakeup wait failed",
                            boundary="task_queue",
                            operation="wait_for_sandbox_wakeup",
                            data={"sandbox_id": str(sandbox_id)},
                            detail=e.__class__.__name__,
                        )
                    },
                    exc_info=True,
                )

    async def drain_and_requeue_sandbox(self, sandbox_id: uuid.UUID) -> None:
        await self.drain_sandbox(sandbox_id)

    def remove_sandbox_queue(self, sandbox_id: uuid.UUID) -> None:
        self._sandbox_queues.pop(sandbox_id, None)

    async def drain_sandbox(self, sandbox_id: uuid.UUID) -> list[uuid.UUID]:
        """Drain sandbox wakeup tokens.

        Sandbox queues are not a durable task source in DB-driven scheduling.
        The returned list is intentionally empty; task recovery must query DB.
        """
        queue = self._sandbox_queues.pop(sandbox_id, None)
        if queue is not None:
            while True:
                if queue.try_pop() is None:
                    break

        if self._redis_coord is not None:
            try:
                await self._redis_coord.drain_sandbox_queue(sandbox_id)
            except Exception as e:
                logger.warning(
                    "Failed to drain Redis sandbox queue",
                    extra={
                        "error": async_boundary_error_payload(
                            code="QUEUE_SANDBOX_REDIS_DRAIN_FAILED",
                            message="Failed to drain Redis sandbox queue",
                            boundary="queue",
                            operation="drain_sandbox_queue",
                            data={"sandbox_id": str(sandbox_id)},
                            detail=e.__class__.__name__,
                        )
                    },
                    exc_info=True,
                )

        return []

    async def has_pending(self, sandbox_id: uuid.UUID) -> bool:
        """Check if a sandbox has pending wakeup work — matches Rust."""
        # Check local queue
        queue = self._sandbox_queues.get(sandbox_id)
        if queue is not None and queue._inner:
            return True
        # Check Redis wakeup key
        if self._redis_coord is not None:
            try:
                key = f"joysafeter:sandbox_wakeup:{sandbox_id}"
                result = await self._redis_coord._redis.get(key)
                return result is not None
            except Exception:
                pass
        return False
