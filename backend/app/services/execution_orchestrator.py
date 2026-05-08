"""
Execution Orchestrator — service-layer entry point for execution dispatch.

Layer 2: sits between API/triggers (Layer 1) and engines (Layer 3).
Creates AgentRun + Execution, resolves the engine, builds context, and starts execution.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import AppError, InvalidRequestError, NotFoundError, normalize_app_error
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
        run = await self._create_and_fire(
            agent=agent,
            release_id=agent.active_release_id,
            workspace_id=agent.workspace_id,
            prompt=prompt,
            trigger_medium="system",
            run_purpose="production",
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

        return await self._create_and_fire(
            agent=agent,
            release_id=agent.active_release_id,
            workspace_id=agent.workspace_id,
            prompt=message,
            trigger_medium="api",
            run_purpose="production",
            thread_id=thread_id,
            user_id=user_id,
        )

    async def dispatch_direct(
        self,
        release_id: uuid.UUID,
        prompt: str,
        user_id: str,
        trigger_medium: str = "api",
        run_purpose: str = "production",
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
            trigger_medium=trigger_medium,
            run_purpose=run_purpose,
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
        thread_id: uuid.UUID | None = None,
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

        return await self._create_and_fire_draft(
            agent=agent,
            version=version,
            workspace_id=workspace_id,
            prompt=prompt,
            trigger_medium="ui",
            run_purpose="draft_test",
            user_id=user_id,
            thread_id=thread_id,
            input_payload=input_payload,
        )

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

        return await self._create_and_fire_draft(
            agent=agent,
            version=version,
            workspace_id=workspace_id,
            prompt=prompt,
            trigger_medium="ui",
            run_purpose="internal_builder",
            user_id=user_id,
            input_payload=copilot_payload,
            engine_kind_override="build_copilot",
            definition_kind_override="build_copilot",
            definition_payload_override=copilot_payload,
        )

    async def dispatch_debug(
        self,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        prompt: str,
        user_id: str,
        workspace_id: uuid.UUID,
        thread_id: uuid.UUID | None = None,
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

        run = await self._create_and_fire_draft(
            agent=agent,
            version=version,
            workspace_id=workspace_id,
            prompt=prompt,
            trigger_medium="ui",
            run_purpose="debug",
            user_id=user_id,
            thread_id=thread_id,
            input_payload={"debug": True, "variables": variables or {}},
            debug=True,
        )

        # Create Trace record for observation tracking
        from datetime import datetime, timezone

        from app.core.observation.model import Trace

        if run.current_execution_id:
            # Use thread_id as session_id to group multi-turn traces
            session_id = (
                str(thread_id)
                if thread_id
                else f"debug-{user_id}-{version_id}-{datetime.now(timezone.utc).date()}"
            )
            trace = Trace(
                id=run.current_execution_id,
                name=agent.name,
                workspace_id=workspace_id,
                start_time=datetime.now(timezone.utc),
                status="running",
                execution_id=run.current_execution_id,
                agent_version_id=version_id,
                user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
                session_id=session_id,
                input={"prompt": prompt, "variables": variables or {}},
            )
            self.db.add(trace)
            await self.db.commit()

        return run

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

    async def _create_and_fire(
        self,
        agent: Agent,
        release_id: uuid.UUID,
        workspace_id: uuid.UUID,
        prompt: str,
        trigger_medium: str,
        run_purpose: str,
        user_id: str,
        thread_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        input_payload: dict | None = None,
        *,
        engine_kind_override: str | None = None,
        definition_kind_override: str | None = None,
        definition_payload_override: dict | None = None,
    ) -> AgentRun:
        release = await self._get_release(release_id)
        version = await self._get_version(release.agent_version_id)

        await self._require_no_active_run(thread_id)

        # Create Run in pending state — bus will transition to running
        run = AgentRun(
            release_id=release_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            task_id=task_id,
            trigger_medium=trigger_medium,
            run_purpose=run_purpose,
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
            engine_kind=engine_kind_override or version.engine_kind,
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
            app_error = normalize_app_error(exc, default_code="EXECUTION_FAILED", source="engine")
            error_payload = app_error.to_payload()
            error_payload.setdefault("data", {})["reason"] = "engine_fire_failed"
            await execution_event_bus.publish(
                ExecutionEventEnvelope(
                    execution_id=execution.id,
                    run_id=run.id,
                    workspace_id=workspace_id,
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

    async def _create_and_fire_draft(
        self,
        agent: Agent,
        version: AgentVersion,
        workspace_id: uuid.UUID,
        prompt: str,
        trigger_medium: str,
        run_purpose: str,
        user_id: str,
        thread_id: uuid.UUID | None = None,
        input_payload: dict | None = None,
        *,
        debug: bool = False,
        engine_kind_override: str | None = None,
        definition_kind_override: str | None = None,
        definition_payload_override: dict | None = None,
    ) -> AgentRun:
        self._validate_draft_overrides(
            engine_kind_override=engine_kind_override,
            definition_kind_override=definition_kind_override,
            definition_payload_override=definition_payload_override,
        )
        runtime_binding: dict = {}

        await self._require_no_active_run(thread_id)

        run = AgentRun(
            release_id=None,
            agent_version_id=version.id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            trigger_medium=trigger_medium,
            run_purpose=run_purpose,
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
            engine_kind=engine_kind_override or version.engine_kind,
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
                release_runtime_binding=runtime_binding,
                version=version,
                agent=agent,
                workspace_id=workspace_id,
                prompt=prompt,
                engine_kind_override=engine_kind_override,
                definition_kind_override=definition_kind_override,
                definition_payload_override=definition_payload_override,
                debug=debug,
            )
        except Exception as exc:
            logger.error(f"[Orchestrator] _fire_engine failed for draft run: {exc}")
            app_error = normalize_app_error(exc, default_code="EXECUTION_FAILED", source="engine")
            error_payload = app_error.to_payload()
            error_payload.setdefault("data", {})["reason"] = "engine_fire_failed"
            await execution_event_bus.publish(
                ExecutionEventEnvelope(
                    execution_id=execution.id,
                    run_id=run.id,
                    workspace_id=workspace_id,
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

    def _validate_draft_overrides(
        self,
        *,
        engine_kind_override: str | None,
        definition_kind_override: str | None,
        definition_payload_override: dict | None,
    ) -> None:
        override_presence = (
            engine_kind_override is not None,
            definition_kind_override is not None,
            definition_payload_override is not None,
        )
        if any(override_presence) and not all(override_presence):
            raise InvalidRequestError(
                "Draft override parameters must be all absent or all present.",
                code="DRAFT_OVERRIDE_PARAMETERS_INVALID",
                data={
                    "engine_kind_override": engine_kind_override is not None,
                    "definition_kind_override": definition_kind_override is not None,
                    "definition_payload_override": definition_payload_override is not None,
                },
            )

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
        engine_kind_override: str | None = None,
        definition_kind_override: str | None = None,
        definition_payload_override: dict | None = None,
        debug: bool = False,
    ) -> None:
        """Build context and fire engine in a background task."""
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

        runtime_binding = release_runtime_binding or (release.runtime_binding if release else {})
        engine = engine_registry.get(engine_kind_override or execution.engine_kind)
        _def_kind = definition_kind_override or version.engine_kind
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
                    self._wire_context(ctx, **run_meta)

                    collector = None
                    if debug:
                        from app.core.observation import ObservationCollector
                        from app.core.observation.types import ObservationLevel
                        from app.websocket.execution_subscription_manager import execution_subscription_manager

                        async def _db_factory():
                            return db

                        async def _broadcast(exec_id: Any, message: dict) -> None:
                            await execution_subscription_manager.broadcast_event(str(exec_id), message)

                        collector = ObservationCollector(
                            trace_id=execution.id,
                            execution_id=execution.id,
                            workspace_id=workspace_id,
                            db_session_factory=_db_factory,
                            broadcast_fn=_broadcast,
                        )
                        ctx.debug = True
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
                        if collector:
                            collector.record_event(
                                f"error:{type(exc).__name__}",
                                input={"message": str(exc)},
                                level=ObservationLevel.ERROR,
                            )
                        raise
                    finally:
                        if collector:
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

    async def _require_no_active_run(self, thread_id: uuid.UUID | None) -> None:
        """Enforce invariant: at most one active AgentRun per Thread.

        No-op when thread_id is None (pre-Thread-as-Session paths). Once
        thread_id becomes NOT NULL, this check is unconditional.
        """
        if thread_id is None:
            return
        active = (
            await self.db.execute(
                select(AgentRun.id).where(
                    AgentRun.thread_id == thread_id,
                    AgentRun.status.in_(("pending", "running")),
                )
            )
        ).scalar_one_or_none()
        if active:
            raise InvalidRequestError(
                "Thread has an active run, please wait for it to complete",
                code="THREAD_ACTIVE_RUN_EXISTS",
                data={"thread_id": str(thread_id), "run_id": str(active)},
            )
