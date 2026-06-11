"""Thread-keyed CLI agent container pool with DB-backed persistence.

Architecture invariants (see project memory: Thread as Session):
- Pool is keyed by thread_id. One Thread → one container → one CLI session.
- DB is the source of truth (threads.container_id, threads.cli_session_id,
  threads.last_active_at). The in-memory pool is a read/write cache.
- On cache miss, the pool lazily adopts a live container recorded in the DB,
  or provisions a new one via the caller-supplied create_fn.
- LRU eviction only touches entries with active_count == 0. Running
  executions are never evicted.
- Pool size is bounded by a global max_containers.

The pool does NOT destroy containers on process shutdown. Survivors are
re-adopted after restart when their Thread is next touched.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from loguru import logger
from sqlalchemy import select, update

from app.joysafeter_shared.database import AsyncSessionLocal
from app.joysafeter_domain.models.thread import Thread
from app.joysafeter_shared.utils.datetime import utc_now

from .container_service import CLIContainerService, ContainerInfo


@dataclass
class PoolEntry:
    container: ContainerInfo
    thread_id: uuid.UUID
    last_used: float
    created_at: float
    active_count: int = 0
    cli_session_id: Optional[str] = None
    # Wall-clock timestamp of the last time we wrote ``last_active_at`` to
    # the DB. Used by the debounce in ``_touch_db_active_at`` so that the
    # hot acquire/release path doesn't issue a write per call.
    last_flushed: float = 0.0


CreateFn = Callable[[], Awaitable[ContainerInfo]]


class ContainerPool:
    """Thread-keyed cache over the persisted container mapping in threads."""

    def __init__(
        self,
        container_service: Optional[CLIContainerService] = None,
        idle_timeout: int = 1800,
        max_containers: int = 50,
        active_at_debounce: float = 60.0,
    ):
        self._cache: dict[uuid.UUID, PoolEntry] = {}
        self._lock = asyncio.Lock()
        self._idle_timeout = idle_timeout
        self._max_containers = max_containers
        self._shutdown = False
        self.container_service = container_service or CLIContainerService()
        # `last_active_at` was previously written on every acquire/release;
        # that's 2-3 DB round-trips per turn just for a timestamp. The pool
        # flushes the in-memory `last_used` at most once per this many
        # seconds, trading coarser idle-eviction granularity for a much
        # quieter write path.
        self._active_at_debounce = active_at_debounce
        # Eviction cleanup runs outside the pool lock as fire-and-forget
        # tasks. Keeping the handles lets `shutdown()` await them so we
        # don't tear down the DB engine mid-write, and surfaces exceptions
        # via a done-callback instead of silently losing them.
        self._eviction_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(
        self,
        thread_id: uuid.UUID,
        create_fn: CreateFn,
    ) -> tuple[ContainerInfo, Optional[str]]:
        """Reserve a container for a Thread.

        Returns (container, prior_cli_session_id). The returned container is
        either cached, adopted from the DB, or freshly created. The caller
        must eventually call release(thread_id).
        """
        if self._shutdown:
            raise RuntimeError("ContainerPool is shut down")

        # 1. Cache hit
        async with self._lock:
            entry = self._cache.get(thread_id)
            if entry:
                entry.active_count += 1
                entry.last_used = time.time()
                await self._touch_db_active_at(thread_id)
                return entry.container, entry.cli_session_id

        # 2. DB-backed adopt
        adopted = await self._try_adopt(thread_id)
        if adopted:
            return adopted

        # 3. Provision a new container
        async with self._lock:
            if len(self._cache) >= self._max_containers:
                await self._evict_lru_locked()

        container = await create_fn()

        # Race: two concurrent acquires for the same thread both missed
        # and both created a container. The first writer wins; the second
        # tears its container down to keep invariant 2 (one container per thread).
        async with self._lock:
            existing = self._cache.get(thread_id)
            if existing:
                logger.warning(
                    f"[pool] Race on thread {thread_id}: discarding duplicate container {container.container_id[:12]}"
                )
                await self._safe_remove(container.container_id)
                existing.active_count += 1
                existing.last_used = time.time()
                return existing.container, existing.cli_session_id

            entry = PoolEntry(
                container=container,
                thread_id=thread_id,
                last_used=time.time(),
                created_at=time.time(),
                active_count=1,
                cli_session_id=None,
                # _persist_container writes last_active_at below, so the
                # debounce clock starts now — no redundant flush on the
                # first acquire.
                last_flushed=time.time(),
            )
            self._cache[thread_id] = entry

        await self._persist_container(thread_id, container.container_id)
        logger.info(
            f"[pool] Provisioned container {container.container_id[:12]} for thread {thread_id} "
            f"(cache_size={len(self._cache)})"
        )
        return container, None

    async def release(self, thread_id: uuid.UUID) -> None:
        """Decrement active count after an execution finishes."""
        async with self._lock:
            entry = self._cache.get(thread_id)
            if not entry:
                return
            entry.active_count = max(0, entry.active_count - 1)
            entry.last_used = time.time()
        await self._touch_db_active_at(thread_id)

    async def store_session(self, thread_id: uuid.UUID, cli_session_id: str) -> None:
        """Persist the CLI session id for the next --resume."""
        async with self._lock:
            entry = self._cache.get(thread_id)
            if entry:
                entry.cli_session_id = cli_session_id or None

        async with AsyncSessionLocal() as db:
            await db.execute(update(Thread).where(Thread.id == thread_id).values(cli_session_id=cli_session_id or None))
            await db.commit()

    async def evict(self, thread_id: uuid.UUID) -> None:
        """Tear down a thread's container and clear the DB binding.

        Called when a Thread is archived or its container needs to be reset
        (e.g., CLI session recovery falls back to rebuild).
        """
        entry: Optional[PoolEntry]
        async with self._lock:
            entry = self._cache.pop(thread_id, None)

        if entry:
            await self._safe_remove(entry.container.container_id)

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Thread).where(Thread.id == thread_id).values(container_id=None, cli_session_id=None)
            )
            await db.commit()

        logger.info(f"[pool] Evicted thread {thread_id}")

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def cleanup_idle(self) -> int:
        """Remove containers idle longer than idle_timeout. Returns count."""
        now = time.time()
        to_remove: list[tuple[uuid.UUID, str]] = []

        async with self._lock:
            for tid, entry in list(self._cache.items()):
                idle = entry.active_count == 0 and (now - entry.last_used) > self._idle_timeout
                if idle:
                    self._cache.pop(tid)
                    to_remove.append((tid, entry.container.container_id))

        for tid, cid in to_remove:
            await self._safe_remove(cid)
            async with AsyncSessionLocal() as db:
                await db.execute(update(Thread).where(Thread.id == tid).values(container_id=None, cli_session_id=None))
                await db.commit()
            logger.info(f"[pool] Evicted idle container {cid[:12]} for thread {tid}")

        return len(to_remove)

    async def shutdown(self) -> None:
        """Mark the pool as shut down. Containers are NOT destroyed so they
        can be adopted again after restart."""
        async with self._lock:
            self._shutdown = True
            self._cache.clear()
        # Wait for any in-flight eviction cleanups so we don't race the
        # DB engine teardown. None of them block on the pool lock, so this
        # completes promptly.
        if self._eviction_tasks:
            pending = list(self._eviction_tasks)
            await asyncio.gather(*pending, return_exceptions=True)
        logger.info("[pool] Shut down (containers left running for reuse after restart)")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _try_adopt(self, thread_id: uuid.UUID) -> Optional[tuple[ContainerInfo, Optional[str]]]:
        """Attempt to adopt a container recorded in the threads row.

        Returns None if no DB record exists or the container is no longer
        running; the caller then falls through to provisioning a new one.
        On adopt failure, the stale DB binding is cleared.
        """
        async with AsyncSessionLocal() as db:
            thread = (await db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
            if thread is None or not thread.container_id:
                return None
            container_id = thread.container_id
            cli_session_id = thread.cli_session_id

        # Verify the container is actually alive
        try:
            status = (await self.container_service.inspect_container(container_id)).strip().lower()
        except Exception as exc:
            logger.warning(f"[pool] Inspect failed for {container_id[:12]} on thread {thread_id}: {exc}")
            status = "missing"

        if "running" not in status:
            logger.info(
                f"[pool] DB-recorded container {container_id[:12]} for thread {thread_id} "
                f"is not running (status={status}); clearing binding"
            )
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Thread).where(Thread.id == thread_id).values(container_id=None, cli_session_id=None)
                )
                await db.commit()
            return None

        container = ContainerInfo(
            container_id=container_id,
            name=container_id[:12],
            status="running",
            working_dir="/workspace",
        )

        async with self._lock:
            existing = self._cache.get(thread_id)
            if existing:
                existing.active_count += 1
                existing.last_used = time.time()
                return existing.container, existing.cli_session_id

            if len(self._cache) >= self._max_containers:
                await self._evict_lru_locked()

            entry = PoolEntry(
                container=container,
                thread_id=thread_id,
                last_used=time.time(),
                created_at=time.time(),
                active_count=1,
                cli_session_id=cli_session_id,
                # last_flushed stays 0 so the touch below always flushes —
                # the DB last_active_at may be stale from long ago, and we
                # want a fresh timestamp the first time we see this thread.
            )
            self._cache[thread_id] = entry

        await self._touch_db_active_at(thread_id)
        logger.info(
            f"[pool] Adopted container {container_id[:12]} for thread {thread_id} "
            f"(cli_session={'yes' if cli_session_id else 'no'})"
        )
        return container, cli_session_id

    async def _evict_lru_locked(self) -> None:
        """Evict the least-recently-used idle entry. Caller must hold the lock."""
        lru_id: Optional[uuid.UUID] = None
        lru_time = float("inf")
        for tid, entry in self._cache.items():
            if entry.active_count == 0 and entry.last_used < lru_time:
                lru_time = entry.last_used
                lru_id = tid

        if lru_id is None:
            # Nothing idle to evict; the cache is fully active. The new
            # acquire will push us past the soft cap. Log and continue —
            # active executions must not be interrupted.
            logger.warning(
                f"[pool] max_containers={self._max_containers} reached with no idle entry; "
                "exceeding limit until an active run completes"
            )
            return

        entry = self._cache.pop(lru_id)
        # Release the lock briefly to perform IO: we drop the container and
        # clear the DB binding outside the critical section.
        loop_tid = lru_id
        loop_cid = entry.container.container_id
        # Perform best-effort cleanup; don't propagate errors — eviction is
        # advisory, the DB binding gets reset on next adopt attempt anyway.
        self._spawn_cleanup(loop_tid, loop_cid)

    def _spawn_cleanup(self, thread_id: uuid.UUID, container_id: str) -> None:
        """Fire an eviction cleanup and keep a handle for shutdown + errors."""
        task = asyncio.create_task(
            self._evict_cleanup(thread_id, container_id),
            name=f"pool-evict-{thread_id}",
        )
        self._eviction_tasks.add(task)

        def _on_done(t: asyncio.Task[None]) -> None:
            self._eviction_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.warning(f"[pool] eviction cleanup raised: {exc!r}")

        task.add_done_callback(_on_done)

    async def _evict_cleanup(self, thread_id: uuid.UUID, container_id: str) -> None:
        await self._safe_remove(container_id)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Thread).where(Thread.id == thread_id).values(container_id=None, cli_session_id=None)
            )
            await db.commit()
        logger.info(f"[pool] LRU-evicted container {container_id[:12]} for thread {thread_id}")

    async def _persist_container(self, thread_id: uuid.UUID, container_id: str) -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Thread).where(Thread.id == thread_id).values(container_id=container_id, last_active_at=utc_now())
            )
            await db.commit()

    async def _touch_db_active_at(self, thread_id: uuid.UUID) -> None:
        """Flush ``last_active_at`` to DB at most once per debounce window.

        Called on every acquire-hit / release / adopt — without the
        debounce this would be 2-3 writes per turn just for a timestamp.
        The in-memory ``last_used`` on ``PoolEntry`` is always current; the
        DB column is allowed to lag by up to ``active_at_debounce`` seconds,
        which is well within the idle-eviction granularity.
        """
        now = time.time()
        async with self._lock:
            entry = self._cache.get(thread_id)
            if entry is None:
                # Not in cache: we're mid-race or the entry was evicted.
                # Fall through and just flush — cheap and correct.
                should_flush = True
            else:
                should_flush = (now - entry.last_flushed) >= self._active_at_debounce
                if should_flush:
                    entry.last_flushed = now
        if not should_flush:
            return
        async with AsyncSessionLocal() as db:
            await db.execute(update(Thread).where(Thread.id == thread_id).values(last_active_at=utc_now()))
            await db.commit()

    async def _safe_remove(self, container_id: str) -> None:
        try:
            await self.container_service.remove_container(container_id, force=True)
        except Exception as exc:
            logger.warning(f"[pool] Failed to remove container {container_id[:12]}: {exc}")


# Module-level singleton
container_pool = ContainerPool()
