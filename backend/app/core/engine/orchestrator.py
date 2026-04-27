"""
Execution Orchestrator — the single entry point for all execution dispatch.

Layer 2: sits between API/triggers (Layer 1) and engines (Layer 3).
Creates AgentRun + Execution, resolves the engine, builds context, fires.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.engine.protocol import ExecutionContext
from app.core.engine.registry import engine_registry
from app.core.events import ExecutionEventEnvelope, execution_event_bus
from app.core.events.event_types import ExecutionEventType
from app.core.state_machines.transitions import transition_task
from app.models.agent import Agent, AgentRelease, AgentVersion
from app.models.agent_run import AgentRun
from app.models.execution import Execution
from app.models.task import Task
from app.models.thread import Thread
from app.utils.credentials import build_agent_credentials
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

    # Statuses from which a task may be dispatched (besides in_progress for re-fire).
    DISPATCHABLE_STATUSES = {"backlog", "todo", "in_review"}

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
        if task.status not in self.DISPATCHABLE_STATUSES and task.status != "in_progress":
            raise BadRequestException(
                f"Cannot dispatch task in '{task.status}' status. "
                "Move the task back to backlog first."
            )
        if not task.agent_id:
            raise BadRequestException("Task has no assigned agent")

        agent = await self._get_agent(task.agent_id)
        if not agent.active_release_id:
            raise BadRequestException(f"Agent '{agent.name}' has no active release")

        prompt = prompt_override or task.goal or task.title
        run = await self._create_and_fire(
            agent=agent,
            release_id=agent.active_release_id,
            workspace_id=agent.workspace_id,
            prompt=prompt,
            trigger_source="task",
            task_id=task_id,
            user_id=user_id,
        )

        # Update task status
        await transition_task(task, "in_progress", self.db, latest_run_id=run.id)
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
            agent=agent,
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
            agent=agent,
            release_id=release_id,
            workspace_id=agent.workspace_id,
            prompt=prompt,
            trigger_source=trigger_source,
            thread_id=thread_id,
            task_id=task_id,
            user_id=user_id,
            input_payload=input_payload,
        )

    async def dispatch_draft(
        self,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        prompt: str,
        user_id: str,
        workspace_id: uuid.UUID,
        input_payload: dict | None = None,
    ) -> AgentRun:
        """Dispatch a Test Lab run against a draft AgentVersion."""
        version = await self._get_version(version_id)
        if version.agent_id != agent_id:
            raise BadRequestException("Version does not belong to this agent")

        agent = await self._get_agent(agent_id)
        if agent.workspace_id != workspace_id:
            raise BadRequestException("Agent does not belong to this workspace")

        return await self._create_and_fire_draft(
            agent=agent,
            version=version,
            workspace_id=workspace_id,
            prompt=prompt,
            trigger_source="draft_test",
            user_id=user_id,
            input_payload=input_payload,
        )

    async def dispatch_copilot(
        self,
        agent_id: uuid.UUID,
        prompt: str,
        user_id: str,
        graph_context: dict,
        conversation_history: list | None = None,
        mode: str = "deepagents",
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> AgentRun:
        """Dispatch a copilot interaction through the execution engine.

        Creates an AgentRun + Execution for the copilot session so that
        copilot events are persisted as ExecutionEvents and broadcast
        via WebSocket.
        """
        agent = await self._get_agent(agent_id)
        if not agent.active_release_id:
            raise BadRequestException(
                f"Agent '{agent.name}' has no active release. "
                "Publish a release first to use persistent copilot history."
            )

        copilot_payload = {
            "graph_context": graph_context,
            "conversation_history": conversation_history,
            "mode": mode,
            "provider_name": provider_name,
            "model_name": model_name,
            "user_id": user_id,
            "graph_id": str(agent_id),
        }

        return await self._create_and_fire(
            agent=agent,
            release_id=agent.active_release_id,
            workspace_id=agent.workspace_id,
            prompt=prompt,
            trigger_source="copilot",
            user_id=user_id,
            input_payload=copilot_payload,
            engine_kind_override="copilot",
            definition_kind_override="copilot",
            definition_payload_override=copilot_payload,
            executor_kind_override="copilot",
        )

    def _resolve_engine(self, execution: Execution, release: AgentRelease):
        """Resolve the correct engine for an execution.

        Uses executor_kind if it maps to a registered engine (e.g., "copilot"),
        otherwise falls back to release.runtime_kind.
        """
        if execution.executor_kind and engine_registry.has(execution.executor_kind):
            return engine_registry.get(execution.executor_kind)
        return engine_registry.get(release.runtime_kind)

    def _resolve_draft_engine_kind(self, version: AgentVersion) -> str:
        if version.definition_kind == "graph":
            return "graph"
        if version.definition_kind == "code":
            return "code"
        raise BadRequestException(
            f"Draft Test Lab does not support definition_kind={version.definition_kind}"
        )

    def _build_draft_runtime_binding(self, version: AgentVersion) -> dict:
        if version.definition_kind == "graph":
            return {"runtime_type": "graph"}
        if version.definition_kind == "code":
            return {"runtime_type": "code"}
        return {}

    # ------------------------------------------------------------------
    # Cancel / Retry / Message / Event helpers
    # ------------------------------------------------------------------

    async def emit_user_message(
        self,
        *,
        run: AgentRun,
        execution_id: uuid.UUID,
        message: str,
        attachments: list[dict] | None = None,
    ) -> None:
        """Emit a USER_MESSAGE event for the given execution."""
        payload: dict = {"text": message}
        if attachments:
            payload["attachments"] = attachments

        envelope = ExecutionEventEnvelope(
            execution_id=execution_id,
            run_id=run.id,
            workspace_id=run.workspace_id,
            event_type=ExecutionEventType.USER_MESSAGE,
            payload=payload,
            trigger_source=run.trigger_source,
            thread_id=run.thread_id,
            task_id=run.task_id,
        )
        await execution_event_bus.publish(envelope, self.db)

    async def cancel_run(self, run_id: uuid.UUID) -> AgentRun:
        """Cancel a running execution."""
        run = await self._get_run(run_id)
        if run.status in ("succeeded", "failed", "cancelled"):
            raise BadRequestException(f"Cannot cancel run in status {run.status}")

        execution_id = run.current_execution_id or uuid.UUID(int=0)

        if run.current_execution_id:
            execution = (await self.db.execute(
                select(Execution).where(Execution.id == run.current_execution_id)
            )).scalar_one_or_none()
            if execution:
                if run.release_id:
                    release = await self._get_release(run.release_id)
                    engine = self._resolve_engine(execution, release)
                elif run.agent_version_id:
                    version = await self._get_version(run.agent_version_id)
                    engine = engine_registry.get(self._resolve_draft_engine_kind(version))
                else:
                    raise BadRequestException("Run has neither release_id nor agent_version_id")
                await engine.cancel(execution.id)

        await execution_event_bus.publish(
            ExecutionEventEnvelope(
                execution_id=execution_id,
                run_id=run.id,
                workspace_id=run.workspace_id,
                event_type=ExecutionEventType.EXECUTION_COMPLETED,
                payload={"status": "cancelled"},
                terminal_status="cancelled",
            ),
            self.db,
        )
        await self.db.refresh(run)
        return run

    async def retry_run(self, run_id: uuid.UUID, user_id: str) -> AgentRun:
        """Retry a failed/cancelled run with a new Execution attempt."""
        run = await self._get_run(run_id)
        if run.status not in ("failed", "cancelled"):
            raise BadRequestException("Can only retry failed or cancelled runs")
        if not run.release_id:
            raise BadRequestException("Draft Test Lab runs cannot be retried")

        release = await self._get_release(run.release_id)
        version = await self._get_version(release.agent_version_id)
        agent = await self._get_agent(version.agent_id)

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
        await self.db.flush()

        await self.publish_run_status_change(
            self.db, run,
            execution_id=execution.id,
            target_status="running",
        )
        await self.db.commit()

        # Fire engine in background
        await self._fire_engine(
            execution=execution,
            release=release,
            version=version,
            agent=agent,
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
        if run.release_id:
            release = await self._get_release(run.release_id)
            engine = self._resolve_engine(execution, release)
        elif run.agent_version_id:
            version = await self._get_version(run.agent_version_id)
            engine = engine_registry.get(self._resolve_draft_engine_kind(version))
        else:
            raise BadRequestException("Run has neither release_id nor agent_version_id")
        await engine.send_message(execution_id, message)

    # ------------------------------------------------------------------
    # Internal: create Run + Execution, fire engine
    # ------------------------------------------------------------------

    async def _create_and_fire(
        self,
        agent: Agent,
        release_id: uuid.UUID,
        workspace_id: uuid.UUID,
        prompt: str,
        trigger_source: str,
        user_id: str,
        thread_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        input_payload: dict | None = None,
        *,
        engine_kind_override: str | None = None,
        definition_kind_override: str | None = None,
        definition_payload_override: dict | None = None,
        executor_kind_override: str | None = None,
    ) -> AgentRun:
        release = await self._get_release(release_id)
        version = await self._get_version(release.agent_version_id)

        # Create Run in pending state — bus will transition to running
        run = AgentRun(
            release_id=release_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            task_id=task_id,
            trigger_source=trigger_source,
            goal=prompt[:500] if prompt else None,
            input_payload=input_payload,
            status="pending",
            created_by=user_id,
        )
        self.db.add(run)
        await self.db.flush()

        execution = Execution(
            run_id=run.id,
            attempt_index=1,
            executor_kind=executor_kind_override or release.runtime_binding.get("runtime_type", "claude_code"),
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()

        run.current_execution_id = execution.id
        await self.db.commit()

        await self.publish_run_status_change(
            self.db, run,
            execution_id=execution.id,
            target_status="running",
        )
        await self.db.refresh(run)

        # Fire engine in background
        try:
            await self._fire_engine(
                execution=execution,
                release=release,
                version=version,
                agent=agent,
                workspace_id=workspace_id,
                prompt=prompt,
                engine_kind_override=engine_kind_override,
                definition_kind_override=definition_kind_override,
                definition_payload_override=definition_payload_override,
            )
        except Exception as exc:
            logger.error(f"[Orchestrator] _fire_engine failed: {exc}")
            await execution_event_bus.publish(
                ExecutionEventEnvelope(
                    execution_id=execution.id,
                    run_id=run.id,
                    workspace_id=workspace_id,
                    event_type=ExecutionEventType.EXECUTION_COMPLETED,
                    payload={"status": "failed"},
                    terminal_status="failed",
                    error_message=str(exc)[:2000],
                    result_summary=str(exc)[:2000],
                ),
                self.db,
            )
            await self.db.refresh(run)

        return run

    async def _create_and_fire_draft(
        self,
        agent: Agent,
        version: AgentVersion,
        workspace_id: uuid.UUID,
        prompt: str,
        trigger_source: str,
        user_id: str,
        input_payload: dict | None = None,
    ) -> AgentRun:
        runtime_binding = self._build_draft_runtime_binding(version)
        engine_kind = self._resolve_draft_engine_kind(version)

        run = AgentRun(
            release_id=None,
            agent_version_id=version.id,
            workspace_id=workspace_id,
            trigger_source=trigger_source,
            goal=prompt[:500] if prompt else None,
            input_payload=input_payload,
            status="pending",
            created_by=user_id,
        )
        self.db.add(run)
        await self.db.flush()

        execution = Execution(
            run_id=run.id,
            attempt_index=1,
            executor_kind=runtime_binding.get("runtime_type", engine_kind),
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()

        run.current_execution_id = execution.id
        await self.db.commit()

        await self.publish_run_status_change(
            self.db, run,
            execution_id=execution.id,
            target_status="running",
        )
        await self.db.refresh(run)

        try:
            await self._fire_engine(
                execution=execution,
                release_runtime_binding=runtime_binding,
                runtime_kind=engine_kind,
                version=version,
                agent=agent,
                workspace_id=workspace_id,
                prompt=prompt,
            )
        except Exception as exc:
            logger.error(f"[Orchestrator] _fire_engine failed for draft run: {exc}")
            await execution_event_bus.publish(
                ExecutionEventEnvelope(
                    execution_id=execution.id,
                    run_id=run.id,
                    workspace_id=workspace_id,
                    event_type=ExecutionEventType.EXECUTION_COMPLETED,
                    payload={"status": "failed"},
                    terminal_status="failed",
                    error_message=str(exc)[:2000],
                    result_summary=str(exc)[:2000],
                ),
                self.db,
            )
            await self.db.refresh(run)

        return run

    async def _fire_engine(
        self,
        execution: Execution,
        version: AgentVersion,
        agent: Agent,
        workspace_id: uuid.UUID,
        prompt: str,
        *,
        release: AgentRelease | None = None,
        release_runtime_binding: dict | None = None,
        runtime_kind: str | None = None,
        engine_kind_override: str | None = None,
        definition_kind_override: str | None = None,
        definition_payload_override: dict | None = None,
    ) -> None:
        """Build context and fire engine in a background task."""
        credentials = build_agent_credentials(agent)

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

        # Wire context callbacks (pass run metadata to avoid extra DB query)
        _run_meta = dict(
            trigger_source=run.trigger_source,
            thread_id=run.thread_id,
            task_id=run.task_id,
        )
        self._wire_context(context, **_run_meta)

        runtime_binding = release_runtime_binding or (release.runtime_binding if release else {})
        resolved_runtime_kind = runtime_kind or (release.runtime_kind if release else None)
        if not resolved_runtime_kind:
            raise BadRequestException("No runtime kind available for execution")

        engine = engine_registry.get(engine_kind_override or resolved_runtime_kind)
        _def_kind = definition_kind_override or version.definition_kind
        _def_payload = definition_payload_override or version.definition_payload

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
                    self._wire_context(ctx, **_run_meta)

                    await engine.start(
                        ctx,
                        release_runtime_binding=runtime_binding,
                        definition_kind=_def_kind,
                        definition_payload=_def_payload,
                        prompt=prompt,
                    )
            except Exception as exc:
                logger.error(f"[Orchestrator] Engine failed for execution {execution.id}: {exc}")
                try:
                    await ctx._complete_fn("failed", f"Engine error: {str(exc)[:2000]}")
                except Exception as cleanup_exc:
                    logger.error(f"[Orchestrator] Failed to mark execution as failed: {cleanup_exc}")

        safe_create_task(_run_engine(), name=f"engine-{execution.id}")

    def _wire_context(
        self,
        ctx: ExecutionContext,
        *,
        trigger_source: str | None = None,
        thread_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> None:
        """Attach emit/status/complete callbacks to context.

        Run metadata is passed in directly by the caller (who already has the
        run object), avoiding an extra DB query.
        """

        def _envelope(**overrides: Any) -> ExecutionEventEnvelope:
            return ExecutionEventEnvelope(
                execution_id=ctx.execution_id,
                run_id=ctx.run_id,
                workspace_id=ctx.workspace_id,
                trigger_source=trigger_source,
                thread_id=thread_id,
                task_id=task_id,
                **overrides,
            )

        async def _emit(event_type: ExecutionEventType, payload: dict) -> None:
            await execution_event_bus.publish(
                _envelope(event_type=event_type, payload=payload), ctx.db,
            )

        async def _status(status: str) -> None:
            await execution_event_bus.publish(
                _envelope(
                    event_type=ExecutionEventType.EXECUTION_STATUS_CHANGE,
                    payload={"status": status},
                    target_status=status,
                ),
                ctx.db,
            )

        async def _complete(status: str, result_summary: str | None = None) -> None:
            await execution_event_bus.publish(
                _envelope(
                    event_type=ExecutionEventType.EXECUTION_COMPLETED,
                    payload={"status": status},
                    terminal_status=status,
                    result_summary=result_summary,
                ),
                ctx.db,
            )

        ctx._emit_fn = _emit
        ctx._status_fn = _status
        ctx._complete_fn = _complete

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def publish_run_status_change(
        db: AsyncSession,
        run: AgentRun,
        *,
        execution_id: uuid.UUID,
        target_status: str,
        result_summary: str | None = None,
    ) -> None:
        """Publish a RUN_STATUS_CHANGE event through the bus."""
        await execution_event_bus.publish(
            ExecutionEventEnvelope(
                execution_id=execution_id,
                run_id=run.id,
                workspace_id=run.workspace_id,
                event_type=ExecutionEventType.RUN_STATUS_CHANGE,
                payload={"status": target_status},
                target_status=target_status,
                result_summary=result_summary,
                trigger_source=run.trigger_source,
                thread_id=run.thread_id,
                task_id=run.task_id,
            ),
            db,
        )

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
