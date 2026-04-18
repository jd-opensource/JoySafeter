# backend/app/services/execution_lifecycle_service.py
"""
ExecutionLifecycleService — the sole cross-domain coordinator
between Mission and Execution.

All operations that touch BOTH domains go through this service.
MissionService and ExecutionService remain single-domain and
never import each other.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.cli_backends.base import CLIResult
from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.core.agent.cli_backends.session_registry import session_registry
from app.models.execution import (
    ExecutionSource,
    MissionExecutionStatus,
    TERMINAL_EXECUTION_STATUSES,
)
from app.models.mission import AssigneeType, Mission, MissionStatus
from app.repositories.agent_profile import AgentProfileRepository
from app.repositories.mission import MissionRepository
from app.services.execution_service import ExecutionService


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
        from sqlalchemy import select

        try:
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
                    mission.status = (
                        MissionStatus.DONE if mission.auto_approve
                        else MissionStatus.IN_REVIEW
                    )
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
            await notification_manager.broadcast({
                "type": NotificationType.MISSION_UPDATED.value,
                "mission_id": str(mission.id),
                "status": mission.status.value,
            })

            logger.info(
                f"Finalized mission {mission.id}: execution {execution_id} "
                f"-> mission status {mission.status.value}"
            )
        except Exception as exc:
            logger.warning(
                f"Failed to finalize mission for execution {execution_id}: {exc}"
            )

    # ------------------------------------------------------------------
    # Cancel: unified cancel path
    # ------------------------------------------------------------------

    async def cancel_execution(
        self,
        execution_id: uuid.UUID,
        user_id: str,
    ) -> Any:
        execution = await self.execution_service.get_execution(
            execution_id, user_id
        )
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

        if execution.mission_id:
            await self._finalize_mission(
                execution_id, MissionExecutionStatus.CANCELLED
            )

        return execution

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

        mission.status = MissionStatus.CANCELLED
        mission.current_execution_id = None
        await self.db.commit()
        await self.db.refresh(mission)

        from app.websocket.notification_manager import (
            NotificationType,
            notification_manager,
        )
        await notification_manager.broadcast({
            "type": NotificationType.MISSION_UPDATED.value,
            "mission_id": str(mission.id),
            "status": mission.status.value,
        })

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
            execution = await self.execution_service.get_execution_internal(
                execution_id
            )
            if not execution or not execution.mission_id:
                return
            from app.services.mission_comment_service import MissionCommentService
            svc = MissionCommentService(self.db)
            await svc.post_execution_comment(
                execution=execution,
                result_status=status,
                result_output=(
                    result.output[:2000] if result and result.output else ""
                ),
                error_message=error_message[:2000] if error_message else "",
            )
        except Exception as exc:
            logger.warning(
                f"Failed to post completion comment for {execution_id}: {exc}"
            )
