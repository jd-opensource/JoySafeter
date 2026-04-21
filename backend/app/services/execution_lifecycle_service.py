# backend/app/services/execution_lifecycle_service.py
"""
ExecutionLifecycleService — the sole cross-domain coordinator
between Mission and Execution.

All operations that touch BOTH domains go through this service.
MissionService and ExecutionService remain single-domain and
never import each other.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, ConflictException, NotFoundException
from app.core.agent.cli_backends.base import CLIResult
from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.core.agent.cli_backends.session_registry import session_registry
from app.models.execution import (
    TERMINAL_EXECUTION_STATUSES,
    ExecutionSource,
    MissionExecutionStatus,
)
from app.models.execution import (
    Execution as ExecModel,
)
from app.models.mission import AssigneeType, Mission, MissionStatus
from app.repositories.agent_profile import AgentProfileRepository
from app.repositories.mission import MissionRepository
from app.services.execution_service import ExecutionService
from app.utils.credentials import build_credentials
from app.utils.safe_task import safe_create_task


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
                lifecycle = ExecutionLifecycleService(db)
                runner = ExecutionRunner(db, callbacks=lifecycle)
                await runner.run(
                    execution_id=execution_id,
                    prompt=prompt,
                    credentials=credentials,
                )
        except Exception as exc:
            logger.error(f"Background runner failed for {execution_id}: {exc}")
        finally:
            await task_manager.unregister_task(str(execution_id))

    safe_create_task(_run(), name=f"exec-{execution_id}")


class ExecutionLifecycleService(RunnerCallbacks):
    """Mediator: coordinates Mission <-> Execution interactions.

    Implements RunnerCallbacks so it can be injected into ExecutionRunner.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.execution_service = ExecutionService(db)
        self.mission_repo = MissionRepository(db)
        self.agent_repo = AgentProfileRepository(db)

    # ------------------------------------------------------------------
    # RunnerCallbacks implementation
    # ------------------------------------------------------------------

    async def on_execution_finalized(
        self,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
        result: CLIResult,
    ) -> None:
        """Called by ExecutionRunner after terminal state reached."""
        await self._post_completion_comment(execution_id, status, result)
        await self._finalize_mission(execution_id, status)

    async def on_execution_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
    ) -> None:
        """Called by ExecutionRunner on unhandled exception."""
        await self._post_completion_comment(
            execution_id,
            MissionExecutionStatus.FAILED,
            error_message=error,
        )
        await self._finalize_mission(execution_id, MissionExecutionStatus.FAILED)

    # ------------------------------------------------------------------
    # Finalize: update mission status after execution ends
    # ------------------------------------------------------------------

    async def _finalize_mission(
        self,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
    ) -> None:
        try:
            mission = (
                await self.db.execute(
                    select(Mission).where(Mission.current_execution_id == execution_id).with_for_update()
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
            elif status == MissionExecutionStatus.CANCELLED:
                if mission.status == MissionStatus.IN_PROGRESS:
                    mission.status = MissionStatus.TODO

            await self.db.commit()

            from app.websocket.notification_manager import (
                NotificationType,
                notification_manager,
            )

            await notification_manager.broadcast(
                {
                    "type": NotificationType.MISSION_UPDATED.value,
                    "mission_id": str(mission.id),
                    "status": mission.status.value,
                }
            )

            logger.info(
                f"Finalized mission {mission.id}: execution {execution_id} -> mission status {mission.status.value}"
            )
        except Exception as exc:
            logger.warning(f"Failed to finalize mission for execution {execution_id}: {exc}")

    # ------------------------------------------------------------------
    # Cancel: unified cancel path
    # ------------------------------------------------------------------

    async def cancel_execution(
        self,
        execution_id: uuid.UUID,
        user_id: str,
    ) -> Any:
        execution = await self.execution_service.get_execution(execution_id, user_id)
        if not execution:
            return None

        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return execution

        execution = await self.execution_service.mark_status(
            execution_id=execution_id,
            user_id=user_id,
            status=MissionExecutionStatus.CANCELLED,
            error_code="cancelled",
            error_message="Cancelled by user",
        )

        session = session_registry.get(execution_id)
        if session:
            try:
                await session.cancel()
            except Exception as exc:
                logger.warning(f"Failed to cancel session {execution_id}: {exc}")

        try:
            from app.utils.task_manager import task_manager

            await task_manager.cancel_task(str(execution_id))
        except Exception as exc:
            logger.warning(f"Failed to cancel task {execution_id}: {exc}")

        # Force-remove the Docker container so it doesn't linger
        await self._destroy_execution_container(execution)

        if execution and execution.mission_id:
            await self._finalize_mission(execution_id, MissionExecutionStatus.CANCELLED)

        return execution

    async def _destroy_execution_container(self, execution: Any) -> None:
        """Release this execution's container; destroy it if no other execution is using it."""
        from app.core.agent.cli_backends.container_pool import container_pool
        from app.core.agent.cli_backends.container_service import CLIContainerService

        if execution.agent_profile_id:
            try:
                destroyed = await container_pool.release_and_destroy_if_idle(execution.agent_profile_id)
                if destroyed:
                    logger.info(
                        f"Destroyed container for agent {execution.agent_profile_id} (execution {execution.id})"
                    )
                else:
                    logger.info(
                        f"Released container for agent {execution.agent_profile_id} "
                        f"(execution {execution.id}, still in use by other executions)"
                    )
                return
            except Exception as exc:
                logger.warning(f"Failed to release/destroy container for agent {execution.agent_profile_id}: {exc}")

        # No agent profile — remove by container_id directly
        if execution.container_id:
            try:
                svc = CLIContainerService()
                await svc.remove_container(execution.container_id, force=True)
                logger.info(f"Removed container {execution.container_id[:12]} for execution {execution.id}")
            except Exception as exc:
                logger.warning(f"Failed to remove container {execution.container_id[:12]}: {exc}")

    async def cancel_mission(
        self,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Optional[Mission]:
        mission = await self.mission_repo.get_for_update(mission_id, workspace_id)
        if not mission:
            return None

        if mission.current_execution_id:
            exec_id = mission.current_execution_id
            try:
                await self.execution_service.mark_status(
                    execution_id=exec_id,
                    status=MissionExecutionStatus.CANCELLED,
                    error_code="cancelled",
                    error_message="Mission cancelled by user",
                )
            except Exception as exc:
                logger.warning(f"Failed to mark execution {exec_id} cancelled: {exc}")

            session = session_registry.get(exec_id)
            if session:
                try:
                    await session.cancel()
                except Exception as exc:
                    logger.warning(f"Failed to cancel session {exec_id}: {exc}")

            try:
                from app.utils.task_manager import task_manager

                await task_manager.cancel_task(str(exec_id))
            except Exception as exc:
                logger.warning(f"Failed to cancel task {exec_id}: {exc}")

            # Force-remove the Docker container
            execution = await self.execution_service.get_execution_internal(exec_id)
            if execution:
                await self._destroy_execution_container(execution)

        mission.status = MissionStatus.CANCELLED
        mission.current_execution_id = None
        await self.db.commit()
        await self.db.refresh(mission)

        from app.websocket.notification_manager import (
            NotificationType,
            notification_manager,
        )

        await notification_manager.broadcast(
            {
                "type": NotificationType.MISSION_UPDATED.value,
                "mission_id": str(mission.id),
                "status": mission.status.value,
            }
        )

        return mission

    # ------------------------------------------------------------------
    # Auto-comment on execution completion
    # ------------------------------------------------------------------

    async def _post_completion_comment(
        self,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
        result: Optional[CLIResult] = None,
        error_message: str = "",
    ) -> None:
        try:
            execution = await self.execution_service.get_execution_internal(execution_id)
            if not execution or not execution.mission_id:
                return
            from app.services.mission_comment_service import MissionCommentService

            svc = MissionCommentService(self.db)
            await svc.post_execution_comment(
                execution=execution,
                result_status=status,
                result_output=(result.output[:2000] if result and result.output else ""),
                error_message=error_message[:2000] if error_message else "",
            )
        except Exception as exc:
            logger.warning(f"Failed to post completion comment for {execution_id}: {exc}")

    # ------------------------------------------------------------------
    # Dispatch: create execution + start runner
    # ------------------------------------------------------------------

    async def dispatch_mission(
        self,
        *,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: str,
        runtime_config: Optional[dict[str, Any]] = None,
    ) -> tuple[Mission, Any]:
        mission = await self.mission_repo.get_for_update(mission_id, workspace_id)
        if not mission:
            raise NotFoundException(f"Mission not found: {mission_id}")

        if mission.status not in {
            MissionStatus.TODO,
            MissionStatus.BACKLOG,
            MissionStatus.IN_PROGRESS,
            MissionStatus.IN_REVIEW,
        }:
            raise BadRequestException(f"Mission {mission_id} cannot be dispatched from status {mission.status.value}")

        if mission.status == MissionStatus.IN_PROGRESS and mission.current_execution_id:
            current_exec = (
                await self.db.execute(select(ExecModel).where(ExecModel.id == mission.current_execution_id))
            ).scalar_one_or_none()
            if current_exec and current_exec.status not in TERMINAL_EXECUTION_STATUSES:
                raise ConflictException(f"Mission {mission_id} already has an active execution")
            mission.current_execution_id = None

        if not mission.assignee_id or mission.assignee_type != AssigneeType.AGENT:
            raise BadRequestException(f"Mission {mission_id} has no agent assignee")

        agent = await self.agent_repo.get_by_id_and_workspace(mission.assignee_id, workspace_id)
        if not agent:
            raise NotFoundException(f"Agent profile not found: {mission.assignee_id}")

        active_count_result = await self.db.execute(
            select(func.count())
            .select_from(ExecModel)
            .where(
                ExecModel.agent_profile_id == agent.id,
                ExecModel.status.in_(
                    [
                        MissionExecutionStatus.QUEUED,
                        MissionExecutionStatus.DISPATCHED,
                        MissionExecutionStatus.RUNNING,
                        MissionExecutionStatus.APPROVAL_WAIT,
                    ]
                ),
            )
        )
        active_count = active_count_result.scalar() or 0
        if active_count >= agent.max_concurrent_tasks:
            raise ConflictException(
                f"Agent {agent.name} already has {active_count}/{agent.max_concurrent_tasks} active executions"
            )

        credentials = build_credentials(agent.custom_env)
        prompt = build_execution_prompt(mission)

        execution = await self.execution_service.create_execution(
            workspace_id=workspace_id,
            user_id=user_id,
            source=ExecutionSource.MISSION,
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

        logger.info(f"Dispatched mission {mission_id} -> execution {execution.id}")

        _start_execution_runner(execution.id, prompt, credentials)
        return mission, execution

    async def dispatch_all_ready_missions(self, *, limit: int = 20) -> int:
        dispatchable = await self.mission_repo.list_dispatchable(limit=limit)
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
                logger.warning(f"Failed to auto-dispatch mission {mission.id}: {exc}")
        return dispatched

    async def dispatch_for_comment(
        self,
        *,
        mission: Mission,
        trigger_comment: Any,
        user_id: str,
    ) -> Optional[uuid.UUID]:
        assert mission.assignee_id is not None
        agent = await self.agent_repo.get_by_id_and_workspace(mission.assignee_id, mission.workspace_id)
        if not agent:
            logger.warning(f"Agent {mission.assignee_id} not found, skipping enqueue")
            return None

        execution_id = await self._create_comment_execution(
            mission=mission,
            agent=agent,
            trigger_comment=trigger_comment,
            user_id=user_id,
        )
        if not execution_id:
            return None

        mission_for_update = await self.mission_repo.get_for_update(mission.id, mission.workspace_id)
        if mission_for_update:
            mission_for_update.current_execution_id = execution_id
            if mission_for_update.status != MissionStatus.IN_PROGRESS:
                mission_for_update.status = MissionStatus.IN_PROGRESS
            await self.db.commit()

        return execution_id

    async def dispatch_for_mention(
        self,
        *,
        mission: Mission,
        trigger_comment: Any,
        user_id: str,
    ) -> None:
        from app.utils.mentions import agent_mentions

        mentions = agent_mentions(trigger_comment.content)
        if not mentions:
            return
        if mission.status in {MissionStatus.DONE, MissionStatus.CANCELLED, MissionStatus.BACKLOG}:
            return

        seen: set[uuid.UUID] = set()
        for mention in mentions:
            if mention.id == mission.assignee_id or mention.id in seen:
                continue
            seen.add(mention.id)
            agent = await self.agent_repo.get_by_id_and_workspace(mention.id, mission.workspace_id)
            if not agent:
                continue
            await self._create_comment_execution(
                mission=mission,
                agent=agent,
                trigger_comment=trigger_comment,
                user_id=user_id,
            )

    async def _create_comment_execution(
        self,
        *,
        mission: Mission,
        agent: Any,
        trigger_comment: Any,
        user_id: str,
    ) -> Optional[uuid.UUID]:
        from sqlalchemy.exc import IntegrityError

        credentials = build_credentials(agent.custom_env)

        active_count_result = await self.db.execute(
            select(func.count())
            .select_from(ExecModel)
            .where(
                ExecModel.agent_profile_id == agent.id,
                ExecModel.status.in_(
                    [
                        MissionExecutionStatus.QUEUED,
                        MissionExecutionStatus.DISPATCHED,
                        MissionExecutionStatus.RUNNING,
                        MissionExecutionStatus.APPROVAL_WAIT,
                    ]
                ),
            )
        )
        active_count = active_count_result.scalar() or 0
        if active_count >= agent.max_concurrent_tasks:
            logger.info(
                f"Agent {agent.name} at concurrency limit ({active_count}/{agent.max_concurrent_tasks}), "
                f"skipping comment-triggered dispatch for mission {mission.id}"
            )
            return None

        try:
            execution = await self.execution_service.create_execution(
                workspace_id=mission.workspace_id,
                user_id=user_id,
                source=ExecutionSource.MISSION,
                runtime_type=agent.runtime_type,
                title=mission.title,
                mission_id=mission.id,
                agent_profile_id=agent.id,
                runtime_config=agent.runtime_config,
                trigger_comment_id=trigger_comment.id,
            )
        except IntegrityError:
            await self.db.rollback()
            logger.info(f"Dedup: skipped enqueue for agent {agent.id} on mission {mission.id}")
            return None

        prompt = build_execution_prompt(mission, trigger_comment=trigger_comment)
        _start_execution_runner(execution.id, prompt, credentials)
        return execution.id
