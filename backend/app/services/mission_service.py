"""
Mission service layer — pure CRUD + status machine.

Execution dispatch logic lives in ExecutionLifecycleService.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.mission import Mission, AssigneeType, MissionPriority, MissionStatus
from app.repositories.agent_profile import AgentProfileRepository
from app.repositories.mission import MissionRepository


class MissionService:
    """Manages mission CRUD and status transitions."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MissionRepository(db)
        self.agent_repo = AgentProfileRepository(db)

    async def create_mission(
        self,
        *,
        workspace_id: uuid.UUID,
        creator_id: str,
        title: str,
        description: Optional[str] = None,
        objective: Optional[str] = None,
        priority: MissionPriority = MissionPriority.NONE,
        parent_mission_id: Optional[uuid.UUID] = None,
        tags: Optional[list] = None,
        position: float = 0.0,
        auto_approve: bool = False,
    ) -> Mission:
        mission = Mission(
            workspace_id=workspace_id,
            creator_id=creator_id,
            title=title,
            description=description,
            objective=objective,
            priority=priority,
            status=MissionStatus.BACKLOG,
            parent_mission_id=parent_mission_id,
            tags=tags,
            position=position,
            auto_approve=auto_approve,
        )
        self.db.add(mission)
        await self.db.commit()
        await self.db.refresh(mission)
        logger.info(f"Created mission: {mission.id} ({title})")
        return mission

    async def get_mission(
        self, mission_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Optional[Mission]:
        return await self.repo.get_by_id_and_workspace(mission_id, workspace_id)

    async def list_missions(
        self,
        *,
        workspace_id: uuid.UUID,
        status: Optional[str] = None,
        creator_id: Optional[str] = None,
        assignee_id: Optional[uuid.UUID] = None,
        parent_mission_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> list[Mission]:
        return list(
            await self.repo.list_by_workspace(
                workspace_id=workspace_id,
                status=status,
                creator_id=creator_id,
                assignee_id=assignee_id,
                parent_mission_id=parent_mission_id,
                limit=limit,
            )
        )

    MANUAL_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
        MissionStatus.BACKLOG:     {MissionStatus.TODO, MissionStatus.IN_PROGRESS, MissionStatus.CANCELLED},
        MissionStatus.TODO:        {MissionStatus.BACKLOG, MissionStatus.IN_PROGRESS, MissionStatus.CANCELLED},
        MissionStatus.IN_PROGRESS: {MissionStatus.TODO, MissionStatus.IN_REVIEW, MissionStatus.DONE, MissionStatus.CANCELLED},
        MissionStatus.IN_REVIEW:   {MissionStatus.TODO, MissionStatus.IN_PROGRESS, MissionStatus.DONE, MissionStatus.CANCELLED},
        MissionStatus.DONE:        {MissionStatus.BACKLOG, MissionStatus.TODO},
        MissionStatus.CANCELLED:   {MissionStatus.BACKLOG, MissionStatus.TODO},
    }

    @classmethod
    def get_transitions(cls) -> dict[str, list[str]]:
        return {
            status.value: sorted(t.value for t in targets)
            for status, targets in cls.MANUAL_TRANSITIONS.items()
        }

    async def update_mission(
        self,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        **kwargs: Any,
    ) -> Optional[Mission]:
        mission = await self.repo.get_by_id_and_workspace(mission_id, workspace_id)
        if not mission:
            return None

        new_status = kwargs.get("status")
        if new_status is not None:
            try:
                new_status = MissionStatus(new_status)
            except ValueError:
                raise BadRequestException(f"Invalid status: {new_status}")

            if new_status != mission.status:
                allowed_targets = self.MANUAL_TRANSITIONS.get(mission.status, set())
                if new_status not in allowed_targets:
                    raise BadRequestException(
                        f"Cannot transition from {mission.status.value} to {new_status.value}"
                    )
                if mission.current_execution_id and new_status in {
                    MissionStatus.DONE, MissionStatus.CANCELLED,
                }:
                    raise ConflictException(
                        f"Cannot move to {new_status.value} while an execution is active — "
                        f"cancel the execution first"
                    )

        allowed = {
            "title", "description", "objective", "priority",
            "status", "assignee_type", "assignee_id",
            "parent_mission_id", "due_date", "position", "tags",
            "auto_approve",
        }
        for key, value in kwargs.items():
            if key in allowed:
                setattr(mission, key, value)
        await self.db.commit()
        await self.db.refresh(mission)
        return mission

    async def assign_to_agent(
        self,
        *,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        agent_profile_id: uuid.UUID,
    ) -> Mission:
        """Assign a mission to an agent profile and move it to TODO status."""
        mission = await self.repo.get_for_update(mission_id, workspace_id)
        if not mission:
            raise NotFoundException(f"Mission not found: {mission_id}")

        agent = await self.agent_repo.get_by_id_and_workspace(agent_profile_id, workspace_id)
        if not agent:
            raise NotFoundException(f"Agent profile not found: {agent_profile_id}")

        mission.assignee_type = AssigneeType.AGENT
        mission.assignee_id = agent_profile_id
        if mission.status == MissionStatus.BACKLOG:
            mission.status = MissionStatus.TODO
        await self.db.commit()
        await self.db.refresh(mission)
        logger.info(f"Assigned mission {mission_id} to agent {agent_profile_id}")
        return mission
