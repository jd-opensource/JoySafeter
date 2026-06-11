"""
Repository for AgentRelease.
"""

from __future__ import annotations

import uuid
from typing import List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.agent import AgentRelease, AgentVersion

from .base import BaseRepository


class AgentReleaseRepository(BaseRepository[AgentRelease]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentRelease, db)

    async def list_by_agent(self, agent_id: uuid.UUID) -> List[AgentRelease]:
        """List all releases for an agent (joining through AgentVersion)."""
        query = (
            select(AgentRelease)
            .join(AgentVersion, AgentRelease.agent_version_id == AgentVersion.id)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentRelease.release_number.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_max_release_number(self, agent_version_id: uuid.UUID) -> int:
        """Get the max release number for a given agent version (for auto-increment)."""
        query = select(func.coalesce(func.max(AgentRelease.release_number), 0)).where(
            AgentRelease.agent_version_id == agent_version_id
        )
        result = await self.db.execute(query)
        return result.scalar() or 0
