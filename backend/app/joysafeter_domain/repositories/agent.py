"""
Repositories for Agent and AgentVersion.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.joysafeter_domain.models.agent import Agent, AgentVersion

from .base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, db: AsyncSession):
        super().__init__(Agent, db)

    async def get_by_project_and_slug(self, project_id: str, slug: str) -> Optional[Agent]:
        query = select(Agent).where(
            Agent.project_id == project_id,
            Agent.slug == slug,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: str) -> List[Agent]:
        query = (
            select(Agent)
            .options(
                selectinload(Agent.current_draft_version),
                selectinload(Agent.active_release),
            )
            .where(Agent.project_id == project_id)
            .order_by(Agent.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())


class AgentVersionRepository(BaseRepository[AgentVersion]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentVersion, db)

    async def list_by_agent(self, agent_id: uuid.UUID) -> List[AgentVersion]:
        query = (
            select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version_number.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_max_version_number(self, agent_id: uuid.UUID) -> int:
        query = select(func.coalesce(func.max(AgentVersion.version_number), 0)).where(AgentVersion.agent_id == agent_id)
        result = await self.db.execute(query)
        return result.scalar() or 0
