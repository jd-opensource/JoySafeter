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
    用户沙箱管理服务 - 生产级实现

    核心职责：
    1. 管理 UserSandbox 数据库记录
    2. 协调 Docker 容器的生命周期 (通过 PydanticSandboxAdapter)
    3. 维护沙箱连接池
    4. 监控沙箱状态

    并发安全：
    - ensure_sandbox_running 使用 per-user lock 防止同一用户并发创建多个容器
    - SandboxPool 使用 asyncio.Lock 保护内部状态
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_sandbox_record(self, user_id: str) -> Optional[UserSandbox]:
        """获取用户的沙箱记录"""
        result = await self.db.execute(select(UserSandbox).where(UserSandbox.user_id == user_id))
        return result.scalar_one_or_none()

    async def create_sandbox_record(self, user_id: str) -> UserSandbox:
        """创建新的沙箱记录（不启动容器）"""
        # 检查是否已存在
        existing = await self.get_user_sandbox_record(user_id)
        if existing:
            return existing

        new_sandbox = UserSandbox(
            id=str(uuid.uuid4()),
            user_id=user_id,
            status="pending",
            image=DEFAULT_USER_SANDBOX_IMAGE,
            idle_timeout=DEFAULT_USER_SANDBOX_IDLE_TIMEOUT,
            cpu_limit=DEFAULT_USER_SANDBOX_CPU_LIMIT,
            memory_limit=DEFAULT_USER_SANDBOX_MEMORY_LIMIT,
        )
        self.db.add(new_sandbox)
        await self.db.commit()
        await self.db.refresh(new_sandbox)
        return new_sandbox

    async def ensure_sandbox_running(self, user_id: str) -> PydanticSandboxAdapter:
        """
        确保用户的沙箱正在运行，并返回可用的适配器。
        如果沙箱不存在则创建，如果已停止则启动。

        使用 per-user lock 防止并发创建多个容器。
        返回的 adapter 已在 pool 中 active_count += 1, 调用方结束后
        必须通过 _sandbox_pool.release(sandbox_id) 释放引用。
        """
        # Per-user lock: 同一用户的并发请求串行化，避免创建多个容器
        user_lock = await _get_user_lock(user_id)
        async with user_lock:
            return await self._ensure_sandbox_running_locked(user_id)

    async def _ensure_sandbox_running_locked(self, user_id: str) -> PydanticSandboxAdapter:
        """ensure_sandbox_running 的内部实现（已持有 per-user lock）"""
        # 1. 获取或创建记录
        sandbox_record = await self.get_user_sandbox_record(user_id)
        if not sandbox_record:
            sandbox_record = await self.create_sandbox_record(user_id)

        # 2. 尝试从池中获取
        adapter = await _sandbox_pool.get(sandbox_record.id)
        if adapter:
            if adapter.is_started():
                await self._update_last_active(sandbox_record.id)
                return adapter
            # 已停止但未移除：尝试重启同一容器
            try:
                adapter.start()
                # 保存 container_id 到 DB
                container_id = adapter.get_container_id()
                await self._update_status(
                    sandbox_record.id, "running",
                    container_id=container_id,
                    error_message=None,
                )
                return adapter
            except Exception as e:
                logger.warning(f"Failed to start existing sandbox {sandbox_record.id}, will recreate: {e}")
                # Release the active_count from pool.get() before removing
                await _sandbox_pool.release(sandbox_record.id)
                await _sandbox_pool.remove(sandbox_record.id)

        # 3. App 重启恢复：尝试重连已有容器
        if sandbox_record.container_id:
            try:
                adapter = self._reconnect_container(sandbox_record)
                if adapter:
                    await _sandbox_pool.put(sandbox_record.id, adapter)
                    container_id = adapter.get_container_id()
                    await self._update_status(
                        sandbox_record.id, "running",
                        container_id=container_id,
                        error_message=None,
                    )
                    logger.info(
                        f"Reconnected existing container {sandbox_record.container_id} "
                        f"for user {user_id}"
                    )
                    return adapter
            except Exception as e:
                logger.warning(
                    f"Failed to reconnect container {sandbox_record.container_id} "
                    f"for user {user_id}: {e}"
                )

        # 4. 启动新容器
        try:
            await self._update_status(sandbox_record.id, "creating")

            import os

            from app.utils.path_utils import sanitize_path_component

            safe_uid = sanitize_path_component(user_id, default="default")
            host_sandbox_dir = f"/tmp/sandboxes/{safe_uid}"
            os.makedirs(host_sandbox_dir, exist_ok=True)
            volumes = {host_sandbox_dir: "/workspace"}

            logger.info(f"Starting sandbox for user {user_id} (id={sandbox_record.id})")
            adapter = PydanticSandboxAdapter(
                image=sandbox_record.image,
                session_id=sandbox_record.id,
                idle_timeout=sandbox_record.idle_timeout,
                volumes=volumes,
                auto_remove=DEFAULT_USER_SANDBOX_AUTO_REMOVE,
                cpu_limit=sandbox_record.cpu_limit,
                memory_limit_mb=sandbox_record.memory_limit,
            )

            # 注册到池中 (put 会设 active_count=1)
            await _sandbox_pool.put(sandbox_record.id, adapter)

            # 保存 container_id 到 DB（支持 app 重启后恢复）
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
    def _reconnect_container(sandbox_record: UserSandbox) -> Optional[PydanticSandboxAdapter]:
        """尝试重连已存在的 Docker 容器（app 重启恢复场景）。

        Returns:
            成功时返回 PydanticSandboxAdapter, 失败返回 None
        """
        try:
            import docker

            client = docker.from_env()
            container = client.containers.get(sandbox_record.container_id)
            container_status = container.status  # "running", "exited", "created", etc.

            if container_status in ("exited", "created"):
                container.start()
            elif container_status != "running":
                logger.warning(
                    f"Container {sandbox_record.container_id} in unexpected state: {container_status}"
                )
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
        self, sandbox_id: str, status: str, container_id: Optional[str] = None, error_message: Optional[str] = None
    ):
        """更新沙箱状态"""
        values: Dict[str, Any] = {"status": status, "last_active_at": datetime.now(timezone.utc)}
        if container_id is not None:
            values["container_id"] = container_id
        if error_message is not None:
            values["error_message"] = error_message
        elif status == "running":
            values["error_message"] = None

        await self.db.execute(update(UserSandbox).where(UserSandbox.id == sandbox_id).values(**values))
        await self.db.commit()

    async def _update_last_active(self, sandbox_id: str):
        """仅更新活跃时间"""
        await self.db.execute(
            update(UserSandbox).where(UserSandbox.id == sandbox_id).values(last_active_at=datetime.now(timezone.utc))
        )
        await self.db.commit()

    async def stop_sandbox(self, sandbox_id: str) -> bool:
        """停止沙箱（仅停止容器，不删除、不移出池）"""
        await _sandbox_pool.stop(sandbox_id)
        result = await self.db.execute(
            update(UserSandbox)
            .where(UserSandbox.id == sandbox_id)
            .values(status="stopped", last_active_at=datetime.now(timezone.utc))
        )
        await self.db.commit()
        return bool(cast(CursorResult, result).rowcount > 0)

    async def restart_sandbox(self, sandbox_id: str) -> bool:
        """重启沙箱（启动同一容器，不删不新建）"""
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
        """重建沙箱：删除旧容器并启动新容器"""
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
        """更新沙箱配置（如 image）；新镜像在下次 rebuild 或新建容器时生效"""
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
        """彻底删除沙箱记录和容器"""
        await _sandbox_pool.remove(sandbox_id)  # stop + remove container
        result = await self.db.execute(delete(UserSandbox).where(UserSandbox.id == sandbox_id))
        await self.db.commit()
        return bool(cast(CursorResult, result).rowcount > 0)

    async def cleanup_idle_sandboxes(self) -> int:
        """清理所有闲置沙箱（后台任务）"""
        evicted_ids = await _sandbox_pool.cleanup_idle()

        if evicted_ids:
            logger.info(f"Syncing status for evicted sandboxes: {evicted_ids}")
            await self.db.execute(update(UserSandbox).where(UserSandbox.id.in_(evicted_ids)).values(status="stopped"))
            await self.db.commit()

        return len(evicted_ids)
