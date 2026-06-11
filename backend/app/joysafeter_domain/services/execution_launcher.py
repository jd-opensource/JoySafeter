"""
ExecutionLauncher — owns the engine-fire lifecycle.

Trace → Context → ObservationCollector → Engine.start → Error recovery.

All paths that fire an engine (dispatch, retry, future spawn) use this
single entry point, guaranteeing consistent trace creation, OTel setup,
and error handling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import AppError, normalize_app_error
from app.joysafeter_domain.engine.protocol import ExecutionContext
from app.joysafeter_domain.engine.registry import engine_registry
from app.joysafeter_worker.events import ExecutionEventEnvelope, execution_event_bus
from app.joysafeter_worker.events.event_types import ExecutionEventType
from app.joysafeter_shared.observation.model import Trace
from app.joysafeter_domain.models.agent import Agent, AgentRelease, AgentVersion
from app.joysafeter_domain.models.agent_run import AgentRun
from app.joysafeter_domain.models.execution import Execution
from app.joysafeter_shared.utils.credentials import build_agent_credentials
from app.joysafeter_shared.utils.datetime import utc_now
from app.joysafeter_shared.utils.safe_task import safe_create_task


@dataclass
class LaunchSpec:
    """Everything needed to fire an engine for an existing Execution row."""

    execution: Execution
    run: AgentRun
    version: AgentVersion
    agent: Agent
    project_id: str
    prompt: str
    auto_approve: bool = True
    release: AgentRelease | None = None
    engine_kind_override: str | None = None
    definition_payload_override: dict | None = None


class ExecutionLauncher:
    """Owns the engine-fire lifecycle: context → trace → collector → engine → error handling."""

    async def launch(self, spec: LaunchSpec) -> None:
        """Fire engine in a background task with full trace + error handling."""
        run = spec.run
        credentials = build_agent_credentials(spec.agent)

        run_meta = dict(
            trigger_medium=run.trigger_medium,
            run_purpose=run.run_purpose,
            thread_id=run.thread_id,
            task_id=run.task_id,
        )

        runtime_binding = spec.release.runtime_binding if spec.release else {}
        engine_kind = spec.engine_kind_override or spec.execution.engine_kind
        engine = engine_registry.get(engine_kind)
        def_payload = spec.definition_payload_override or spec.version.definition_payload

        safe_create_task(
            self._run_engine(
                execution=spec.execution,
                run=run,
                agent=spec.agent,
                version=spec.version,
                project_id=spec.project_id,
                prompt=spec.prompt,
                credentials=credentials,
                auto_approve=spec.auto_approve,
                run_meta=run_meta,
                runtime_binding=runtime_binding,
                engine=engine,
                engine_kind=engine_kind,
                def_payload=def_payload,
            ),
            name=f"engine-{spec.execution.id}",
        )

    async def _run_engine(
        self,
        *,
        execution: Execution,
        run: AgentRun,
        agent: Agent,
        version: AgentVersion,
        project_id: str,
        prompt: str,
        credentials: dict,
        auto_approve: bool,
        run_meta: dict,
        runtime_binding: dict,
        engine: Any,
        engine_kind: str,
        def_payload: dict,
    ) -> None:
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_shared.observation import ObservationCollector
        from app.joysafeter_shared.observation.types import ObservationLevel
        from app.joysafeter_domain.services.model_service import ModelService
        from app.joysafeter_domain.services.runner_factory import create_execution_runner
        from app.joysafeter_api.websocket.execution_subscription_manager import execution_subscription_manager

        ctx = None
        try:
            async with AsyncSessionLocal() as db:
                await self._insert_trace(
                    db,
                    execution=execution,
                    run=run,
                    agent_name=agent.name,
                    agent_version_id=version.id,
                    prompt=prompt,
                )

                ctx = ExecutionContext(
                    db=db,
                    execution_id=execution.id,
                    run_id=run.id,
                    project_id=project_id,
                    credentials=credentials,
                    auto_approve=auto_approve,
                    model_port=ModelService(db),
                    runner_factory=create_execution_runner,
                )
                self._wire_context(ctx, **run_meta)

                async def _db_factory():
                    return AsyncSessionLocal()

                async def _broadcast(exec_id: Any, message: dict) -> None:
                    await execution_subscription_manager.broadcast_event(str(exec_id), message)

                collector = ObservationCollector(
                    trace_id=execution.id,
                    execution_id=execution.id,
                    project_id=project_id,
                    db_session_factory=_db_factory,
                    broadcast_fn=_broadcast,
                )
                ctx.collector = collector

                try:
                    await engine.start(
                        ctx,
                        release_runtime_binding=runtime_binding,
                        engine_kind=engine_kind,
                        definition_payload=def_payload,
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
            logger.error(f"[Launcher] Engine failed for execution {execution.id}: {exc}")
            # ctx.db is closed here (async with exited), so we need a fresh
            # session to publish the failure event through the event bus.
            try:
                async with AsyncSessionLocal() as err_db:
                    app_error = normalize_app_error(
                        exc,
                        default_code="EXECUTION_ENGINE_FAILED",
                        default_message="Engine execution failed",
                        default_data={"execution_id": str(execution.id), "run_id": str(run.id)},
                        source="engine",
                    )
                    error_payload = app_error.to_payload() if app_error else None
                    await execution_event_bus.publish(
                        ExecutionEventEnvelope(
                            execution_id=execution.id,
                            run_id=run.id,
                            project_id=project_id,
                            event_type=ExecutionEventType.EXECUTION_COMPLETED,
                            payload={"status": "failed", "error": error_payload},
                            terminal_status="failed",
                            error=error_payload,
                            result_summary=str(exc)[:2000],
                            trigger_medium=run_meta.get("trigger_medium"),
                            run_purpose=run_meta.get("run_purpose"),
                            thread_id=run_meta.get("thread_id"),
                            task_id=run_meta.get("task_id"),
                        ),
                        err_db,
                    )
            except Exception as cleanup_exc:
                logger.error(f"[Launcher] Failed to mark execution as failed: {cleanup_exc}")

    def _wire_context(
        self,
        ctx: ExecutionContext,
        *,
        trigger_medium: str | None = None,
        run_purpose: str | None = None,
        thread_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> None:
        def _envelope(**overrides: Any) -> ExecutionEventEnvelope:
            return ExecutionEventEnvelope(
                execution_id=ctx.execution_id,
                run_id=ctx.run_id,
                project_id=ctx.project_id,
                trigger_medium=trigger_medium,
                run_purpose=run_purpose,
                thread_id=thread_id,
                task_id=task_id,
                **overrides,
            )

        class _Bridge:
            async def emit(self, event_type: ExecutionEventType, payload: dict) -> None:
                await execution_event_bus.publish(
                    _envelope(event_type=event_type, payload=payload),
                    ctx.db,
                )

            async def update_status(self, status: str) -> None:
                await execution_event_bus.publish(
                    _envelope(
                        event_type=ExecutionEventType.EXECUTION_STATUS_CHANGE,
                        payload={"status": status},
                        target_status=status,
                    ),
                    ctx.db,
                )

            async def complete(
                self,
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

        ctx._event_bridge = _Bridge()

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
        trace = Trace(
            id=execution.id,
            name=agent_name,
            project_id=run.project_id or "",
            start_time=utc_now(),
            status="running",
            execution_id=execution.id,
            agent_version_id=agent_version_id,
            user_id=(
                uuid.UUID(run.created_by) if run.created_by and isinstance(run.created_by, str) else run.created_by
            ),
            session_id=str(run.thread_id),
            input={"prompt": prompt},
        )
        db.add(trace)
        await db.flush()
