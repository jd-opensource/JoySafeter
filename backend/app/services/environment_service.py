"""
Environment variable and secret management service.

Supports:
- User environment variables (Environment)
- Workspace environment variables (WorkspaceEnvironment)
Provides basic read/update and merge capabilities (no encryption yet; KMS can be plugged in later).
"""

from __future__ import annotations

import uuid
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Environment, WorkspaceEnvironment


class EnvironmentService:
    """Environment variable read/write and merge."""

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
        # workspace overrides personal, ensuring team config takes effect
        return {**user_env, **workspace_env}

    @staticmethod
    def mask_variables(variables: Dict[str, str]) -> Dict[str, str]:
        """Return key names only, for safe display."""
        return {k: "***" for k in variables.keys()}
