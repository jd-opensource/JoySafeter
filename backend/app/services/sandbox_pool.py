"""
Sandbox Connection Pool

Thread-safe pool for managing PydanticSandboxAdapter instances.
All synchronous Docker API calls (stop/cleanup) are performed OUTSIDE
the asyncio.Lock to avoid blocking the event loop.
"""

import asyncio
import time
from typing import Dict, Optional

from loguru import logger

from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter


class PoolEntry:
    """池条目"""

    def __init__(self, adapter: PydanticSandboxAdapter):
        self.adapter = adapter
        self.last_used = time.time()
        self.active_count = 0  # 当前有多少个请求正在使用此沙箱


class SandboxPool:
    """
    线程安全的沙箱实例池

    管理活跃的 PydanticSandboxAdapter 实例，避免重复创建和销毁 Docker 客户端连接。
    同时负责清理长时间未使用的连接。

    IMPORTANT: All synchronous Docker calls (adapter.stop(), adapter.cleanup())
    are performed OUTSIDE the asyncio.Lock to avoid blocking the event loop.
    """

    def __init__(self, max_size: int = 100, idle_timeout: int = 3600):
        self._pool: Dict[str, PoolEntry] = {}
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._idle_timeout = idle_timeout
        self._shutdown = False

    async def get(self, sandbox_id: str) -> Optional[PydanticSandboxAdapter]:
        """获取沙箱实例，如果要使用，请务必配合 context manager 或 try-finally 确保正确计数"""
        async with self._lock:
            if self._shutdown:
                return None

            entry = self._pool.get(sandbox_id)
            if entry:
                entry.last_used = time.time()
                entry.active_count += 1
                return entry.adapter
            return None

    async def put(self, sandbox_id: str, adapter: PydanticSandboxAdapter) -> None:
        """注册新的沙箱实例到池中"""
        old_adapter = None

        async with self._lock:
            if self._shutdown:
                # Close outside lock below
                old_adapter = adapter
            else:
                if len(self._pool) >= self._max_size:
                    evicted = self._evict_lru_entry()
                    if evicted:
                        old_adapter = evicted

                if sandbox_id in self._pool:
                    old_entry = self._pool[sandbox_id]
                    # If we already need to close an evicted adapter, chain them
                    # For simplicity, close the old entry's adapter
                    if old_adapter is None:
                        old_adapter = old_entry.adapter
                    else:
                        # Close inline (rare case: both eviction and replacement)
                        self._safe_cleanup(old_entry.adapter)

                entry = PoolEntry(adapter)
                entry.active_count = 1
                self._pool[sandbox_id] = entry
                logger.debug(f"Added sandbox {sandbox_id} to pool. Size: {len(self._pool)}")

        # Close old adapter OUTSIDE the lock
        if old_adapter is not None and old_adapter is not adapter:
            self._safe_cleanup(old_adapter)
        elif old_adapter is adapter:
            # Shutdown case: close the adapter we were asked to put
            self._safe_cleanup(adapter)

    async def release(self, sandbox_id: str) -> None:
        """释放沙箱引用计数"""
        async with self._lock:
            entry = self._pool.get(sandbox_id)
            if entry:
                entry.active_count = max(0, entry.active_count - 1)
                entry.last_used = time.time()

    async def stop(self, sandbox_id: str) -> None:
        """仅停止容器，不从池中移除，不删除容器（用于 stop/restart 语义）

        The synchronous adapter.stop() call is performed OUTSIDE the lock.
        """
        adapter = None
        async with self._lock:
            entry = self._pool.get(sandbox_id)
            if entry:
                adapter = entry.adapter

        # Stop OUTSIDE the lock to avoid blocking
        if adapter is not None:
            try:
                adapter.stop()
                logger.debug(f"Stopped sandbox {sandbox_id} (kept in pool)")
            except Exception as e:
                logger.warning(f"Error stopping adapter {sandbox_id}: {e}")

    async def remove(self, sandbox_id: str) -> None:
        """从池中移除并彻底清理沙箱（stop + remove container）"""
        adapter = None
        async with self._lock:
            if sandbox_id in self._pool:
                entry = self._pool.pop(sandbox_id)
                adapter = entry.adapter

        if adapter:
            self._safe_cleanup(adapter)
            logger.debug(f"Removed sandbox {sandbox_id} from pool")

    async def cleanup_idle(self) -> list[str]:
        """清理空闲超时的沙箱，返回被清理的沙箱ID列表"""
        now = time.time()
        to_close: list[tuple[str, PydanticSandboxAdapter]] = []

        async with self._lock:
            to_remove_ids = []
            for sid, entry in self._pool.items():
                if entry.active_count == 0 and (now - entry.last_used) > self._idle_timeout:
                    to_remove_ids.append(sid)

            for sid in to_remove_ids:
                entry = self._pool.pop(sid)
                to_close.append((sid, entry.adapter))

        # Close adapters OUTSIDE the lock to avoid blocking the pool
        for sid, adapter in to_close:
            self._safe_cleanup(adapter)

        evicted_ids = [sid for sid, _ in to_close]
        if evicted_ids:
            logger.info(f"Cleaned up {len(evicted_ids)} idle sandboxes: {evicted_ids}")
        return evicted_ids

    async def shutdown(self):
        """关闭连接池"""
        adapters = []
        async with self._lock:
            self._shutdown = True
            for entry in self._pool.values():
                adapters.append(entry.adapter)
            self._pool.clear()

        for adapter in adapters:
            self._safe_cleanup(adapter)

    def _safe_cleanup(self, adapter: PydanticSandboxAdapter) -> None:
        """Cleanup adapter. Called OUTSIDE the lock.

        This is synchronous (Docker API calls are blocking) but safe
        because it's outside the asyncio.Lock.
        """
        try:
            adapter.cleanup()
        except Exception as e:
            logger.warning(f"Error closing adapter: {e}")

    def _evict_lru_entry(self) -> Optional[PydanticSandboxAdapter]:
        """淘汰最久未使用的闲置连接 (called inside lock).

        Returns the evicted adapter (to be cleaned up outside lock), or None.
        """
        lru_sid = None
        lru_time = float("inf")

        for sid, entry in self._pool.items():
            if entry.active_count == 0 and entry.last_used < lru_time:
                lru_time = entry.last_used
                lru_sid = sid

        if lru_sid:
            entry = self._pool.pop(lru_sid)
            logger.debug(f"Evicted LRU sandbox {lru_sid}")
            return entry.adapter
        return None
