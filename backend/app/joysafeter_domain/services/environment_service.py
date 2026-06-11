"""
Environment variable and secret management service.

Supports:
- User environment variables (Environment)
- Project environment variables (ProjectEnvironment table, keyed by project_id)
Provides basic read/update and merge capabilities (no encryption yet; KMS can be plugged in later).
"""

from __future__ import annotations

import uuid
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.settings import Environment, ProjectEnvironment


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

    # ------------------------------------------------------------------
    # Project environment (uses project_environment table, keyed by project_id)
    # ------------------------------------------------------------------

    async def get_project_env(self, project_id: uuid.UUID) -> Dict[str, str]:
        """Get environment variables for a project (stored in project_environment table)."""
        result = await self.db.execute(
            select(ProjectEnvironment).where(ProjectEnvironment.project_id == str(project_id))
        )
        row = result.scalar_one_or_none()
        return row.variables if row else {}

    async def upsert_project_env(self, project_id: uuid.UUID, variables: Dict[str, str]) -> Dict[str, str]:
        """Upsert environment variables for a project (stored in project_environment table)."""
        existing = await self.db.execute(
            select(ProjectEnvironment).where(ProjectEnvironment.project_id == str(project_id))
        )
        env_row = existing.scalar_one_or_none()
        if env_row:
            env_row.variables = variables
        else:
            env_row = ProjectEnvironment(project_id=str(project_id), variables=variables)
            self.db.add(env_row)
        await self.db.commit()
        return env_row.variables

    # @deprecated — use get_project_env / upsert_project_env instead
    async def get_workspace_env(self, workspace_id: uuid.UUID) -> Dict[str, str]:
        return await self.get_project_env(workspace_id)

    # @deprecated — use upsert_project_env instead
    async def upsert_workspace_env(self, workspace_id: uuid.UUID, variables: Dict[str, str]) -> Dict[str, str]:
        return await self.upsert_project_env(workspace_id, variables)

    async def merge_user_project_env(self, user_id: uuid.UUID, project_id: Optional[uuid.UUID]) -> Dict[str, str]:
        """Merge user env with project env (project overrides user)."""
        user_env = await self.get_user_env(user_id)
        project_env: Dict[str, str] = {}
        if project_id:
            project_env = await self.get_project_env(project_id)
        # project overrides personal, ensuring team config takes effect
        return {**user_env, **project_env}

    # @deprecated — use merge_user_project_env instead
    async def merge_user_workspace_env(self, user_id: uuid.UUID, workspace_id: Optional[uuid.UUID]) -> Dict[str, str]:
        return await self.merge_user_project_env(user_id, workspace_id)

    @staticmethod
    def mask_variables(variables: Dict[str, str]) -> Dict[str, str]:
        """Return key names only, for safe display."""
        return {k: "***" for k in variables.keys()}
