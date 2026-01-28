"""
环境变量与机密管理服务

支持：
- 用户环境变量（Environment）
- 工作空间环境变量（WorkspaceEnvironment）
提供基础的读取/更新与合并能力（未做加密，后续可挂接 KMS）
"""

from __future__ import annotations

import uuid
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Environment, WorkspaceEnvironment


class EnvironmentService:
    """环境变量读写与合并"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_env(self, user_id: uuid.UUID) -> Dict[str, str]:
        result = await self.db.execute(select(Environment).where(Environment.user_id == user_id))
        row = result.scalar_one_or_none()
        return row.variables if row else {}

    async def upsert_user_env(self, user_id: uuid.UUID, variables: Dict[str, str]) -> Dict[str, str]:
        existing = await self.db.execute(select(Environment).where(Environment.user_id == user_id))
        env_row = existing.scalar_one_or_none()
        if env_row:
            env_row.variables = variables
        else:
            env_row = Environment(user_id=user_id, variables=variables)
            self.db.add(env_row)
        await self.db.commit()
        return env_row.variables

    async def get_workspace_env(self, workspace_id: uuid.UUID) -> Dict[str, str]:
        result = await self.db.execute(
            select(WorkspaceEnvironment).where(WorkspaceEnvironment.workspace_id == workspace_id)
        )
        row = result.scalar_one_or_none()
        return row.variables if row else {}

    async def upsert_workspace_env(self, workspace_id: uuid.UUID, variables: Dict[str, str]) -> Dict[str, str]:
        existing = await self.db.execute(
            select(WorkspaceEnvironment).where(WorkspaceEnvironment.workspace_id == workspace_id)
        )
        env_row = existing.scalar_one_or_none()
        if env_row:
            env_row.variables = variables
        else:
            env_row = WorkspaceEnvironment(workspace_id=workspace_id, variables=variables)
            self.db.add(env_row)
        await self.db.commit()
        return env_row.variables

    async def merge_user_workspace_env(self, user_id: uuid.UUID, workspace_id: Optional[uuid.UUID]) -> Dict[str, str]:
        user_env = await self.get_user_env(user_id)
        workspace_env = {}
        if workspace_id:
            workspace_env = await self.get_workspace_env(workspace_id)
        # workspace 优先覆盖个人，保证团队配置生效
        return {**user_env, **workspace_env}

    @staticmethod
    def mask_variables(variables: Dict[str, str]) -> Dict[str, str]:
        """仅返回键名，用于安全展示"""
        return {k: "***" for k in variables.keys()}
