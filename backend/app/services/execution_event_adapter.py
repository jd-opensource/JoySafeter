"""
ExecutionEventAdapter — implements ExecutionEventPort.

Bridges core/ execution runners to the event bus without core/ importing services/.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import InternalServiceError
from app.core.events import ExecutionEventEnvelope, execution_event_bus
from app.core.events.event_types import ExecutionEventType
from app.core.ports.execution import EventContext
from app.models.execution import Execution, ExecutionEvent


class ExecutionEventAdapter:
    """Implements ExecutionEventPort — publishes execution events through the bus."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._event_ctx: Optional[EventContext] = None

    def set_event_context(self, ctx: EventContext) -> None:
        self._event_ctx = ctx

    async def mark_status(
        self,
        *,
        execution_id: uuid.UUID,
        status: str,
        container_id: Optional[str] = None,
        session_id: Optional[str] = None,
        error: Mapping[str, Any] | None = None,
        result_summary: Optional[dict[str, Any]] = None,
    ) -> Optional[Execution]:
        ctx = self._event_ctx
        if ctx is None:
            from app.models.agent_run import AgentRun

            result = await self.db.execute(
                select(Execution, AgentRun.workspace_id)
                .join(AgentRun, Execution.run_id == AgentRun.id)
                .where(Execution.id == execution_id)
            )
            row = result.one_or_none()
            if not row:
                return None
            execution, ws_id = row
            ctx = EventContext(
                run_id=execution.run_id,
                workspace_id=ws_id,
            )
        else:
            execution = None

        envelope = ExecutionEventEnvelope(
            execution_id=execution_id,
            run_id=ctx.run_id,
            workspace_id=ctx.workspace_id,
            event_type=ExecutionEventType.EXECUTION_STATUS_CHANGE,
            payload={"status": status},
            trigger_source=ctx.trigger_source,
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            target_status=status,
            error=dict(error) if error is not None else None,
            container_id=container_id or session_id,
            metrics=result_summary,
        )
        await execution_event_bus.publish(envelope, self.db)

        if execution is None:
            execution = (
                await self.db.execute(select(Execution).where(Execution.id == execution_id))
            ).scalar_one_or_none()
        else:
            await self.db.refresh(execution)
        return execution

    async def append_event(
        self,
        *,
        execution_id: uuid.UUID,
        event_type: ExecutionEventType,
        payload: dict[str, Any],
    ) -> ExecutionEvent:
        if self._event_ctx is None:
            raise InternalServiceError(
                "Execution event context is not initialized",
                code="EXECUTION_EVENT_CONTEXT_MISSING",
                data={"execution_id": str(execution_id)},
            )

        envelope = ExecutionEventEnvelope(
            execution_id=execution_id,
            run_id=self._event_ctx.run_id,
            workspace_id=self._event_ctx.workspace_id,
            event_type=event_type,
            payload=payload,
            trigger_source=self._event_ctx.trigger_source,
            thread_id=self._event_ctx.thread_id,
            task_id=self._event_ctx.task_id,
        )
        await execution_event_bus.publish(envelope, self.db)

        return ExecutionEvent(
            execution_id=execution_id,
            sequence_no=envelope.seq,
            event_type=event_type,
            payload=payload,
        )

    async def batch_append_events(
        self,
        *,
        execution_id: uuid.UUID,
        events: list[dict[str, Any]],
    ) -> list[ExecutionEvent]:
        if self._event_ctx is None:
            raise InternalServiceError(
                "Execution event context is not initialized",
                code="EXECUTION_EVENT_CONTEXT_MISSING",
                data={"execution_id": str(execution_id)},
            )

        envelopes = [
            ExecutionEventEnvelope(
                execution_id=execution_id,
                run_id=self._event_ctx.run_id,
                workspace_id=self._event_ctx.workspace_id,
                event_type=evt["event_type"],
                payload=evt["payload"],
                trigger_source=self._event_ctx.trigger_source,
                thread_id=self._event_ctx.thread_id,
                task_id=self._event_ctx.task_id,
            )
            for evt in events
        ]
        await execution_event_bus.publish_batch(envelopes, self.db)

        return [
            ExecutionEvent(
                execution_id=execution_id,
                sequence_no=env.seq,
                event_type=env.event_type,
                payload=env.payload,
            )
            for env in envelopes
        ]

    async def complete_execution(
        self,
        *,
        execution_id: uuid.UUID,
        terminal_status: str,
        result_summary: Optional[dict[str, Any]] = None,
        error: Mapping[str, Any] | None = None,
        session_id: Optional[str] = None,
    ) -> None:
        if self._event_ctx is None:
            raise InternalServiceError(
                "Execution event context is not initialized",
                code="EXECUTION_EVENT_CONTEXT_MISSING",
                data={"execution_id": str(execution_id)},
            )

        envelope = ExecutionEventEnvelope(
            execution_id=execution_id,
            run_id=self._event_ctx.run_id,
            workspace_id=self._event_ctx.workspace_id,
            event_type=ExecutionEventType.EXECUTION_COMPLETED,
            payload={
                "status": terminal_status,
                "error": dict(error) if error is not None else None,
                "result_summary": result_summary,
            },
            terminal_status=terminal_status,
            error=dict(error) if error is not None else None,
            container_id=session_id,
            metrics=result_summary,
            trigger_source=self._event_ctx.trigger_source,
            thread_id=self._event_ctx.thread_id,
            task_id=self._event_ctx.task_id,
        )
        await execution_event_bus.publish(envelope, self.db)
