# backend/app/services/execution_lifecycle_service.py
"""
ExecutionLifecycleService — cross-domain coordinator between Task/AgentRun and Execution.

All operations that touch BOTH domains go through this service.
TaskService and ExecutionService remain single-domain and never import each other.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.agent.cli_backends.base import CLIResult
from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.core.agent.cli_backends.session_registry import session_registry
from app.models.agent import Agent, AgentRelease
from app.models.agent_run import AgentRun
from app.models.execution import Execution as ExecModel
from app.models.task import Task
from app.repositories.agent import AgentRepository
from app.repositories.task import TaskRepository
from app.services.execution_service import ExecutionService, TERMINAL_EXECUTION_STATUSES
from app.utils.credentials import build_credentials
from app.utils.datetime import utc_now
from app.utils.safe_task import safe_create_task


def build_task_prompt(task: Task, trigger_comment: Any = None) -> str:
    """Build the prompt sent to the CLI agent for a task."""
    parts: list[str] = []
    parts.append(f"# Task: {task.title}")
    if task.description:
        parts.append(f"\n## Description\n{task.description}")
    if task.goal:
        parts.append(f"\n## Goal\n{task.goal}")
    if task.tags:
        parts.append(f"\n## Tags\n{', '.join(str(t) for t in task.tags)}")
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
    """Mediator: coordinates Task/AgentRun <-> Execution interactions.

    Implements RunnerCallbacks so it can be injected into ExecutionRunner.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.execution_service = ExecutionService(db)
        self.task_repo = TaskRepository(db)
        self.agent_repo = AgentRepository(db)

    # ------------------------------------------------------------------
    # RunnerCallbacks implementation
    # ------------------------------------------------------------------

    async def on_execution_finalized(
        self,
        execution_id: uuid.UUID,
        status: str,
        result: CLIResult,
    ) -> None:
        """Called by ExecutionRunner after terminal state reached."""
        await self._post_completion_comment(execution_id, status, result)
        await self._finalize_task(execution_id, status)

    async def on_execution_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
    ) -> None:
        """Called by ExecutionRunner on unhandled exception."""
        await self._post_completion_comment(
            execution_id,
            "failed",
            error_message=error,
        )
        await self._finalize_task(execution_id, "failed")

    # ------------------------------------------------------------------
    # Finalize: update run + task status after execution ends
    # ------------------------------------------------------------------

    async def _finalize_task(
        self,
        execution_id: uuid.UUID,
        status: str,
    ) -> None:
        try:
            result = await self.db.execute(
                select(ExecModel).where(ExecModel.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            if not execution:
                return

            run_result = await self.db.execute(
                select(AgentRun).where(AgentRun.id == execution.run_id).with_for_update()
            )
            run = run_result.scalar_one_or_none()
            if not run:
                return

            # Map execution status → run status
            if status == "completed":
                run.status = "succeeded"
            elif status == "failed":
                run.status = "failed"
            elif status == "cancelled":
                run.status = "cancelled"
            run.ended_at = utc_now()

            # Sync task status if task exists
            if run.task_id:
                from app.services.task_service import TaskService

                task_result = await self.db.execute(
                    select(Task).where(Task.id == run.task_id)
                )
                task = task_result.scalar_one_or_none()
                if task:
                    task_service = TaskService(self.db)
                    await task_service.sync_status_from_run(run.task_id, task.workspace_id, run)

            await self.db.commit()

            logger.info(
                f"Finalized run {run.id}: execution {execution_id} -> run status {run.status}"
            )
        except Exception as exc:
            logger.warning(f"Failed to finalize task for execution {execution_id}: {exc}")

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
            status="cancelled",
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

        if execution:
            await self._finalize_task(execution_id, "cancelled")

        return execution

    async def _destroy_execution_container(self, execution: Any) -> None:
        """Release this execution's container; destroy it if no other execution is using it."""
        from app.core.agent.cli_backends.container_pool import container_pool
        from app.core.agent.cli_backends.container_service import CLIContainerService

        # Try to find the release_id via run → release chain
        release_id: Optional[uuid.UUID] = None
        if execution.run_id:
            try:
                run_result = await self.db.execute(
                    select(AgentRun).where(AgentRun.id == execution.run_id)
                )
                run = run_result.scalar_one_or_none()
                if run:
                    release_id = run.release_id
            except Exception:
                pass

        if release_id:
            try:
                destroyed = await container_pool.release_and_destroy_if_idle(release_id)
                if destroyed:
                    logger.info(
                        f"Destroyed container for release {release_id} (execution {execution.id})"
                    )
                else:
                    logger.info(
                        f"Released container for release {release_id} "
                        f"(execution {execution.id}, still in use by other executions)"
                    )
                return
            except Exception as exc:
                logger.warning(f"Failed to release/destroy container for release {release_id}: {exc}")

        # No release — remove by runtime_session_ref (container_id) directly
        if execution.runtime_session_ref:
            try:
                svc = CLIContainerService()
                await svc.remove_container(execution.runtime_session_ref, force=True)
                logger.info(f"Removed container {execution.runtime_session_ref[:12]} for execution {execution.id}")
            except Exception as exc:
                logger.warning(f"Failed to remove container for execution {execution.id}: {exc}")

    async def cancel_task(
        self,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Optional[Task]:
        task = await self.task_repo.get_for_update(task_id, workspace_id)
        if not task:
            return None

        # Cancel the latest active run if any
        if task.latest_run_id:
            run_result = await self.db.execute(
                select(AgentRun).where(AgentRun.id == task.latest_run_id).with_for_update()
            )
            run = run_result.scalar_one_or_none()
            if run and run.current_execution_id and run.status not in ("succeeded", "failed", "cancelled"):
                exec_id = run.current_execution_id
                try:
                    await self.execution_service.mark_status(
                        execution_id=exec_id,
                        status="cancelled",
                        error_code="cancelled",
                        error_message="Task cancelled by user",
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

                execution = await self.execution_service.get_execution_internal(exec_id)
                if execution:
                    await self._destroy_execution_container(execution)

                run.status = "cancelled"
                run.ended_at = utc_now()

        from app.models.task import TaskStatus
        task.status = TaskStatus.CANCELLED
        await self.db.commit()
        await self.db.refresh(task)

        return task

    # ------------------------------------------------------------------
    # Auto-comment on execution completion
    # ------------------------------------------------------------------

    async def _post_completion_comment(
        self,
        execution_id: uuid.UUID,
        status: str,
        result: Optional[CLIResult] = None,
        error_message: str = "",
    ) -> None:
        """Post a comment on the task after execution completes (if task has comments)."""
        try:
            execution = await self.execution_service.get_execution_internal(execution_id)
            if not execution:
                return

            # Resolve task via run
            run_result = await self.db.execute(
                select(AgentRun).where(AgentRun.id == execution.run_id)
            )
            run = run_result.scalar_one_or_none()
            if not run or not run.task_id:
                return

            # Post comment via task comment service if available
            try:
                from app.services.task_activity_service import TaskActivityService

                svc = TaskActivityService(self.db)
                await svc.post_execution_activity(
                    execution=execution,
                    task_id=run.task_id,
                    result_status=status,
                    result_output=(result.output[:2000] if result and result.output else ""),
                    error_message=error_message[:2000] if error_message else "",
                )
            except ImportError:
                pass  # task_activity_service may not exist yet
        except Exception as exc:
            logger.warning(f"Failed to post completion comment for {execution_id}: {exc}")

    # ------------------------------------------------------------------
    # Dispatch: create run + execution + start runner
    # ------------------------------------------------------------------

    async def dispatch_task(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: str,
    ) -> tuple[Task, AgentRun]:
        task = await self.task_repo.get_for_update(task_id, workspace_id)
        if not task:
            raise NotFoundException(f"Task not found: {task_id}")

        if not task.agent_id:
            raise BadRequestException(f"Task {task_id} has no assigned agent")

        # Load agent and its active release
        agent_result = await self.db.execute(
            select(Agent).where(Agent.id == task.agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise NotFoundException(f"Agent not found: {task.agent_id}")
        if not agent.active_release_id:
            raise BadRequestException(f"Agent {agent.id} has no active release")

        release_result = await self.db.execute(
            select(AgentRelease).where(AgentRelease.id == agent.active_release_id)
        )
        release = release_result.scalar_one_or_none()
        if not release:
            raise NotFoundException(f"AgentRelease not found: {agent.active_release_id}")

        # Build credentials from release runtime_binding
        custom_env = release.runtime_binding.get("custom_env", {})
        credentials = build_credentials(custom_env)
        prompt = build_task_prompt(task)

        # Create run + execution via AgentRunService
        from app.schemas.agent_run import CreateAgentRunRequest
        from app.services.agent_run_service import AgentRunService

        run_service = AgentRunService(self.db)
        run_data = CreateAgentRunRequest(
            release_id=agent.active_release_id,
            task_id=task_id,
            trigger_source="task",
            goal=task.goal or task.title,
        )
        run = await run_service.create_run(user_id, run_data)

        # Update task status to in_progress
        from app.models.task import TaskStatus
        task.status = TaskStatus.IN_PROGRESS
        task.latest_run_id = run.id
        await self.db.commit()
        await self.db.refresh(task)

        logger.info(f"Dispatched task {task_id} -> run {run.id} -> execution {run.current_execution_id}")

        _start_execution_runner(run.current_execution_id, prompt, credentials)
        return task, run

    async def dispatch_all_ready_tasks(self, *, limit: int = 20) -> int:
        """Dispatch all BACKLOG tasks that have an agent assigned."""
        dispatchable = await self.task_repo.list_dispatchable(limit=limit)
        dispatched = 0
        for task in dispatchable:
            try:
                await self.dispatch_task(
                    task_id=task.id,
                    workspace_id=task.workspace_id,
                    user_id=task.creator_id,
                )
                dispatched += 1
            except Exception as exc:
                logger.warning(f"Failed to auto-dispatch task {task.id}: {exc}")
        return dispatched

    async def dispatch_for_comment(
        self,
        *,
        task: Task,
        trigger_comment: Any,
        user_id: str,
    ) -> Optional[uuid.UUID]:
        """Dispatch a task execution triggered by a comment."""
        if not task.agent_id:
            logger.warning(f"Task {task.id} has no agent, skipping comment dispatch")
            return None

        # Load agent and release
        agent_result = await self.db.execute(
            select(Agent).where(Agent.id == task.agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent or not agent.active_release_id:
            logger.warning(f"Agent {task.agent_id} not found or has no active release, skipping dispatch")
            return None

        release_result = await self.db.execute(
            select(AgentRelease).where(AgentRelease.id == agent.active_release_id)
        )
        release = release_result.scalar_one_or_none()
        if not release:
            return None

        # Create run + execution
        from app.schemas.agent_run import CreateAgentRunRequest
        from app.services.agent_run_service import AgentRunService

        run_service = AgentRunService(self.db)
        run_data = CreateAgentRunRequest(
            release_id=agent.active_release_id,
            task_id=task.id,
            trigger_source="comment",
            goal=task.goal or task.title,
        )
        run = await run_service.create_run(user_id, run_data)

        # Update task
        from app.models.task import TaskStatus
        if task.status != TaskStatus.IN_PROGRESS:
            task.status = TaskStatus.IN_PROGRESS
        task.latest_run_id = run.id
        await self.db.commit()

        # Build prompt and credentials
        custom_env = release.runtime_binding.get("custom_env", {})
        credentials = build_credentials(custom_env)
        prompt = build_task_prompt(task, trigger_comment=trigger_comment)

        _start_execution_runner(run.current_execution_id, prompt, credentials)
        return run.current_execution_id

    async def dispatch_for_mention(
        self,
        *,
        task: Task,
        trigger_comment: Any,
        user_id: str,
    ) -> None:
        """Dispatch executions for all agents mentioned in a comment (excluding the assigned agent)."""
        from app.utils.mentions import agent_mentions

        mentions = agent_mentions(trigger_comment.content)
        if not mentions:
            return

        from app.models.task import TaskStatus
        if task.status in {TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.BACKLOG}:
            return

        seen: set[uuid.UUID] = set()
        for mention in mentions:
            if mention.id == task.agent_id or mention.id in seen:
                continue
            seen.add(mention.id)

            # Load mentioned agent
            agent_result = await self.db.execute(
                select(Agent).where(Agent.id == mention.id)
            )
            agent = agent_result.scalar_one_or_none()
            if not agent or not agent.active_release_id:
                continue

            release_result = await self.db.execute(
                select(AgentRelease).where(AgentRelease.id == agent.active_release_id)
            )
            release = release_result.scalar_one_or_none()
            if not release:
                continue

            # Create run for mentioned agent
            from app.schemas.agent_run import CreateAgentRunRequest
            from app.services.agent_run_service import AgentRunService

            run_service = AgentRunService(self.db)
            run_data = CreateAgentRunRequest(
                release_id=agent.active_release_id,
                task_id=task.id,
                trigger_source="mention",
                goal=task.goal or task.title,
            )
            try:
                run = await run_service.create_run(user_id, run_data)

                # Build prompt and credentials
                custom_env = release.runtime_binding.get("custom_env", {})
                credentials = build_credentials(custom_env)
                prompt = build_task_prompt(task, trigger_comment=trigger_comment)

                _start_execution_runner(run.current_execution_id, prompt, credentials)
            except Exception as exc:
                logger.warning(f"Failed to dispatch mention for agent {agent.id} on task {task.id}: {exc}")
