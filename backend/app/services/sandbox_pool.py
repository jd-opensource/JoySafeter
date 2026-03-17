"""
Sandbox Connection Pool
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
        async with self._lock:
            if self._shutdown:
                await self._close_adapter(adapter)
                return

            if len(self._pool) >= self._max_size:
                # 简单的淘汰策略：移除最久未使用的
                await self._evict_lru()

            if sandbox_id in self._pool:
                # 如果已存在，先关闭旧的
                old_entry = self._pool[sandbox_id]
                await self._close_adapter(old_entry.adapter)

            entry = PoolEntry(adapter)
            # 初始引用计数为 1 (调用者正在使用)
            entry.active_count = 1
            self._pool[sandbox_id] = entry
            logger.debug(f"Added sandbox {sandbox_id} to pool. Size: {len(self._pool)}")

    async def release(self, sandbox_id: str) -> None:
        """释放沙箱引用计数"""
        async with self._lock:
            entry = self._pool.get(sandbox_id)
            if entry:
                entry.active_count = max(0, entry.active_count - 1)
                entry.last_used = time.time()

    async def stop(self, sandbox_id: str) -> None:
        """仅停止容器，不从池中移除，不删除容器（用于 stop/restart 语义）"""
        async with self._lock:
            entry = self._pool.get(sandbox_id)
            if entry:
                try:
                    if hasattr(entry.adapter, "stop"):
                        entry.adapter.stop()
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
            await self._close_adapter(adapter)
            logger.debug(f"Removed sandbox {sandbox_id} from pool")

    async def cleanup_idle(self) -> list[str]:
        """清理空闲超时的沙箱，返回被清理的沙箱ID列表"""
        now = time.time()
        to_remove = []

        async with self._lock:
            # First pass: identify
            for sid, entry in self._pool.items():
                # Check if idle (active_count == 0) and timed out
                if entry.active_count == 0 and (now - entry.last_used) > self._idle_timeout:
                    to_remove.append(sid)

            # Second pass: remove
            for sid in to_remove:
                entry = self._pool.pop(sid)
                # Cleanup in background or await here?
                # Awaiting here might block the lock if cleanup is slow.
                # ideally we should move cleanup outside the lock, but we need the entry.
                # For safety/simplicity in this iteration, we await inside.
                await self._close_adapter(entry.adapter)

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} idle sandboxes: {to_remove}")
        return to_remove

    async def shutdown(self):
        """关闭连接池"""
        self._shutdown = True
        adapters = []
        async with self._lock:
            for entry in self._pool.values():
                adapters.append(entry.adapter)
            self._pool.clear()

        for adapter in adapters:
            await self._close_adapter(adapter)

    async def _close_adapter(self, adapter: PydanticSandboxAdapter):
        """从池中移除时彻底清理：停止并删除容器（cleanup）"""
        try:
            if hasattr(adapter, "cleanup"):
                adapter.cleanup()
        except Exception as e:
            logger.warning(f"Error closing adapter: {e}")

    async def _evict_lru(self):
        """淘汰最久未使用的闲置连接"""
        lru_sid = None
        lru_time = float("inf")

        for sid, entry in self._pool.items():
            if entry.active_count == 0 and entry.last_used < lru_time:
                lru_time = entry.last_used
                lru_sid = sid

        if lru_sid:
            entry = self._pool.pop(lru_sid)
            await self._close_adapter(entry.adapter)
            logger.debug(f"Evicted LRU sandbox {lru_sid}")
