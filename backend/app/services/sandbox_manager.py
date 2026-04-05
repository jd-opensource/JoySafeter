"""
Sandbox Manager Service
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.backends.constants import (
    DEFAULT_USER_SANDBOX_AUTO_REMOVE,
    DEFAULT_USER_SANDBOX_CPU_LIMIT,
    DEFAULT_USER_SANDBOX_IDLE_TIMEOUT,
    DEFAULT_USER_SANDBOX_IMAGE,
    DEFAULT_USER_SANDBOX_MEMORY_LIMIT,
)
from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter
from app.models.user_sandbox import UserSandbox
from app.services.sandbox_pool import SandboxPool

# Global Sandbox Pool
_sandbox_pool = SandboxPool()

# Per-user locks to prevent concurrent container creation for the same user.
# Key: user_id -> asyncio.Lock
_user_locks: Dict[str, asyncio.Lock] = {}
_user_locks_guard = asyncio.Lock()  # Protects _user_locks dict itself


async def _get_user_lock(user_id: str) -> asyncio.Lock:
    """Get or create a per-user asyncio.Lock."""
    async with _user_locks_guard:
        if user_id not in _user_locks:
            _user_locks[user_id] = asyncio.Lock()
        return _user_locks[user_id]


class SandboxManagerService:
    """
    User sandbox management service — production-grade implementation.

    Core responsibilities:
    1. Manage UserSandbox database records
    2. Coordinate Docker container lifecycle (via PydanticSandboxAdapter)
    3. Maintain the sandbox connection pool
    4. Monitor sandbox status

    Concurrency safety:
    - ensure_sandbox_running uses a per-user lock to prevent concurrent container creation for the same user
    - SandboxPool uses asyncio.Lock to protect internal state
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_sandbox_record(self, user_id: str) -> Optional[UserSandbox]:
        """Get the user's sandbox record."""
        result = await self.db.execute(select(UserSandbox).where(UserSandbox.user_id == user_id))
        return result.scalar_one_or_none()

    async def create_sandbox_record(self, user_id: str) -> UserSandbox:
        """Create a new sandbox record (do not start a container)."""
        existing = await self.get_user_sandbox_record(user_id)
        if existing:
            return existing

        new_sandbox = self._build_sandbox_record(user_id)
        self.db.add(new_sandbox)
        await self.db.commit()
        await self.db.refresh(new_sandbox)
        return new_sandbox

    @staticmethod
    def _build_sandbox_record(user_id: str) -> UserSandbox:
        return UserSandbox(
            id=str(uuid.uuid4()),
            user_id=user_id,
            status="pending",
            image=DEFAULT_USER_SANDBOX_IMAGE,
            idle_timeout=DEFAULT_USER_SANDBOX_IDLE_TIMEOUT,
            cpu_limit=DEFAULT_USER_SANDBOX_CPU_LIMIT,
            memory_limit=DEFAULT_USER_SANDBOX_MEMORY_LIMIT,
        )

    async def ensure_sandbox_running(self, user_id: str) -> Any:
        """
        Ensure the user's sandbox is running and return a SandboxHandle.
        Create if it does not exist, start if stopped.

        Use a per-user lock to prevent concurrent container creation.
        The returned SandboxHandle already has active_count += 1 in the pool;
        the caller must release via handle.release() or async with handle.
        """
        from app.services import sandbox_handle

        user_lock = await _get_user_lock(user_id)
        async with user_lock:
            adapter = await self._ensure_sandbox_running_locked(user_id)
            record = await self.get_user_sandbox_record(user_id)
            sandbox_id = str(record.id) if record else user_id
            return sandbox_handle.SandboxHandle(adapter, sandbox_id, _sandbox_pool)

    async def warm_up_sandbox(self, user_id: str) -> None:
        """
        Ensure the user's sandbox is running, but do not increment active_count.
        Used for background warm-up after login; no sandbox content operations needed.
        """
        user_lock = await _get_user_lock(user_id)
        async with user_lock:
            await self._ensure_sandbox_running_locked(user_id)
            # immediately release pool reference (_ensure_sandbox_running_locked internally did pool.get/put +1)
            record = await self.get_user_sandbox_record(user_id)
            if record:
                await _sandbox_pool.release(str(record.id))

    async def _get_or_create_sandbox_record_for_update(self, user_id: str) -> UserSandbox:
        """Get or create a sandbox record, using SELECT FOR UPDATE to prevent cross-process races.

        Hold the row lock until the caller commits or rolls back, ensuring the same user
        is not concurrently assigned multiple containers by different workers.
        """
        result = await self.db.execute(select(UserSandbox).where(UserSandbox.user_id == user_id).with_for_update())
        record = result.scalar_one_or_none()
        if record:
            return record

        new_sandbox = self._build_sandbox_record(user_id)
        self.db.add(new_sandbox)
        await self.db.flush()
        return new_sandbox

    async def _ensure_sandbox_running_locked(self, user_id: str) -> PydanticSandboxAdapter:
        """Internal implementation of ensure_sandbox_running (per-user lock already held)."""
        sandbox_record = await self._get_or_create_sandbox_record_for_update(user_id)

        adapter = await _sandbox_pool.get(sandbox_record.id)
        if adapter:
            if adapter.is_started():
                await self._update_last_active(sandbox_record.id)
                return adapter
            # stopped but not removed: try restarting the same container
            try:
                adapter.start()
                container_id = adapter.get_container_id()
                await self._update_status(
                    sandbox_record.id,
                    "running",
                    container_id=container_id,
                    error_message=None,
                )
                return adapter
            except Exception as e:
                logger.warning(f"Failed to start existing sandbox {sandbox_record.id}, will recreate: {e}")
                await _sandbox_pool.release(sandbox_record.id)
                await _sandbox_pool.remove(sandbox_record.id)

        if sandbox_record.container_id:
            try:
                adapter = self._reconnect_container(sandbox_record)
                if adapter:
                    await _sandbox_pool.put(sandbox_record.id, adapter)
                    container_id = adapter.get_container_id()
                    await self._update_status(
                        sandbox_record.id,
                        "running",
                        container_id=container_id,
                        error_message=None,
                    )
                    logger.info(f"Reconnected existing container {sandbox_record.container_id} for user {user_id}")
                    return adapter
                self._force_remove_container(sandbox_record.container_id)
            except Exception as e:
                logger.warning(f"Failed to reconnect container {sandbox_record.container_id} for user {user_id}: {e}")
                self._force_remove_container(sandbox_record.container_id)

        # flush_only=True keeps the row lock until container_id is written, preventing a second worker from reading container_id=None and creating a duplicate container
        try:
            await self._update_status(sandbox_record.id, "creating", flush_only=True)

            import os

            from app.utils.sandbox_paths import get_user_sandbox_host_dir

            host_sandbox_dir = str(get_user_sandbox_host_dir(user_id))
            os.makedirs(host_sandbox_dir, exist_ok=True)
            volumes = {host_sandbox_dir: "/workspace"}

            logger.info(f"Starting sandbox for user {user_id} (id={sandbox_record.id})")
            adapter = PydanticSandboxAdapter(
                image=sandbox_record.image,
                session_id=sandbox_record.id,
                idle_timeout=sandbox_record.idle_timeout,
                volumes=volumes,
                auto_remove=DEFAULT_USER_SANDBOX_AUTO_REMOVE,
            )

            await _sandbox_pool.put(sandbox_record.id, adapter)

            container_id = adapter.get_container_id()
            await self._update_status(
                sandbox_record.id,
                "running",
                container_id=container_id,
                error_message=None,
            )

            return adapter

        except Exception as e:
            logger.error(f"Failed to start sandbox for user {user_id}: {e}")
            await self._update_status(sandbox_record.id, "failed", error_message=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Failed to start sandbox: {str(e)}"
            )

    @staticmethod
    def _force_remove_container(container_id: str) -> None:
        """Force-remove a Docker container, ignoring all errors (for cleaning up orphan containers)."""
        try:
            import docker

            docker.from_env().containers.get(container_id).remove(force=True)
            logger.info(f"Force-removed stale container {container_id[:12]}")
        except Exception as e:
            logger.warning(f"Could not force-remove container {container_id[:12]}: {e}")

    @staticmethod
    def _reconnect_container(sandbox_record: UserSandbox) -> Optional[PydanticSandboxAdapter]:
        """Try to reconnect to an existing Docker container (app restart recovery scenario).

        Returns:
            PydanticSandboxAdapter on success, None on failure
        """
        try:
            import docker

            client = docker.from_env()
            container = client.containers.get(sandbox_record.container_id)
            container_status = container.status  # "running", "exited", "created", etc.

            if container_status in ("exited", "created"):
                container.start()
            elif container_status != "running":
                logger.warning(f"Container {sandbox_record.container_id} in unexpected state: {container_status}")
                return None

            # Create adapter that wraps the existing container
            adapter = PydanticSandboxAdapter.from_existing_container(
                container=container,
                session_id=sandbox_record.id,
                image=sandbox_record.image,
                idle_timeout=sandbox_record.idle_timeout,
            )
            return adapter
        except Exception as e:
            logger.warning(f"Cannot reconnect container {sandbox_record.container_id}: {e}")
            return None

    async def _update_status(
        self,
        sandbox_id: str,
        status: str,
        container_id: Optional[str] = None,
        error_message: Optional[str] = None,
        flush_only: bool = False,
    ):
        """Update sandbox status.

        flush_only=True: only flush (keep transaction and row lock), caller is responsible for commit.
        flush_only=False (default): flush + commit, commit immediately.
        """
        values: Dict[str, Any] = {"status": status, "last_active_at": datetime.now(timezone.utc)}
        if container_id is not None:
            values["container_id"] = container_id
        if error_message is not None:
            values["error_message"] = error_message
        elif status == "running":
            values["error_message"] = None

        await self.db.execute(update(UserSandbox).where(UserSandbox.id == sandbox_id).values(**values))
        if flush_only:
            await self.db.flush()
        else:
            await self.db.commit()

    async def _update_last_active(self, sandbox_id: str):
        """Update last-active time only."""
        await self.db.execute(
            update(UserSandbox).where(UserSandbox.id == sandbox_id).values(last_active_at=datetime.now(timezone.utc))
        )
        await self.db.commit()

    async def stop_sandbox(self, sandbox_id: str) -> bool:
        """Stop the sandbox (stop container only, do not delete or remove from pool)."""
        await _sandbox_pool.stop(sandbox_id)
        result = await self.db.execute(
            update(UserSandbox)
            .where(UserSandbox.id == sandbox_id)
            .values(status="stopped", last_active_at=datetime.now(timezone.utc))
        )
        await self.db.commit()
        return bool(cast(CursorResult, result).rowcount > 0)

    async def restart_sandbox(self, sandbox_id: str) -> bool:
        """Restart the sandbox (start the same container, no delete or recreate)."""
        result = await self.db.execute(select(UserSandbox).where(UserSandbox.id == sandbox_id))
        record = result.scalar_one_or_none()
        if not record:
            return False

        adapter = await _sandbox_pool.get(sandbox_id)
        if adapter:
            try:
                if not adapter.is_started():
                    adapter.start()
                    container_id = adapter.get_container_id()
                    await self._update_status(sandbox_id, "running", container_id=container_id, error_message=None)
                # Always release the active_count from pool.get()
                await _sandbox_pool.release(sandbox_id)
                return True
            except Exception as e:
                logger.warning(f"Failed to start sandbox {sandbox_id}, will recreate: {e}")
                await _sandbox_pool.release(sandbox_id)

        # Fallback: recreate via ensure_sandbox_running (which also releases properly)
        try:
            new_adapter = await self.ensure_sandbox_running(record.user_id)
            # ensure_sandbox_running returns with active_count=1, release it since
            # this is an admin action, not an active usage session
            sandbox_id_for_release = getattr(new_adapter, "id", sandbox_id)
            await _sandbox_pool.release(sandbox_id_for_release)
            return True
        except Exception as e:
            logger.error(f"Failed to restart sandbox {sandbox_id}: {e}")
            return False

    async def rebuild_sandbox(self, sandbox_id: str) -> bool:
        """Rebuild the sandbox: delete the old container and start a new one."""
        result = await self.db.execute(select(UserSandbox).where(UserSandbox.id == sandbox_id))
        record = result.scalar_one_or_none()
        if not record:
            return False
        await _sandbox_pool.remove(sandbox_id)  # stop + remove container
        try:
            new_adapter = await self.ensure_sandbox_running(record.user_id)
            # Release the active_count since this is an admin action
            sandbox_id_for_release = getattr(new_adapter, "id", sandbox_id)
            await _sandbox_pool.release(sandbox_id_for_release)
            return True
        except Exception as e:
            logger.error(f"Failed to rebuild sandbox {sandbox_id}: {e}")
            return False

    async def update_sandbox_config(self, sandbox_id: str, image: Optional[str] = None) -> bool:
        """Update sandbox config (e.g. image); the new image takes effect on the next rebuild or container creation."""
        values: Dict[str, Any] = {}
        if image is not None:
            image_str = image.strip()
            if not image_str:
                return False
            if len(image_str) > 255:
                return False
            values["image"] = image_str
        if not values:
            return True
        result = await self.db.execute(update(UserSandbox).where(UserSandbox.id == sandbox_id).values(**values))
        await self.db.commit()
        return bool(cast(CursorResult, result).rowcount > 0)

    async def delete_sandbox(self, sandbox_id: str) -> bool:
        """Permanently delete the sandbox record and container."""
        await _sandbox_pool.remove(sandbox_id)  # stop + remove container
        result = await self.db.execute(delete(UserSandbox).where(UserSandbox.id == sandbox_id))
        await self.db.commit()
        return bool(cast(CursorResult, result).rowcount > 0)

    async def cleanup_idle_sandboxes(self) -> int:
        """Clean up all idle sandboxes (background task)."""
        evicted_ids = await _sandbox_pool.cleanup_idle()

        if evicted_ids:
            logger.info(f"Syncing status for evicted sandboxes: {evicted_ids}")
            await self.db.execute(update(UserSandbox).where(UserSandbox.id.in_(evicted_ids)).values(status="stopped"))
            await self.db.commit()

        return len(evicted_ids)


async def get_sandbox_handle(user_id: str) -> Any:
    """Standalone helper to acquire a SandboxHandle for a user.

    Opens a DB session, creates SandboxManagerService, and calls ensure_sandbox_running.
    Caller MUST release the handle via handle.release() or async with handle.
    """
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        service = SandboxManagerService(db)
        return await service.ensure_sandbox_running(user_id)
