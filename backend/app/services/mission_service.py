"""
Mission service layer with dispatch logic.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentStatus
from app.models.execution import ExecutionSource, MissionExecutionStatus
from app.models.mission import Mission, MissionPriority, MissionStatus
from app.repositories.agent_profile import AgentProfileRepository
from app.repositories.mission import MissionRepository
from app.services.execution_service import ExecutionService
from app.utils.datetime import utc_now


def _handle_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(f"Background dispatch task failed: {exc}")


def _start_execution_runner(
    execution_id: uuid.UUID,
    prompt: str,
    credentials: dict[str, str] | None,
) -> None:
    """Fire-and-forget: launch an ExecutionRunner in a background task."""
    from app.core.agent.cli_backends.execution_runner import ExecutionRunner
    from app.core.database import AsyncSessionLocal

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            runner = ExecutionRunner(db)
            try:
                await runner.run(
                    execution_id=execution_id,
                    prompt=prompt,
                    credentials=credentials,
                )
            except Exception as exc:
                logger.error(f"Background runner failed for {execution_id}: {exc}")

    task = asyncio.create_task(_run(), name=f"dispatch-{execution_id}")
    task.add_done_callback(_handle_task_exception)


def build_execution_prompt(mission: Mission) -> str:
    """Build the prompt sent to the CLI agent for a mission."""
    parts: list[str] = []
    parts.append(f"# Mission: {mission.title}")
    if mission.description:
        parts.append(f"\n## Description\n{mission.description}")
    if mission.objective:
        parts.append(f"\n## Objective\n{mission.objective}")
    if mission.tags:
        parts.append(f"\n## Tags\n{', '.join(str(t) for t in mission.tags)}")
    return "\n".join(parts)


class MissionService:
    """Manages mission lifecycle and agent dispatch."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MissionRepository(db)
        self.agent_repo = AgentProfileRepository(db)
        self.execution_service = ExecutionService(db)

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

    async def update_mission(
        self,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        **kwargs: Any,
    ) -> Optional[Mission]:
        mission = await self.repo.get_by_id_and_workspace(mission_id, workspace_id)
        if not mission:
            return None
        allowed = {
            "title", "description", "objective", "priority",
            "status", "assignee_type", "assignee_id",
            "parent_mission_id", "due_date", "position", "tags",
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
            raise ValueError(f"Mission not found: {mission_id}")

        agent = await self.agent_repo.get_by_id_and_workspace(agent_profile_id, workspace_id)
        if not agent:
            raise ValueError(f"Agent profile not found: {agent_profile_id}")

        mission.assignee_type = "agent"
        mission.assignee_id = agent_profile_id
        if mission.status == MissionStatus.BACKLOG:
            mission.status = MissionStatus.TODO
        await self.db.commit()
        await self.db.refresh(mission)
        logger.info(f"Assigned mission {mission_id} to agent {agent_profile_id}")
        return mission

    async def dispatch_mission(
        self,
        *,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: str,
        runtime_config: Optional[dict[str, Any]] = None,
    ) -> tuple[Mission, Any]:
        """Dispatch a mission: create an execution and transition to IN_PROGRESS.

        Returns the updated mission and the created execution.
        """
        mission = await self.repo.get_for_update(mission_id, workspace_id)
        if not mission:
            raise ValueError(f"Mission not found: {mission_id}")

        if mission.status not in {MissionStatus.TODO, MissionStatus.BACKLOG}:
            raise ValueError(
                f"Mission {mission_id} cannot be dispatched from status {mission.status.value}"
            )

        if not mission.assignee_id or mission.assignee_type != "agent":
            raise ValueError(f"Mission {mission_id} has no agent assignee")

        agent = await self.agent_repo.get_by_id_and_workspace(
            mission.assignee_id, workspace_id
        )
        if not agent:
            raise ValueError(f"Agent profile not found: {mission.assignee_id}")

        execution = await self.execution_service.create_execution(
            workspace_id=workspace_id,
            user_id=user_id,
            source=ExecutionSource.MISSION,
            source_id=str(mission_id),
            runtime_type=agent.runtime_type,
            title=mission.title,
            mission_id=mission_id,
            agent_profile_id=mission.assignee_id,
            runtime_config=runtime_config or agent.runtime_config,
        )

        mission.status = MissionStatus.IN_PROGRESS
        mission.current_execution_id = execution.id
        await self.db.commit()
        await self.db.refresh(mission)

        logger.info(
            f"Dispatched mission {mission_id} -> execution {execution.id} "
            f"(agent={agent.name}, runtime={agent.runtime_type})"
        )

        # Start the runner in the background so the execution doesn't stay QUEUED
        prompt = build_execution_prompt(mission)
        credentials = dict(agent.custom_env or {})
        _start_execution_runner(execution.id, prompt, credentials or None)

        return mission, execution

    async def complete_mission(
        self,
        *,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Optional[Mission]:
        """Mark a mission as DONE."""
        mission = await self.repo.get_for_update(mission_id, workspace_id)
        if not mission:
            return None
        mission.status = MissionStatus.DONE
        await self.db.commit()
        await self.db.refresh(mission)
        return mission

    async def cancel_mission(
        self,
        *,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Optional[Mission]:
        """Cancel a mission and its active execution if any."""
        mission = await self.repo.get_for_update(mission_id, workspace_id)
        if not mission:
            return None

        if mission.current_execution_id:
            await self.execution_service.mark_status(
                execution_id=mission.current_execution_id,
                status=MissionExecutionStatus.CANCELLED,
            )

        mission.status = MissionStatus.CANCELLED
        await self.db.commit()
        await self.db.refresh(mission)
        return mission

    async def dispatch_ready_missions(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: str,
        limit: int = 10,
    ) -> list[tuple[Mission, Any]]:
        """Background task: find TODO missions with agent assignees and dispatch them.

        Returns list of (mission, execution) tuples for successfully dispatched missions.
        """
        dispatchable = await self.repo.list_dispatchable(
            workspace_id=workspace_id, limit=limit
        )
        results: list[tuple[Mission, Any]] = []
        for mission in dispatchable:
            try:
                result = await self.dispatch_mission(
                    mission_id=mission.id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                results.append(result)
            except Exception as exc:
                logger.warning(
                    f"Failed to dispatch mission {mission.id}: {exc}"
                )
        return results
