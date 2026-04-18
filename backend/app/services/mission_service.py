"""
Mission service layer with dispatch logic.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentStatus
from app.models.execution import Execution as ExecModel, ExecutionSource, MissionExecutionStatus, TERMINAL_EXECUTION_STATUSES
from app.models.mission import Mission, AssigneeType, MissionPriority, MissionStatus
from app.repositories.agent_profile import AgentProfileRepository
from app.repositories.mission import MissionRepository
from app.services.execution_service import ExecutionService
from app.utils.credentials import build_credentials
from app.utils.datetime import utc_now
from app.utils.safe_task import safe_create_task


def _start_execution_runner(
    execution_id: uuid.UUID,
    prompt: str,
    credentials: dict[str, str] | None,
) -> None:
    """Fire-and-forget: launch an ExecutionRunner in a background task."""
    from app.core.agent.cli_backends.execution_runner import ExecutionRunner
    from app.core.database import AsyncSessionLocal
    from app.utils.task_manager import task_manager

    async def _run() -> None:
        current_task = asyncio.current_task()
        if current_task:
            await task_manager.register_task(str(execution_id), current_task)
        try:
            async with AsyncSessionLocal() as db:
                runner = ExecutionRunner(db)
                await runner.run(
                    execution_id=execution_id,
                    prompt=prompt,
                    credentials=credentials,
                )
        except Exception as exc:
            logger.error(f"Background runner failed for {execution_id}: {exc}")
        finally:
            await task_manager.unregister_task(str(execution_id))

    task = safe_create_task(_run(), name=f"dispatch-{execution_id}")


def build_execution_prompt(mission: Mission, trigger_comment=None) -> str:
    """Build the prompt sent to the CLI agent for a mission."""
    parts: list[str] = []
    parts.append(f"# Mission: {mission.title}")
    if mission.description:
        parts.append(f"\n## Description\n{mission.description}")
    if mission.objective:
        parts.append(f"\n## Objective\n{mission.objective}")
    if mission.tags:
        parts.append(f"\n## Tags\n{', '.join(str(t) for t in mission.tags)}")
    if trigger_comment:
        parts.append(
            f"\n## [NEW COMMENT]\n"
            f"A user just left a new comment. You MUST respond to THIS comment:\n\n"
            f"> {trigger_comment.content[:4000]}"
        )
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
                raise ValueError(f"Invalid status: {new_status}")

            if new_status != mission.status:
                allowed_targets = self.MANUAL_TRANSITIONS.get(mission.status, set())
                if new_status not in allowed_targets:
                    raise ValueError(
                        f"Cannot transition from {mission.status.value} to {new_status.value}"
                    )
                if mission.current_execution_id and new_status in {
                    MissionStatus.DONE, MissionStatus.CANCELLED,
                }:
                    raise ValueError(
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
            raise ValueError(f"Mission not found: {mission_id}")

        agent = await self.agent_repo.get_by_id_and_workspace(agent_profile_id, workspace_id)
        if not agent:
            raise ValueError(f"Agent profile not found: {agent_profile_id}")

        mission.assignee_type = AssigneeType.AGENT
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

        if mission.status not in {
            MissionStatus.TODO, MissionStatus.BACKLOG,
            MissionStatus.IN_PROGRESS, MissionStatus.IN_REVIEW,
        }:
            raise ValueError(
                f"Mission {mission_id} cannot be dispatched from status {mission.status.value}"
            )

        # If mission is IN_PROGRESS, check if the current execution is actually terminal
        if mission.status == MissionStatus.IN_PROGRESS:
            if mission.current_execution_id:
                current_exec = (
                    await self.db.execute(
                        select(ExecModel).where(ExecModel.id == mission.current_execution_id)
                    )
                ).scalar_one_or_none()
                if current_exec and current_exec.status in {
                    MissionExecutionStatus.RUNNING,
                    MissionExecutionStatus.DISPATCHED,
                    MissionExecutionStatus.QUEUED,
                    MissionExecutionStatus.APPROVAL_WAIT,
                }:
                    raise ValueError(
                        f"Mission {mission_id} already has an active execution"
                    )
            # Stale IN_PROGRESS — reset so we can re-dispatch
            mission.current_execution_id = None

        if not mission.assignee_id or mission.assignee_type != AssigneeType.AGENT:
            raise ValueError(f"Mission {mission_id} has no agent assignee")

        agent = await self.agent_repo.get_by_id_and_workspace(
            mission.assignee_id, workspace_id
        )
        if not agent:
            raise ValueError(f"Agent profile not found: {mission.assignee_id}")

        # Validate credentials before creating the execution row
        credentials = build_credentials(agent.custom_env)
        prompt = build_execution_prompt(mission)

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
        _start_execution_runner(execution.id, prompt, credentials)

        return mission, execution

    async def finalize_mission_execution(
        self,
        *,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
    ) -> None:
        """Called by ExecutionRunner after completion/failure to update the parent Mission."""
        from sqlalchemy import select

        mission = (
            await self.db.execute(
                select(Mission)
                .where(Mission.current_execution_id == execution_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not mission:
            return

        mission.current_execution_id = None

        if status == MissionExecutionStatus.COMPLETED:
            if mission.status != MissionStatus.CANCELLED:
                mission.status = MissionStatus.DONE if mission.auto_approve else MissionStatus.IN_REVIEW
        elif status == MissionExecutionStatus.FAILED:
            if mission.status == MissionStatus.IN_PROGRESS:
                mission.status = MissionStatus.TODO
        # CANCELLED is handled by cancel_mission directly

        await self.db.commit()

        from app.websocket.notification_manager import NotificationType, notification_manager
        await notification_manager.broadcast({
            "type": NotificationType.MISSION_UPDATED.value,
            "mission_id": str(mission.id),
            "status": mission.status.value,
        })

        logger.info(
            f"Finalized mission {mission.id}: execution {execution_id} "
            f"-> mission status {mission.status.value}"
        )

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
            exec_id = mission.current_execution_id
            current_exec = (
                await self.db.execute(
                    select(ExecModel).where(ExecModel.id == exec_id)
                )
            ).scalar_one_or_none()
            if current_exec and current_exec.status not in TERMINAL_EXECUTION_STATUSES:
                await self.execution_service.mark_status(
                    execution_id=exec_id,
                    status=MissionExecutionStatus.CANCELLED,
                )
                # Terminate the running container process
                from app.core.agent.cli_backends.session_registry import session_registry
                session = session_registry.get(exec_id)
                if session:
                    await session.cancel()
                # Cancel the asyncio background task
                from app.utils.task_manager import task_manager
                await task_manager.cancel_task(str(exec_id))

        mission.status = MissionStatus.CANCELLED
        mission.current_execution_id = None
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

    async def dispatch_all_ready_missions(self, *, limit: int = 20) -> int:
        """Cross-workspace auto-dispatch: find all ready TODO missions and dispatch them."""
        dispatchable = await self.repo.list_dispatchable(limit=limit)
        dispatched = 0
        for mission in dispatchable:
            try:
                await self.dispatch_mission(
                    mission_id=mission.id,
                    workspace_id=mission.workspace_id,
                    user_id=mission.creator_id,
                )
                dispatched += 1
            except Exception as exc:
                logger.warning(f"Auto-dispatch failed for mission {mission.id}: {exc}")
        return dispatched
