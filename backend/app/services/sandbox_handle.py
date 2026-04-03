"""SandboxHandle — RAII wrapper for sandbox adapter with automatic pool release.

Ensures that every acquire of a sandbox adapter is paired with a release,
preventing active_count leaks that block idle cleanup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from app.services.sandbox_pool import SandboxPool

LOG_PREFIX = "[SandboxHandle]"


class SandboxHandle:
    """RAII wrapper — acquire on create, release on exit/release().

    Usage::

        async with await sandbox_service.ensure_sandbox_running(user_id) as handle:
            handle.adapter.write_overwrite("/workspace/uploads/f.txt", b"hello")
        # active_count decremented automatically

    Does NOT use ``__del__`` as a safety net: Python's ``__del__`` is unreliable
    in async contexts and cannot call ``await release()``. Leak detection is
    handled by periodic audit in ``SandboxPool.cleanup_idle()``.
    """

    def __init__(self, adapter: Any, sandbox_id: str, pool: SandboxPool) -> None:
        self.adapter = adapter
        self._sandbox_id = sandbox_id
        self._pool = pool
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    async def release(self) -> None:
        """Decrement active_count. Idempotent — safe to call multiple times."""
        if not self._released:
            self._released = True
            try:
                await self._pool.release(self._sandbox_id)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Failed to release {self._sandbox_id}: {e}")

    async def __aenter__(self) -> SandboxHandle:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.release()
