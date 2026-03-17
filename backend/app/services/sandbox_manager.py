"""
Sandbox Manager Service
"""

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
# In a real production environment with multiple workers,
# this pool might need to be managed differently or be per-worker.
# Since containers are external resources, per-worker pools are generally fine
# as long as they don't exceed total system capacity.
_sandbox_pool = SandboxPool()


class SandboxManagerService:
    """
    用户沙箱管理服务 - 生产级实现

    核心职责：
    1. 管理 UserSandbox 数据库记录
    2. 协调 Docker 容器的生命周期 (通过 PydanticSandboxAdapter)
    3. 维护沙箱连接池
    4. 监控沙箱状态
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
        """
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
                await self._update_status(sandbox_record.id, "running", error_message=None)
                return adapter
            except Exception as e:
                logger.warning(f"Failed to start existing sandbox {sandbox_record.id}, will recreate: {e}")
                await _sandbox_pool.remove(sandbox_record.id)

        # 3. 启动新容器
        try:
            # 更新状态为 creating
            await self._update_status(sandbox_record.id, "creating")

            # 准备持久化存储
            import os

            host_sandbox_dir = f"/tmp/sandboxes/{user_id}"
            os.makedirs(host_sandbox_dir, exist_ok=True)
            volumes = {host_sandbox_dir: "/workspace"}

            # 创建适配器（会自动启动容器）
            logger.info(f"Starting sandbox for user {user_id} (id={sandbox_record.id})")
            adapter = PydanticSandboxAdapter(
                image=sandbox_record.image,
                session_id=sandbox_record.id,  # 使用沙箱ID作为 session_id
                idle_timeout=sandbox_record.idle_timeout,
                volumes=volumes,
                auto_remove=DEFAULT_USER_SANDBOX_AUTO_REMOVE,  # stop/restart 不删容器，仅 rebuild 删
                # 注意：目前 PydanticSandboxAdapter 不直接支持 cpu/memory limit 参数
                # 如果需要支持，需修改 PydanticSandboxAdapter 的 __init__ 和底层 DockerSandbox 调用
            )

            # 4. 注册到池中
            await _sandbox_pool.put(sandbox_record.id, adapter)

            # 5. 更新数据库状态
            # 我们无法轻易获取 container_id，除非 adapter 暴露它
            # PydanticSandboxAdapter 目前没有暴露 container_id，但有 id (session_id)
            await self._update_status(
                sandbox_record.id,
                "running",
                container_id=None,  # Adapter 暂未暴露 container_id
                error_message=None,
            )

            return adapter

        except Exception as e:
            logger.error(f"Failed to start sandbox for user {user_id}: {e}")
            await self._update_status(sandbox_record.id, "failed", error_message=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Failed to start sandbox: {str(e)}"
            )

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
        if adapter and not adapter.is_started():
            try:
                adapter.start()
                await self._update_status(sandbox_id, "running", error_message=None)
                return True
            except Exception as e:
                logger.warning(f"Failed to start sandbox {sandbox_id}, will recreate: {e}")
        try:
            await self.ensure_sandbox_running(record.user_id)
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
            await self.ensure_sandbox_running(record.user_id)
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
        # 1. 清理池中的闲置连接，并获取被清理的ID列表
        evicted_ids = await _sandbox_pool.cleanup_idle()

        if evicted_ids:
            # 2. 更新数据库状态为 stopped
            logger.info(f"Syncing status for evicted sandboxes: {evicted_ids}")
            await self.db.execute(update(UserSandbox).where(UserSandbox.id.in_(evicted_ids)).values(status="stopped"))
            await self.db.commit()

        return len(evicted_ids)
