import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class QueueBackend(ABC):
    @abstractmethod
    async def push_global(self, task_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def pop_global(self, timeout: float = 30.0) -> Optional[uuid.UUID]: ...

    @abstractmethod
    async def push_to_sandbox(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def pop_for_sandbox(
        self, sandbox_id: uuid.UUID, cancel: asyncio.Event
    ) -> Optional[uuid.UUID]: ...

    @abstractmethod
    async def pop_for_sandbox_nowait(self, sandbox_id: uuid.UUID) -> Optional[uuid.UUID]: ...

    @abstractmethod
    async def drain_and_requeue_sandbox(self, sandbox_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def drain_sandbox(self, sandbox_id: uuid.UUID) -> list[uuid.UUID]: ...


class InMemoryQueueBackend(QueueBackend):
    def __init__(self):
        self._global: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._sandbox: dict[uuid.UUID, asyncio.Queue[uuid.UUID]] = {}

    async def push_global(self, task_id: uuid.UUID) -> None:
        await self._global.put(task_id)

    async def pop_global(self, timeout: float = 30.0) -> Optional[uuid.UUID]:
        try:
            return await asyncio.wait_for(self._global.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def push_to_sandbox(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> None:
        if sandbox_id not in self._sandbox:
            self._sandbox[sandbox_id] = asyncio.Queue()
        await self._sandbox[sandbox_id].put(task_id)

    async def pop_for_sandbox(
        self, sandbox_id: uuid.UUID, cancel: asyncio.Event
    ) -> Optional[uuid.UUID]:
        if sandbox_id not in self._sandbox:
            self._sandbox[sandbox_id] = asyncio.Queue()
        q = self._sandbox[sandbox_id]
        cancel_task = asyncio.create_task(cancel.wait())
        get_task = asyncio.create_task(q.get())
        done, pending = await asyncio.wait(
            {cancel_task, get_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for p in pending:
            p.cancel()
        if get_task in done:
            return get_task.result()
        return None

    async def pop_for_sandbox_nowait(self, sandbox_id: uuid.UUID) -> Optional[uuid.UUID]:
        q = self._sandbox.get(sandbox_id)
        if q and not q.empty():
            return q.get_nowait()
        return None

    async def drain_and_requeue_sandbox(self, sandbox_id: uuid.UUID) -> None:
        q = self._sandbox.pop(sandbox_id, None)
        if not q:
            return
        while not q.empty():
            task_id = q.get_nowait()
            await self._global.put(task_id)
            logger.info("Requeued task %s from sandbox %s to global", task_id, sandbox_id)

    async def drain_sandbox(self, sandbox_id: uuid.UUID) -> list[uuid.UUID]:
        q = self._sandbox.pop(sandbox_id, None)
        if not q:
            return []
        result = []
        while not q.empty():
            result.append(q.get_nowait())
        return result


class RedisQueueBackend(QueueBackend):
    def __init__(self, redis_client, prefix: str = "conductor"):
        self._redis = redis_client
        self._prefix = prefix
        self._fallback = InMemoryQueueBackend()
        self._redis_available = True

    async def push_global(self, task_id: uuid.UUID) -> None:
        key = f"{self._prefix}:global_queue"
        try:
            await self._redis.rpush(key, str(task_id))
            self._redis_available = True
        except Exception:
            logger.warning("Redis push failed, using in-memory fallback")
            self._redis_available = False
            await self._fallback.push_global(task_id)

    async def pop_global(self, timeout: float = 30.0) -> Optional[uuid.UUID]:
        key = f"{self._prefix}:global_queue"
        try:
            result = await self._redis.blpop(key, timeout=int(timeout))
            self._redis_available = True
            if result:
                _, val = result
                return uuid.UUID(val.decode() if isinstance(val, bytes) else val)
            return None
        except Exception:
            logger.warning("Redis pop failed, using in-memory fallback")
            self._redis_available = False
            return await self._fallback.pop_global(timeout)

    async def push_to_sandbox(self, sandbox_id: uuid.UUID, task_id: uuid.UUID) -> None:
        key = f"{self._prefix}:sandbox_queue:{sandbox_id}"
        try:
            await self._redis.rpush(key, str(task_id))
        except Exception:
            await self._fallback.push_to_sandbox(sandbox_id, task_id)

    async def pop_for_sandbox(
        self, sandbox_id: uuid.UUID, cancel: asyncio.Event
    ) -> Optional[uuid.UUID]:
        key = f"{self._prefix}:sandbox_queue:{sandbox_id}"
        try:
            while not cancel.is_set():
                blpop_task = asyncio.create_task(
                    self._redis.blpop(key, timeout=2)
                )
                cancel_task = asyncio.create_task(cancel.wait())
                done, pending = await asyncio.wait(
                    {blpop_task, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    p.cancel()
                    try:
                        await p
                    except (asyncio.CancelledError, Exception):
                        pass
                if cancel_task in done:
                    return None
                if blpop_task in done:
                    result = blpop_task.result()
                    if result:
                        _, val = result
                        return uuid.UUID(val.decode() if isinstance(val, bytes) else val)
            return None
        except Exception:
            return await self._fallback.pop_for_sandbox(sandbox_id, cancel)

    async def pop_for_sandbox_nowait(self, sandbox_id: uuid.UUID) -> Optional[uuid.UUID]:
        key = f"{self._prefix}:sandbox_queue:{sandbox_id}"
        try:
            val = await self._redis.lpop(key)
            if val:
                return uuid.UUID(val.decode() if isinstance(val, bytes) else val)
            return None
        except Exception:
            return await self._fallback.pop_for_sandbox_nowait(sandbox_id)

    async def drain_and_requeue_sandbox(self, sandbox_id: uuid.UUID) -> None:
        key = f"{self._prefix}:sandbox_queue:{sandbox_id}"
        global_key = f"{self._prefix}:global_queue"
        try:
            while True:
                val = await self._redis.lpop(key)
                if not val:
                    break
                await self._redis.rpush(global_key, val)
                logger.info("Requeued task from sandbox %s to global", sandbox_id)
        except Exception:
            await self._fallback.drain_and_requeue_sandbox(sandbox_id)

    async def drain_sandbox(self, sandbox_id: uuid.UUID) -> list[uuid.UUID]:
        key = f"{self._prefix}:sandbox_queue:{sandbox_id}"
        result = []
        try:
            while True:
                val = await self._redis.lpop(key)
                if not val:
                    break
                tid = uuid.UUID(val.decode() if isinstance(val, bytes) else val)
                result.append(tid)
        except Exception:
            result.extend(await self._fallback.drain_sandbox(sandbox_id))
        return result
