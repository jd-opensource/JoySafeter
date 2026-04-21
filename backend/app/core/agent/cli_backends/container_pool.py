"""
CLI agent container pool with TTL-based eviction and session resume.

Keeps containers alive after execution for reuse by the same agent.
Idle containers are cleaned up after `idle_timeout` seconds (default 30 min).
On app shutdown, containers are NOT destroyed — they survive restarts.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from .container_service import CLIContainerService, ContainerInfo


@dataclass
class PoolEntry:
    container: ContainerInfo
    agent_profile_id: uuid.UUID
    last_used: float
    created_at: float
    active_count: int = 0
    last_session_id: Optional[str] = None


class ContainerPool:
    """Pool of CLI agent containers keyed by agent_profile_id."""

    def __init__(
        self,
        container_service: Optional[CLIContainerService] = None,
        idle_timeout: int = 1800,
        max_size: int = 20,
    ):
        self._pool: dict[uuid.UUID, PoolEntry] = {}
        self._lock = asyncio.Lock()
        self._idle_timeout = idle_timeout
        self._max_size = max_size
        self._shutdown = False
        self.container_service = container_service or CLIContainerService()

    async def get(self, agent_profile_id: uuid.UUID) -> tuple[Optional[ContainerInfo], Optional[str]]:
        """Return (container, last_session_id) if a pooled container exists."""
        async with self._lock:
            if self._shutdown:
                return None, None
            entry = self._pool.get(agent_profile_id)
            if entry:
                entry.last_used = time.time()
                entry.active_count += 1
                return entry.container, entry.last_session_id
            return None, None

    async def put(
        self,
        agent_profile_id: uuid.UUID,
        container: ContainerInfo,
    ) -> None:
        """Register a newly created container in the pool."""
        old: Optional[PoolEntry] = None
        evicted: Optional[PoolEntry] = None
        shutdown = False

        async with self._lock:
            if self._shutdown:
                shutdown = True
            else:
                if len(self._pool) >= self._max_size and agent_profile_id not in self._pool:
                    evicted = self._evict_lru_entry()

                old = self._pool.pop(agent_profile_id, None)
                self._pool[agent_profile_id] = PoolEntry(
                    container=container,
                    agent_profile_id=agent_profile_id,
                    last_used=time.time(),
                    created_at=time.time(),
                    active_count=1,
                )
                logger.info(
                    f"Pooled container {container.container_id[:12]} for agent "
                    f"{agent_profile_id} (pool_size={len(self._pool)})"
                )

        if shutdown:
            await self._safe_remove(container.container_id)
            return
        if evicted:
            await self._safe_remove(evicted.container.container_id)
        if old:
            await self._safe_remove(old.container.container_id)

    async def release(self, agent_profile_id: uuid.UUID) -> None:
        """Decrement active count after execution finishes."""
        async with self._lock:
            entry = self._pool.get(agent_profile_id)
            if entry:
                entry.active_count = max(0, entry.active_count - 1)
                entry.last_used = time.time()

    async def release_and_destroy_if_idle(self, agent_profile_id: uuid.UUID) -> bool:
        """Decrement active count; if no other executions are using it, remove the container.

        Returns True if the container was destroyed."""
        entry: Optional[PoolEntry] = None
        async with self._lock:
            e = self._pool.get(agent_profile_id)
            if not e:
                return False
            e.active_count = max(0, e.active_count - 1)
            if e.active_count == 0:
                entry = self._pool.pop(agent_profile_id)
        if entry:
            await self._safe_remove(entry.container.container_id)
            logger.info(
                f"Destroyed idle container {entry.container.container_id[:12]} "
                f"for agent {agent_profile_id} after cancel"
            )
            return True
        return False

    async def set_session_id(self, agent_profile_id: uuid.UUID, session_id: str) -> None:
        """Store Claude session_id for next --resume."""
        async with self._lock:
            entry = self._pool.get(agent_profile_id)
            if entry and session_id:
                entry.last_session_id = session_id

    async def remove(self, agent_profile_id: uuid.UUID) -> None:
        """Force-remove a container (e.g., on execution failure)."""
        entry: Optional[PoolEntry] = None
        async with self._lock:
            entry = self._pool.pop(agent_profile_id, None)
        if entry:
            await self._safe_remove(entry.container.container_id)

    async def cleanup_idle(self) -> int:
        """Remove containers idle longer than idle_timeout. Returns count removed."""
        now = time.time()
        to_remove: list[tuple[uuid.UUID, str]] = []

        async with self._lock:
            for agent_id, entry in list(self._pool.items()):
                idle = entry.active_count == 0 and (now - entry.last_used) > self._idle_timeout
                if idle:
                    self._pool.pop(agent_id)
                    to_remove.append((agent_id, entry.container.container_id))

        for agent_id, container_id in to_remove:
            await self._safe_remove(container_id)
            logger.info(f"Evicted idle container {container_id[:12]} for agent {agent_id}")

        return len(to_remove)

    async def shutdown(self) -> None:
        """Mark pool as shut down. Containers are NOT destroyed."""
        async with self._lock:
            self._shutdown = True
            self._pool.clear()
        logger.info("Container pool shut down (containers left running for reuse after restart)")

    async def _evict_lru(self) -> None:
        """Evict the least-recently-used idle container. Called outside lock."""
        entry = self._evict_lru_entry()
        if entry:
            await self._safe_remove(entry.container.container_id)

    def _evict_lru_entry(self) -> Optional[PoolEntry]:
        """Pop the LRU idle entry from the pool. Must be called inside lock."""
        lru_id: Optional[uuid.UUID] = None
        lru_time = float("inf")
        for agent_id, entry in self._pool.items():
            if entry.active_count == 0 and entry.last_used < lru_time:
                lru_time = entry.last_used
                lru_id = agent_id
        if lru_id:
            return self._pool.pop(lru_id)
        return None

    async def _safe_remove(self, container_id: str) -> None:
        try:
            await self.container_service.remove_container(container_id, force=True)
        except Exception as exc:
            logger.warning(f"Failed to remove pooled container {container_id[:12]}: {exc}")


# Module-level singleton
container_pool = ContainerPool()
