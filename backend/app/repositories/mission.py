"""
Mission repository helpers.
"""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import Mission, AssigneeType, MissionStatus

from .base import BaseRepository


class MissionRepository(BaseRepository[Mission]):
    def __init__(self, db: AsyncSession):
        super().__init__(Mission, db)

    async def get_by_id_and_workspace(
        self, mission_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Optional[Mission]:
        result = await self.db.execute(
            select(Mission).where(
                Mission.id == mission_id,
                Mission.workspace_id == workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(
        self, mission_id: uuid.UUID, workspace_id: Optional[uuid.UUID] = None
    ) -> Optional[Mission]:
        query = select(Mission).where(Mission.id == mission_id)
        if workspace_id is not None:
            query = query.where(Mission.workspace_id == workspace_id)
        result = await self.db.execute(query.with_for_update())
        return result.scalar_one_or_none()

    async def list_by_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
        status: Optional[str] = None,
        creator_id: Optional[str] = None,
        assignee_id: Optional[uuid.UUID] = None,
        parent_mission_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> Sequence[Mission]:
        query = select(Mission).where(Mission.workspace_id == workspace_id)
        if status:
            query = query.where(Mission.status == status)
        if creator_id:
            query = query.where(Mission.creator_id == creator_id)
        if assignee_id:
            query = query.where(Mission.assignee_id == assignee_id)
        if parent_mission_id:
            query = query.where(Mission.parent_mission_id == parent_mission_id)
        result = await self.db.execute(
            query.order_by(Mission.position.asc(), desc(Mission.created_at)).limit(limit)
        )
        return result.scalars().all()

    async def list_dispatchable(
        self, *, workspace_id: Optional[uuid.UUID] = None, limit: int = 10
    ) -> Sequence[Mission]:
        """Find TODO missions with an agent assignee, ready for dispatch.

        When workspace_id is None, searches across all workspaces.
        """
        query = select(Mission).where(
            Mission.status == MissionStatus.TODO,
            Mission.assignee_type == AssigneeType.AGENT,
            Mission.assignee_id.isnot(None),
            Mission.current_execution_id.is_(None),
        )
        if workspace_id is not None:
            query = query.where(Mission.workspace_id == workspace_id)
        result = await self.db.execute(
            query.order_by(Mission.position.asc(), Mission.created_at.asc()).limit(limit)
        )
        return result.scalars().all()
