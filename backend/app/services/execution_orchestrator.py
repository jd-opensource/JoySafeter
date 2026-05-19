"""
Execution Orchestrator — service-layer entry point for execution dispatch.

Layer 2: sits between API/triggers (Layer 1) and engines (Layer 3).
Creates AgentRun + Execution, resolves the engine, builds context, and starts execution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import AppError, InvalidRequestError, NotFoundError, normalize_app_error
from app.core.engine.protocol import ExecutionContext
from app.core.engine.registry import engine_registry
from app.core.events import ExecutionEventEnvelope, execution_event_bus
from app.core.events.event_types import ExecutionEventType
from app.core.observation.model import Trace
from app.core.state_machines.transitions import transition_task
from app.models.agent import Agent, AgentRelease, AgentVersion
from app.models.agent_run import AgentRun
from app.models.execution import Execution
from app.models.task import Task
from app.models.thread import Thread
from app.utils.credentials import build_agent_credentials
from app.utils.datetime import utc_now
from app.utils.safe_task import safe_create_task

# Status values that count as an "active" AgentRun — mirrored in the
# partial unique index `uq_agent_runs_active_per_thread`.
ACTIVE_RUN_STATUSES: tuple[str, ...] = ("pending", "running")


@dataclass
class RunSpec:
    """Everything needed to create an AgentRun + Execution and fire an engine.

    ``release`` being set (vs None) determines whether this is a
    release-based production run or a draft test-lab run.
    """

    agent: Agent
    version: AgentVersion
    workspace_id: uuid.UUID
    prompt: str
    trigger_medium: str
    run_purpose: str
    user_id: str
    thread_id: uuid.UUID
    release: AgentRelease | None = None
    task_id: uuid.UUID | None = None
    input_payload: dict | None = None
    engine_kind_override: str | None = None
    definition_kind_override: str | None = None
    definition_payload_override: dict | None = None

    def __post_init__(self) -> None:
        overrides = (self.engine_kind_override, self.definition_kind_override, self.definition_payload_override)
        if any(o is not None for o in overrides) and not all(o is not None for o in overrides):
            raise ValueError("engine_kind_override, definition_kind_override, and definition_payload_override must be all-or-nothing")


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
            raise InvalidRequestError(
                "Task already has an active run. Cancel it first.",
                code="TASK_RUN_ALREADY_ACTIVE",
                data={"task_id": str(task_id), "run_id": str(task.latest_run_id)},
            )
        if task.status not in self.DISPATCHABLE_STATUSES and task.status != "in_progress":
            raise InvalidRequestError(
                f"Cannot dispatch task in '{task.status}' status. Move the task back to backlog first.",
                code="TASK_STATUS_NOT_DISPATCHABLE",
                data={"task_id": str(task_id), "status": task.status},
            )
        if not task.agent_id:
            raise InvalidRequestError(
                "Task has no assigned agent",
                code="TASK_AGENT_MISSING",
                data={"task_id": str(task_id)},
            )

        agent = await self._get_agent(task.agent_id)
        if not agent.active_release_id:
            raise InvalidRequestError(
                f"Agent '{agent.name}' has no active release",
                code="AGENT_ACTIVE_RELEASE_MISSING",
                data={"agent_id": str(agent.id), "agent_name": agent.name},
            )

        prompt = prompt_override or task.goal or task.title
        release = await self._get_release(agent.active_release_id)
        version = await self._get_version(release.agent_version_id)
        run = await self._create_run_and_fire(RunSpec(
            agent=agent,
            version=version,
            release=release,
            workspace_id=agent.workspace_id,
            prompt=prompt,
            trigger_medium="system",
            run_purpose="production",
            user_id=user_id,
            thread_id=task.thread_id,
            task_id=task_id,
        ))

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
        thread = (await self.db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
        if not thread:
            raise NotFoundError("Thread not found", code="THREAD_NOT_FOUND", data={"thread_id": str(thread_id)})

        agent = await self._get_agent(thread.agent_id)
        if not agent.active_release_id:
            raise InvalidRequestError(
                f"Agent '{agent.name}' has no active release",
                code="AGENT_ACTIVE_RELEASE_MISSING",
                data={"agent_id": str(agent.id), "agent_name": agent.name},
            )

        release = await self._get_release(agent.active_release_id)
        version = await self._get_version(release.agent_version_id)
        return await self._create_run_and_fire(RunSpec(
            agent=agent,
            version=version,
            release=release,
            workspace_id=agent.workspace_id,
            prompt=message,
            trigger_medium="api",
            run_purpose="production",
            user_id=user_id,
            thread_id=thread_id,
        ))

    async def dispatch_direct(
        self,
        release_id: uuid.UUID,
        prompt: str,
        user_id: str,
        thread_id: uuid.UUID,
        trigger_medium: str = "api",
        run_purpose: str = "production",
        task_id: uuid.UUID | None = None,
        input_payload: dict | None = None,
    ) -> AgentRun:
        """Direct dispatch with explicit release_id (API / Scheduler)."""
        release = await self._get_release(release_id)
        version = await self._get_version(release.agent_version_id)
        agent = await self._get_agent(version.agent_id)

        return await self._create_run_and_fire(RunSpec(
            agent=agent,
            version=version,
            release=release,
            workspace_id=agent.workspace_id,
            prompt=prompt,
            trigger_medium=trigger_medium,
            run_purpose=run_purpose,
            user_id=user_id,
            thread_id=thread_id,
            task_id=task_id,
            input_payload=input_payload,
        ))

    async def dispatch_draft(
        self,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        prompt: str,
        user_id: str,
        workspace_id: uuid.UUID,
        thread_id: uuid.UUID,
        input_payload: dict | None = None,
    ) -> AgentRun:
        """Dispatch a Test Lab run against a draft AgentVersion."""
        version = await self._get_version(version_id)
        if version.agent_id != agent_id:
            raise InvalidRequestError(
                "Version does not belong to this agent",
                code="AGENT_VERSION_AGENT_MISMATCH",
                data={"agent_id": str(agent_id), "version_id": str(version_id)},
            )

        agent = await self._get_agent(agent_id)
        if agent.workspace_id != workspace_id:
            raise InvalidRequestError(
                "Agent does not belong to this workspace",
                code="AGENT_WORKSPACE_MISMATCH",
                data={"agent_id": str(agent_id), "workspace_id": str(workspace_id)},
            )

        return await self._create_run_and_fire(RunSpec(
            agent=agent,
            version=version,
            workspace_id=workspace_id,
            prompt=prompt,
            trigger_medium="ui",
            run_purpose="draft_test",
            user_id=user_id,
            thread_id=thread_id,
            input_payload=input_payload,
        ))

    async def dispatch_copilot_draft(
        self,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        workspace_id: uuid.UUID,
        prompt: str,
        user_id: str,
        graph_context: dict,
        conversation_history: list | None = None,
        mode: str = "deepagents",
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> AgentRun:
        """Dispatch a copilot interaction against a draft AgentVersion."""
        version = await self._get_version(version_id)
        if version.agent_id != agent_id:
            raise InvalidRequestError(
                "Version does not belong to this agent",
                code="AGENT_VERSION_AGENT_MISMATCH",
                data={"agent_id": str(agent_id), "version_id": str(version_id)},
            )

        agent = await self._get_agent(agent_id)
        if agent.workspace_id != workspace_id:
            raise InvalidRequestError(
                "Agent does not belong to this workspace",
                code="AGENT_WORKSPACE_MISMATCH",
                data={"agent_id": str(agent_id), "workspace_id": str(workspace_id)},
            )

        copilot_payload = self._build_copilot_payload(
            agent_id=agent_id,
            user_id=user_id,
            graph_context=graph_context,
            conversation_history=conversation_history,
            mode=mode,
            provider_name=provider_name,
            model_name=model_name,
        )

        # Copilot is a build-time interaction; still gets a Thread so the
        # container/CLI-session/Trace aggregation model is uniform.
        thread = Thread(
            agent_id=agent_id,
            workspace_id=workspace_id,
            title=f"copilot:{version_id}",
            status="active",
            created_by=user_id,
        )
        self.db.add(thread)
        await self.db.flush()

        return await self._create_run_and_fire(RunSpec(
            agent=agent,
            version=version,
            workspace_id=workspace_id,
            prompt=prompt,
            trigger_medium="ui",
            run_purpose="internal_builder",
            user_id=user_id,
            thread_id=thread.id,
            input_payload=copilot_payload,
            engine_kind_override="build_copilot",
            definition_kind_override="build_copilot",
            definition_payload_override=copilot_payload,
        ))

    async def dispatch_debug(
        self,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        prompt: str,
        user_id: str,
        workspace_id: uuid.UUID,
        thread_id: uuid.UUID,
        variables: dict | None = None,
    ) -> AgentRun:
        """Dispatch a debug run with observation tracing."""
        version = await self._get_version(version_id)
        if version.agent_id != agent_id:
            raise InvalidRequestError(
                "Version does not belong to this agent",
                code="AGENT_VERSION_AGENT_MISMATCH",
                data={"agent_id": str(agent_id), "version_id": str(version_id)},
            )

        agent = await self._get_agent(agent_id)
        if agent.workspace_id != workspace_id:
            raise InvalidRequestError(
                "Agent does not belong to this workspace",
                code="AGENT_WORKSPACE_MISMATCH",
                data={"agent_id": str(agent_id), "workspace_id": str(workspace_id)},
            )

        return await self._create_run_and_fire(RunSpec(
            agent=agent,
            version=version,
            workspace_id=workspace_id,
            prompt=prompt,
            trigger_medium="ui",
            run_purpose="debug",
            user_id=user_id,
            thread_id=thread_id,
            input_payload={"debug": True, "variables": variables or {}},
        ))

    def _resolve_engine(self, execution: Execution, release: AgentRelease):
        return engine_registry.get(execution.engine_kind)

    def _resolve_draft_engine_kind(self, version: AgentVersion) -> str:
        return version.engine_kind

    def _build_copilot_payload(
        self,
        *,
        agent_id: uuid.UUID,
        user_id: str,
        graph_context: dict,
        conversation_history: list | None,
        mode: str,
        provider_name: str | None,
        model_name: str | None,
    ) -> dict:
        return {
            "graph_context": graph_context,
            "conversation_history": conversation_history,
            "mode": mode,
            "provider_name": provider_name,
            "model_name": model_name,
            "user_id": user_id,
            "graph_id": str(agent_id),
        }

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
            trigger_medium=run.trigger_medium,
            run_purpose=run.run_purpose,
            thread_id=run.thread_id,
            task_id=run.task_id,
        )
        await execution_event_bus.publish(envelope, self.db)

    async def cancel_run(self, run_id: uuid.UUID) -> AgentRun:
        """Cancel a running execution."""
        run = await self._get_run(run_id)
        if run.status in ("succeeded", "failed", "cancelled"):
            raise InvalidRequestError(
                f"Cannot cancel run in status {run.status}",
                code="RUN_CANCEL_STATUS_INVALID",
                data={"run_id": str(run_id), "status": run.status},
            )

        execution_id = run.current_execution_id or uuid.UUID(int=0)

        if run.current_execution_id:
            execution = (
                await self.db.execute(select(Execution).where(Execution.id == run.current_execution_id))
            ).scalar_one_or_none()
            if execution:
                if run.release_id:
                    release = await self._get_release(run.release_id)
                    engine = self._resolve_engine(execution, release)
                elif run.agent_version_id:
                    version = await self._get_version(run.agent_version_id)
                    engine = engine_registry.get(self._resolve_draft_engine_kind(version))
                else:
                    raise InvalidRequestError(
                        "Run has neither release_id nor agent_version_id",
                        code="RUN_BINDING_INVALID",
                        data={"run_id": str(run_id)},
                    )
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
            raise InvalidRequestError(
                "Can only retry failed or cancelled runs",
                code="RUN_RETRY_STATUS_INVALID",
                data={"run_id": str(run_id), "status": run.status},
            )
        if not run.release_id:
            raise InvalidRequestError(
                "Draft Test Lab runs cannot be retried",
                code="RUN_RETRY_DRAFT_FORBIDDEN",
                data={"run_id": str(run_id)},
            )

        release = await self._get_release(run.release_id)
        version = await self._get_version(release.agent_version_id)
        agent = await self._get_agent(version.agent_id)

        # Create new execution attempt
        from sqlalchemy import func

        max_attempt = (
            await self.db.execute(
                select(func.coalesce(func.max(Execution.attempt_index), 0)).where(Execution.run_id == run_id)
            )
        ).scalar() or 0

        execution = Execution(
            run_id=run_id,
            attempt_index=max_attempt + 1,
            engine_kind=version.engine_kind,
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()

        run.current_execution_id = execution.id
        await self.db.flush()

        await self.publish_run_status_change(
            self.db,
            run,
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
        execution = (await self.db.execute(select(Execution).where(Execution.id == execution_id))).scalar_one_or_none()
        if not execution:
            raise NotFoundError(
                "Execution not found",
                code="EXECUTION_NOT_FOUND",
                data={"execution_id": str(execution_id)},
            )

        run = await self._get_run(execution.run_id)
        if run.release_id:
            release = await self._get_release(run.release_id)
            engine = self._resolve_engine(execution, release)
        elif run.agent_version_id:
            version = await self._get_version(run.agent_version_id)
            engine = engine_registry.get(self._resolve_draft_engine_kind(version))
        else:
            raise InvalidRequestError(
                "Run has neither release_id nor agent_version_id",
                code="RUN_BINDING_INVALID",
                data={"run_id": str(run.id)},
            )
        if not engine.capabilities.supports_message_injection:
            raise InvalidRequestError(
                "Execution engine does not support message injection",
                code="EXECUTION_OPERATION_UNSUPPORTED",
                data={
                    "operation": "send_message",
                    "engine_kind": getattr(engine, "engine_kind", execution.engine_kind),
                    "execution_id": str(execution_id),
                },
            )
        await engine.send_message(execution_id, message)

    # ------------------------------------------------------------------
    # Internal: create Run + Execution, fire engine
    # ------------------------------------------------------------------

    async def _create_run_and_fire(self, spec: RunSpec) -> AgentRun:
        """Create AgentRun + Execution and fire the engine in a background task."""
        await self._require_no_active_run(spec.thread_id)

        run = AgentRun(
            release_id=spec.release.id if spec.release else None,
            agent_version_id=None if spec.release else spec.version.id,
            workspace_id=spec.workspace_id,
            thread_id=spec.thread_id,
            task_id=spec.task_id,
            trigger_medium=spec.trigger_medium,
            run_purpose=spec.run_purpose,
            goal=spec.prompt[:500] if spec.prompt else None,
            input_payload=spec.input_payload,
            status="pending",
            created_by=spec.user_id,
        )
        self.db.add(run)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise self._raise_active_run_conflict(spec.thread_id)

        execution = Execution(
            run_id=run.id,
            attempt_index=1,
            engine_kind=spec.engine_kind_override or spec.version.engine_kind,
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()

        run.current_execution_id = execution.id
        await self.db.commit()

        await self.publish_run_status_change(
            self.db,
            run,
            execution_id=execution.id,
            target_status="running",
        )
        await self.db.refresh(run)

        try:
            await self._fire_engine(
                execution=execution,
                version=spec.version,
                agent=spec.agent,
                workspace_id=spec.workspace_id,
                prompt=spec.prompt,
                release=spec.release,
                engine_kind_override=spec.engine_kind_override,
                definition_kind_override=spec.definition_kind_override,
                definition_payload_override=spec.definition_payload_override,
            )
        except Exception as exc:
            logger.error(f"[Orchestrator] _fire_engine failed: {exc}")
            app_error = normalize_app_error(exc, default_code="EXECUTION_FAILED", source="engine")
            error_payload = app_error.to_payload()
            error_payload.setdefault("data", {})["reason"] = "engine_fire_failed"
            await execution_event_bus.publish(
                ExecutionEventEnvelope(
                    execution_id=execution.id,
                    run_id=run.id,
                    workspace_id=spec.workspace_id,
                    event_type=ExecutionEventType.EXECUTION_COMPLETED,
                    payload={
                        "status": "failed",
                        "error": error_payload,
                        "result_summary": str(exc)[:2000],
                    },
                    terminal_status="failed",
                    error=error_payload,
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
        engine_kind_override: str | None = None,
        definition_kind_override: str | None = None,
        definition_payload_override: dict | None = None,
    ) -> None:
        """Build context and fire engine in a background task.

        Trace + ObservationCollector are created unconditionally — every run
        contributes to full-stack tracing, grouped by thread_id as session_id.
        """
        credentials = build_agent_credentials(agent)

        # Resolve auto_approve from task if linked
        auto_approve = True
        run = (await self.db.execute(select(AgentRun).where(AgentRun.id == execution.run_id))).scalar_one()
        if run.task_id:
            task = (await self.db.execute(select(Task).where(Task.id == run.task_id))).scalar_one_or_none()
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
        run_meta = dict(
            trigger_medium=run.trigger_medium,
            run_purpose=run.run_purpose,
            thread_id=run.thread_id,
            task_id=run.task_id,
        )
        self._wire_context(context, **run_meta)  # type: ignore[arg-type]

        runtime_binding = release.runtime_binding if release else {}
        engine = engine_registry.get(engine_kind_override or execution.engine_kind)
        _def_kind = definition_kind_override or version.engine_kind
        _def_payload = definition_payload_override or version.definition_payload

        async def _run_engine():
            from app.core.database import AsyncSessionLocal
            from app.core.observation import ObservationCollector
            from app.core.observation.types import ObservationLevel
            from app.websocket.execution_subscription_manager import execution_subscription_manager

            try:
                async with AsyncSessionLocal() as db:
                    # Persist the Trace row inside this session so observations
                    # written later FK to a committed row — no cross-session
                    # visibility race with the caller's transaction.
                    await self._insert_trace(
                        db,
                        execution=execution,
                        run=run,
                        agent_name=agent.name,
                        agent_version_id=version.id,
                        prompt=prompt,
                    )

                    # Rebuild context with fresh session
                    ctx = ExecutionContext(
                        db=db,
                        execution_id=execution.id,
                        run_id=run.id,
                        workspace_id=workspace_id,
                        credentials=credentials,
                        auto_approve=auto_approve,
                    )
                    self._wire_context(ctx, **run_meta)

                    async def _db_factory():
                        return AsyncSessionLocal()

                    async def _broadcast(exec_id: Any, message: dict) -> None:
                        await execution_subscription_manager.broadcast_event(str(exec_id), message)

                    collector = ObservationCollector(
                        trace_id=execution.id,
                        execution_id=execution.id,
                        workspace_id=workspace_id,
                        db_session_factory=_db_factory,
                        broadcast_fn=_broadcast,
                    )
                    ctx.collector = collector

                    try:
                        await engine.start(
                            ctx,
                            release_runtime_binding=runtime_binding,
                            engine_kind=_def_kind,
                            definition_payload=_def_payload,
                            prompt=prompt,
                        )
                    except Exception as exc:
                        collector.record_event(
                            f"error:{type(exc).__name__}",
                            input={"message": str(exc)},
                            level=ObservationLevel.ERROR,
                        )
                        raise
                    finally:
                        await collector.finalize()
            except Exception as exc:
                logger.error(f"[Orchestrator] Engine failed for execution {execution.id}: {exc}")
                try:
                    app_error = normalize_app_error(
                        exc,
                        default_code="EXECUTION_ENGINE_FAILED",
                        default_message="Engine execution failed",
                        default_data={"execution_id": str(execution.id), "run_id": str(run.id)},
                        source="engine",
                    )
                    await ctx._complete_fn("failed", app_error.message[:2000], app_error)
                except Exception as cleanup_exc:
                    logger.error(f"[Orchestrator] Failed to mark execution as failed: {cleanup_exc}")

        safe_create_task(_run_engine(), name=f"engine-{execution.id}")

    def _wire_context(
        self,
        ctx: ExecutionContext,
        *,
        trigger_medium: str | None = None,
        run_purpose: str | None = None,
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
                trigger_medium=trigger_medium,
                run_purpose=run_purpose,
                thread_id=thread_id,
                task_id=task_id,
                **overrides,
            )

        async def _emit(event_type: ExecutionEventType, payload: dict) -> None:
            await execution_event_bus.publish(
                _envelope(event_type=event_type, payload=payload),
                ctx.db,
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

        async def _complete(
            status: str,
            result_summary: str | None = None,
            error: AppError | None = None,
        ) -> None:
            error_payload = error.to_payload() if error is not None else None
            await execution_event_bus.publish(
                _envelope(
                    event_type=ExecutionEventType.EXECUTION_COMPLETED,
                    payload={
                        "status": status,
                        "error": error_payload,
                    },
                    terminal_status=status,
                    error=error_payload,
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
                trigger_medium=run.trigger_medium,
                run_purpose=run.run_purpose,
                thread_id=run.thread_id,
                task_id=run.task_id,
            ),
            db,
        )

    async def _get_task(self, task_id: uuid.UUID) -> Task:
        result = (await self.db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not result:
            raise NotFoundError("Task not found", code="TASK_NOT_FOUND", data={"task_id": str(task_id)})
        return result

    async def _get_agent(self, agent_id: uuid.UUID) -> Agent:
        result = (await self.db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if not result:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})
        return result

    async def _get_release(self, release_id: uuid.UUID) -> AgentRelease:
        result = (await self.db.execute(select(AgentRelease).where(AgentRelease.id == release_id))).scalar_one_or_none()
        if not result:
            raise NotFoundError(
                "Agent release not found",
                code="AGENT_RELEASE_NOT_FOUND",
                data={"release_id": str(release_id)},
            )
        return result

    async def _get_version(self, version_id: uuid.UUID) -> AgentVersion:
        result = (await self.db.execute(select(AgentVersion).where(AgentVersion.id == version_id))).scalar_one_or_none()
        if not result:
            raise NotFoundError(
                "Agent version not found",
                code="AGENT_VERSION_NOT_FOUND",
                data={"version_id": str(version_id)},
            )
        return result

    async def _get_run(self, run_id: uuid.UUID) -> AgentRun:
        result = (await self.db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
        if not result:
            raise NotFoundError("Agent run not found", code="AGENT_RUN_NOT_FOUND", data={"run_id": str(run_id)})
        return result

    async def _require_no_active_run(self, thread_id: uuid.UUID) -> None:
        """Enforce invariant: at most one active AgentRun per Thread.

        Fast path — the partial unique index
        ``uq_agent_runs_active_per_thread`` is the correctness backstop
        against the check/insert race; this SELECT just surfaces a friendly
        error in the common (uncontested) case.
        """
        active = (
            await self.db.execute(
                select(AgentRun.id).where(
                    AgentRun.thread_id == thread_id,
                    AgentRun.status.in_(ACTIVE_RUN_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if active:
            raise InvalidRequestError(
                "Thread has an active run, please wait for it to complete",
                code="THREAD_ACTIVE_RUN_EXISTS",
                data={"thread_id": str(thread_id), "run_id": str(active)},
            )

    @staticmethod
    def _raise_active_run_conflict(thread_id: uuid.UUID) -> InvalidRequestError:
        return InvalidRequestError(
            "Thread has an active run, please wait for it to complete",
            code="THREAD_ACTIVE_RUN_EXISTS",
            data={"thread_id": str(thread_id)},
        )

    async def _insert_trace(
        self,
        db: AsyncSession,
        *,
        execution: Execution,
        run: AgentRun,
        agent_name: str,
        agent_version_id: uuid.UUID,
        prompt: str,
    ) -> None:
        """Insert the Trace row for this execution.

        Called inside the engine's fresh session so the row is committed with
        the engine transaction — downstream observations FK to it safely.
        Trace.id == Execution.id by convention; session_id == str(thread_id)
        groups multi-turn traces in the UI.
        """
        trace = Trace(
            id=execution.id,
            name=agent_name,
            workspace_id=run.workspace_id,
            start_time=utc_now(),
            status="running",
            execution_id=execution.id,
            agent_version_id=agent_version_id,
            user_id=(
                uuid.UUID(run.created_by)
                if run.created_by and isinstance(run.created_by, str)
                else run.created_by
            ),
            session_id=str(run.thread_id),
            input={"prompt": prompt},
        )
        db.add(trace)
        await db.flush()
