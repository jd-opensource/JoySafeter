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

from app.common.app_errors import InvalidRequestError, NotFoundError, normalize_app_error
from app.core.constants import RunPurpose, TriggerMedium
from app.core.engine.registry import engine_registry
from app.core.events import ExecutionEventEnvelope, execution_event_bus
from app.core.events.event_types import ExecutionEventType
from app.core.state_machines.transitions import transition_task
from app.models.agent import Agent, AgentRelease, AgentVersion
from app.models.agent_run import AgentRun
from app.models.execution import Execution
from app.models.task import Task
from app.models.thread import Thread
from app.utils.datetime import utc_now

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
    trigger_medium: TriggerMedium
    run_purpose: RunPurpose
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
            trigger_medium=TriggerMedium.SYSTEM,
            run_purpose=RunPurpose.PRODUCTION,
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
            trigger_medium=TriggerMedium.API,
            run_purpose=RunPurpose.PRODUCTION,
            user_id=user_id,
            thread_id=thread_id,
        ))

    async def dispatch_direct(
        self,
        release_id: uuid.UUID,
        prompt: str,
        user_id: str,
        thread_id: uuid.UUID,
        trigger_medium: TriggerMedium = TriggerMedium.API,
        run_purpose: RunPurpose = RunPurpose.PRODUCTION,
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
            trigger_medium=TriggerMedium.UI,
            run_purpose=RunPurpose.DRAFT_TEST,
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
            trigger_medium=TriggerMedium.UI,
            run_purpose=RunPurpose.INTERNAL_BUILDER,
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
            trigger_medium=TriggerMedium.UI,
            run_purpose=RunPurpose.DEBUG,
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
        # SELECT ... FOR UPDATE prevents concurrent retries on the same run
        run = (
            await self.db.execute(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if not run:
            raise NotFoundError("Agent run not found", code="AGENT_RUN_NOT_FOUND", data={"run_id": str(run_id)})
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

        # Fire engine in background (with error envelope, same as dispatch path)
        from app.services.execution_launcher import ExecutionLauncher, LaunchSpec

        launcher = ExecutionLauncher()
        try:
            auto_approve = True
            if run.task_id:
                task = (await self.db.execute(select(Task).where(Task.id == run.task_id))).scalar_one_or_none()
                if task:
                    auto_approve = task.auto_approve
            await launcher.launch(LaunchSpec(
                execution=execution,
                run=run,
                release=release,
                version=version,
                agent=agent,
                workspace_id=run.workspace_id,
                prompt=run.goal or "",
                auto_approve=auto_approve,
            ))
        except Exception as exc:
            logger.error(f"[Orchestrator] launcher.launch failed for retry: {exc}")
            await self._publish_launch_failure(execution, run.id, run.workspace_id, exc)

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
            from app.services.execution_launcher import ExecutionLauncher, LaunchSpec

            launcher = ExecutionLauncher()
            await launcher.launch(LaunchSpec(
                execution=execution,
                run=run,
                version=spec.version,
                agent=spec.agent,
                workspace_id=spec.workspace_id,
                prompt=spec.prompt,
                release=spec.release,
                engine_kind_override=spec.engine_kind_override,
                definition_kind_override=spec.definition_kind_override,
                definition_payload_override=spec.definition_payload_override,
            ))
        except Exception as exc:
            logger.error(f"[Orchestrator] launcher.launch failed: {exc}")
            await self._publish_launch_failure(execution, run.id, spec.workspace_id, exc)
            await self.db.refresh(run)

        return run

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    async def _publish_launch_failure(
        self,
        execution: Execution,
        run_id: uuid.UUID,
        workspace_id: uuid.UUID,
        exc: Exception,
    ) -> None:
        app_error = normalize_app_error(exc, default_code="EXECUTION_FAILED", source="engine")
        error_payload = app_error.to_payload()
        error_payload.setdefault("data", {})["reason"] = "engine_fire_failed"
        await execution_event_bus.publish(
            ExecutionEventEnvelope(
                execution_id=execution.id,
                run_id=run_id,
                workspace_id=workspace_id,
                event_type=ExecutionEventType.EXECUTION_COMPLETED,
                payload={"status": "failed", "error": error_payload, "result_summary": str(exc)[:2000]},
                terminal_status="failed",
                error=error_payload,
                result_summary=str(exc)[:2000],
            ),
            self.db,
        )

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

