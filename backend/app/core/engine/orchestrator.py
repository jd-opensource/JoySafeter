"""
Execution Orchestrator — the single entry point for all execution dispatch.

Layer 2: sits between API/triggers (Layer 1) and engines (Layer 3).
Creates AgentRun + Execution, resolves the engine, builds context, fires.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.engine.protocol import ExecutionContext
from app.core.engine.registry import engine_registry
from app.models.agent import Agent, AgentRelease, AgentVersion
from app.models.agent_run import AgentRun
from app.models.execution import Execution, ExecutionEvent
from app.models.task import Task
from app.models.thread import Thread
from app.utils.credentials import build_credentials
from app.utils.datetime import utc_now
from app.utils.safe_task import safe_create_task


class ExecutionOrchestrator:
    """
    Unified dispatch: trigger → Run → Engine → Events.

    All entry points (Task dispatch, Chat, API, Scheduler) go through here.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Public dispatch methods (Layer 1 calls these)
    # ------------------------------------------------------------------

    async def dispatch_task(
        self,
        task_id: uuid.UUID,
        user_id: str,
        prompt_override: str | None = None,
    ) -> AgentRun:
        """Dispatch a Task → creates Run + Execution, fires engine."""
        task = await self._get_task(task_id)
        if task.status == "in_progress" and task.latest_run_id:
            raise BadRequestException("Task already has an active run. Cancel it first.")
        if not task.agent_id:
            raise BadRequestException("Task has no assigned agent")

        agent = await self._get_agent(task.agent_id)
        if not agent.active_release_id:
            raise BadRequestException(f"Agent '{agent.name}' has no active release")

        prompt = prompt_override or task.goal or task.title
        run = await self._create_and_fire(
            release_id=agent.active_release_id,
            workspace_id=agent.workspace_id,
            prompt=prompt,
            trigger_source="task",
            task_id=task_id,
            user_id=user_id,
        )

        # Update task status
        task.status = "in_progress"
        task.latest_run_id = run.id
        await self.db.commit()

        return run

    async def dispatch_chat(
        self,
        thread_id: uuid.UUID,
        message: str,
        user_id: str,
    ) -> AgentRun:
        """Dispatch from a Thread conversation → creates Run + Execution."""
        thread = (await self.db.execute(
            select(Thread).where(Thread.id == thread_id)
        )).scalar_one_or_none()
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")

        agent = await self._get_agent(thread.agent_id)
        if not agent.active_release_id:
            raise BadRequestException(f"Agent '{agent.name}' has no active release")

        return await self._create_and_fire(
            release_id=agent.active_release_id,
            workspace_id=agent.workspace_id,
            prompt=message,
            trigger_source="chat",
            thread_id=thread_id,
            user_id=user_id,
        )

    async def dispatch_direct(
        self,
        release_id: uuid.UUID,
        prompt: str,
        user_id: str,
        trigger_source: str = "api",
        thread_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        input_payload: dict | None = None,
    ) -> AgentRun:
        """Direct dispatch with explicit release_id (API / Scheduler)."""
        release = await self._get_release(release_id)
        version = await self._get_version(release.agent_version_id)
        agent = await self._get_agent(version.agent_id)

        return await self._create_and_fire(
            release_id=release_id,
            workspace_id=agent.workspace_id,
            prompt=prompt,
            trigger_source=trigger_source,
            thread_id=thread_id,
            task_id=task_id,
            user_id=user_id,
            input_payload=input_payload,
        )

    # ------------------------------------------------------------------
    # Cancel / Retry / Message
    # ------------------------------------------------------------------

    async def cancel_run(self, run_id: uuid.UUID) -> AgentRun:
        """Cancel a running execution."""
        run = await self._get_run(run_id)
        if run.status in ("succeeded", "failed", "cancelled"):
            raise BadRequestException(f"Cannot cancel run in status {run.status}")

        if run.current_execution_id:
            execution = (await self.db.execute(
                select(Execution).where(Execution.id == run.current_execution_id)
            )).scalar_one_or_none()
            if execution:
                release = await self._get_release(run.release_id)
                engine = engine_registry.get(release.runtime_kind)
                await engine.cancel(execution.id)
                execution.status = "cancelled"
                execution.ended_at = utc_now()

        run.status = "cancelled"
        run.ended_at = utc_now()
        await self.db.commit()
        await self.db.refresh(run)

        await self._sync_task_status(run)
        return run

    async def retry_run(self, run_id: uuid.UUID, user_id: str) -> AgentRun:
        """Retry a failed/cancelled run with a new Execution attempt."""
        run = await self._get_run(run_id)
        if run.status not in ("failed", "cancelled"):
            raise BadRequestException("Can only retry failed or cancelled runs")

        release = await self._get_release(run.release_id)
        version = await self._get_version(release.agent_version_id)

        # Create new execution attempt
        from sqlalchemy import func
        max_attempt = (await self.db.execute(
            select(func.coalesce(func.max(Execution.attempt_index), 0))
            .where(Execution.run_id == run_id)
        )).scalar()

        execution = Execution(
            run_id=run_id,
            attempt_index=max_attempt + 1,
            executor_kind=release.runtime_binding.get("runtime_type", "claude_code"),
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()

        run.current_execution_id = execution.id
        run.status = "running"
        run.ended_at = None
        await self.db.commit()

        # Fire engine in background
        await self._fire_engine(
            execution=execution,
            release=release,
            version=version,
            workspace_id=run.workspace_id,
            prompt=run.goal or "",
        )

        await self.db.refresh(run)
        return run

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        """Inject a message into a running execution."""
        execution = (await self.db.execute(
            select(Execution).where(Execution.id == execution_id)
        )).scalar_one_or_none()
        if not execution:
            raise NotFoundException(f"Execution {execution_id} not found")

        run = await self._get_run(execution.run_id)
        release = await self._get_release(run.release_id)
        engine = engine_registry.get(release.runtime_kind)
        await engine.send_message(execution_id, message)

    # ------------------------------------------------------------------
    # Internal: create Run + Execution, fire engine
    # ------------------------------------------------------------------

    async def _create_and_fire(
        self,
        release_id: uuid.UUID,
        workspace_id: uuid.UUID,
        prompt: str,
        trigger_source: str,
        user_id: str,
        thread_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        input_payload: dict | None = None,
    ) -> AgentRun:
        release = await self._get_release(release_id)
        version = await self._get_version(release.agent_version_id)

        # Create Run
        run = AgentRun(
            release_id=release_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            task_id=task_id,
            trigger_source=trigger_source,
            goal=prompt[:500] if prompt else None,
            input_payload=input_payload,
            status="running",
            created_by=user_id,
            started_at=utc_now(),
        )
        self.db.add(run)
        await self.db.flush()

        # Create initial Execution
        execution = Execution(
            run_id=run.id,
            attempt_index=1,
            executor_kind=release.runtime_binding.get("runtime_type", "claude_code"),
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()

        run.current_execution_id = execution.id
        await self.db.commit()
        await self.db.refresh(run)

        # Fire engine in background
        try:
            await self._fire_engine(
                execution=execution,
                release=release,
                version=version,
                workspace_id=workspace_id,
                prompt=prompt,
            )
        except Exception as exc:
            logger.error(f"[Orchestrator] _fire_engine failed: {exc}")
            run.status = "failed"
            run.ended_at = utc_now()
            execution.status = "failed"
            execution.ended_at = utc_now()
            await self.db.commit()
            await self.db.refresh(run)

        return run

    async def _fire_engine(
        self,
        execution: Execution,
        release: AgentRelease,
        version: AgentVersion,
        workspace_id: uuid.UUID,
        prompt: str,
    ) -> None:
        """Build context and fire engine in a background task."""
        credentials = await build_credentials(self.db, workspace_id)

        # Resolve auto_approve from task if linked
        auto_approve = True
        run = (await self.db.execute(
            select(AgentRun).where(AgentRun.id == execution.run_id)
        )).scalar_one()
        if run.task_id:
            task = (await self.db.execute(
                select(Task).where(Task.id == run.task_id)
            )).scalar_one_or_none()
            if task:
                auto_approve = task.auto_approve

        context = ExecutionContext(
            db=self.db,
            execution_id=execution.id,
            run_id=run.id,
            workspace_id=workspace_id,
            credentials=credentials,
            auto_approve=auto_approve,
        )

        # Wire context callbacks
        self._wire_context(context)

        engine = engine_registry.get(release.runtime_kind)

        async def _run_engine():
            from app.core.database import AsyncSessionLocal
            try:
                async with AsyncSessionLocal() as db:
                    # Rebuild context with fresh session
                    ctx = ExecutionContext(
                        db=db,
                        execution_id=execution.id,
                        run_id=run.id,
                        workspace_id=workspace_id,
                        credentials=credentials,
                        auto_approve=auto_approve,
                    )
                    self._wire_context(ctx)

                    await engine.start(
                        ctx,
                        release_runtime_binding=release.runtime_binding,
                        definition_kind=version.definition_kind,
                        definition_payload=version.definition_payload,
                        prompt=prompt,
                    )
            except Exception as exc:
                logger.error(f"[Orchestrator] Engine failed for execution {execution.id}: {exc}")
                try:
                    await ctx._complete_fn("failed", f"Engine error: {str(exc)[:2000]}")
                except Exception as cleanup_exc:
                    logger.error(f"[Orchestrator] Failed to mark execution as failed: {cleanup_exc}")

        safe_create_task(_run_engine(), name=f"engine-{execution.id}")

    def _wire_context(self, ctx: ExecutionContext) -> None:
        """Attach emit/status/complete callbacks to context."""

        async def _emit(event_type: str, payload: dict) -> None:
            from sqlalchemy import func, select as sa_select
            max_seq = (await ctx.db.execute(
                sa_select(func.coalesce(func.max(ExecutionEvent.sequence_no), 0))
                .where(ExecutionEvent.execution_id == ctx.execution_id)
            )).scalar()

            event = ExecutionEvent(
                execution_id=ctx.execution_id,
                sequence_no=max_seq + 1,
                event_type=event_type,
                payload=payload,
            )
            ctx.db.add(event)
            await ctx.db.commit()

            # Broadcast via WebSocket
            from app.websocket.execution_subscription_manager import execution_subscription_manager
            await execution_subscription_manager.broadcast_event(str(ctx.execution_id), {
                "type": "event",
                "execution_id": str(ctx.execution_id),
                "seq": event.sequence_no,
                "event_type": event_type,
                "data": payload,
            })

        async def _status(status: str) -> None:
            execution = (await ctx.db.execute(
                select(Execution).where(Execution.id == ctx.execution_id)
            )).scalar_one()
            execution.status = status
            if status == "running" and not execution.started_at:
                execution.started_at = utc_now()
            await ctx.db.commit()

        async def _complete(status: str, result_summary: str | None = None) -> None:
            # Update Execution
            execution = (await ctx.db.execute(
                select(Execution).where(Execution.id == ctx.execution_id)
            )).scalar_one()
            execution.status = status
            execution.ended_at = utc_now()
            await ctx.db.commit()

            # Update Run
            run = (await ctx.db.execute(
                select(AgentRun).where(AgentRun.id == ctx.run_id)
            )).scalar_one()
            run.status = status
            run.result_summary = result_summary
            run.ended_at = utc_now()
            await ctx.db.commit()

            # Sync Task status
            await self._sync_task_status(run, db=ctx.db)

            # Broadcast
            from app.websocket.execution_subscription_manager import execution_subscription_manager
            await execution_subscription_manager.broadcast_event(str(ctx.execution_id), {
                "type": "execution_completed",
                "execution_id": str(ctx.execution_id),
                "run_id": str(ctx.run_id),
                "status": status,
            })

        ctx._emit_fn = _emit
        ctx._status_fn = _status
        ctx._complete_fn = _complete

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    async def _sync_task_status(self, run: AgentRun, db: AsyncSession | None = None) -> None:
        """Sync Task status from Run status."""
        if not run.task_id:
            return
        session = db or self.db
        task = (await session.execute(
            select(Task).where(Task.id == run.task_id)
        )).scalar_one_or_none()
        if not task:
            return

        if run.status == "succeeded":
            task.status = "done"
        elif run.status == "failed":
            task.status = "in_review"
        elif run.status == "cancelled":
            task.status = "backlog"
        elif run.status in ("queued", "running"):
            task.status = "in_progress"

        task.latest_run_id = run.id
        await session.commit()

    async def _get_task(self, task_id: uuid.UUID) -> Task:
        result = (await self.db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not result:
            raise NotFoundException(f"Task {task_id} not found")
        return result

    async def _get_agent(self, agent_id: uuid.UUID) -> Agent:
        result = (await self.db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if not result:
            raise NotFoundException(f"Agent {agent_id} not found")
        return result

    async def _get_release(self, release_id: uuid.UUID) -> AgentRelease:
        result = (await self.db.execute(select(AgentRelease).where(AgentRelease.id == release_id))).scalar_one_or_none()
        if not result:
            raise NotFoundException(f"AgentRelease {release_id} not found")
        return result

    async def _get_version(self, version_id: uuid.UUID) -> AgentVersion:
        result = (await self.db.execute(select(AgentVersion).where(AgentVersion.id == version_id))).scalar_one_or_none()
        if not result:
            raise NotFoundException(f"AgentVersion {version_id} not found")
        return result

    async def _get_run(self, run_id: uuid.UUID) -> AgentRun:
        result = (await self.db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
        if not result:
            raise NotFoundException(f"AgentRun {run_id} not found")
        return result
