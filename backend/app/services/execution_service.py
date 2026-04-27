"""
Service layer for CLI agent executions.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, List, Mapping, Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import NotFoundError
from app.core.events import ExecutionEventEnvelope, execution_event_bus
from app.core.events.event_types import ExecutionEventType
from app.core.ports.execution import EventContext
from app.core.state_machines.definitions import EXECUTION_TERMINAL
from app.models.execution import (
    Execution,
    ExecutionEvent,
)
from app.repositories.execution import ExecutionRepository, ExecutionEventRepository
from app.utils.datetime import utc_now

TERMINAL_EXECUTION_STATUSES = EXECUTION_TERMINAL


class ExecutionService:
    """Manages execution lifecycle and event appending."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExecutionRepository(db)
        self.event_repo = ExecutionEventRepository(db)
        self._event_ctx: Optional[EventContext] = None

    def set_event_context(self, ctx: EventContext) -> None:
        """Inject run-level metadata so append_event can build full envelopes."""
        self._event_ctx = ctx

    async def get_execution_internal(self, execution_id: uuid.UUID) -> Optional[Execution]:
        """Internal use — no user-scope check, no FOR UPDATE lock."""
        result = await self.db.execute(select(Execution).where(Execution.id == execution_id))
        return result.scalar_one_or_none()

    async def get_execution(self, execution_id: uuid.UUID, user_id: Optional[str] = None) -> Optional[Execution]:
        """Get execution by ID (user_id kept for API compatibility; no row-level auth here).

        Raises NotFoundError when called without user_id (API path) so callers get a clean 404.
        When user_id is provided (WebSocket path) returns None on miss.
        """
        execution = await self.get_execution_internal(execution_id)
        if execution is None and user_id is None:
            raise NotFoundError(
                "Execution not found",
                code="EXECUTION_NOT_FOUND",
                data={"execution_id": str(execution_id)},
            )
        return execution

    async def list_events_after(
        self, execution_id: uuid.UUID, user_id: str, after_seq: int = 0, limit: int = 500
    ) -> list[ExecutionEvent]:
        execution = await self.get_execution_internal(execution_id)
        if not execution:
            return []
        result = await self.db.execute(
            select(ExecutionEvent)
            .where(
                ExecutionEvent.execution_id == execution_id,
                ExecutionEvent.sequence_no > after_seq,
            )
            .order_by(ExecutionEvent.sequence_no.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

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
        """Publish a status-change event through the bus.

        StateTransitionSubscriber handles the actual DB transition and
        metadata writes in Phase 1 of the bus pipeline.
        """
        ctx = self._event_ctx
        if ctx is None:
            # Fallback for callers without event context (e.g. reaper)
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

        # Return the updated row
        if execution is None:
            execution = (await self.db.execute(
                select(Execution).where(Execution.id == execution_id)
            )).scalar_one_or_none()
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
            raise RuntimeError(
                "EventContext not set. Call set_event_context() before appending events."
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
        """Append multiple events in a single transaction via the event bus."""
        if self._event_ctx is None:
            raise RuntimeError(
                "EventContext not set. Call set_event_context() before appending events."
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
        result_summary: dict | None = None,
        error: Mapping[str, Any] | None = None,
        session_id: str | None = None,
    ) -> None:
        """Publish a single EXECUTION_COMPLETED event with full metadata.

        StateTransitionSubscriber handles Execution + Run terminal transitions.
        """
        if self._event_ctx is None:
            raise RuntimeError(
                "EventContext not set. Call set_event_context() before completing."
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

    async def list_executions(self, run_id: uuid.UUID) -> List[Execution]:
        """List all executions for a run."""
        return await self.repo.list_by_run(run_id)

    async def list_events(self, execution_id: uuid.UUID) -> List[ExecutionEvent]:
        """List all events for an execution."""
        return await self.event_repo.list_by_execution(execution_id)

    async def get_snapshot(self, execution_id: uuid.UUID, user_id: Optional[str] = None):
        """Return a lightweight snapshot of the execution for WebSocket catch-up.

        Returns an object with ``last_seq`` and ``projection`` attributes.
        Falls back to a synthetic snapshot built from the execution row when no
        dedicated snapshot table exists.
        """
        execution = await self.get_execution_internal(execution_id)
        if not execution:
            return None

        # Compute last_seq from the events table
        result = await self.db.execute(
            select(func.coalesce(func.max(ExecutionEvent.sequence_no), 0)).where(
                ExecutionEvent.execution_id == execution_id
            )
        )
        last_seq = result.scalar() or 0

        # Build a minimal projection from the execution row itself
        class _Snapshot:
            pass

        snap = _Snapshot()
        snap.last_seq = last_seq
        snap.projection = {
            "status": execution.status if isinstance(execution.status, str) else execution.status.value,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "ended_at": execution.ended_at.isoformat() if execution.ended_at else None,
            "error": execution.error,
        }
        return snap

    async def create_execution(
        self,
        *,
        run_id: uuid.UUID,
        runtime_type: str = "claude_code",
        parent_execution_id: Optional[uuid.UUID] = None,
    ) -> Execution:
        """Create an Execution record attached to an existing AgentRun."""
        max_attempt = await ExecutionRepository(self.db).get_max_attempt(run_id)
        execution = Execution(
            run_id=run_id,
            attempt_index=max_attempt + 1,
            executor_kind=runtime_type,
            status="pending",
            parent_execution_id=parent_execution_id,
        )
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def reap_stale_executions(
        self,
        thresholds: list[tuple[tuple[str, ...], timedelta]],
    ) -> int:
        """Discover and reap stale executions.

        For each (statuses, threshold) pair:
          1. Query stale executions           → Repository
          2. Cancel active runtime session    → session_registry
          3. Mark execution as failed         → self.mark_status (bus)
          4. Mark parent run as failed        → RUN_STATUS_CHANGE (bus)

        Args:
            thresholds: list of ``((status, ...), timedelta)`` pairs defining
                which execution statuses to scan and how old they must be.

        Returns:
            Total number of reaped executions.
        """
        from app.core.agent.cli_backends.session_registry import session_registry
        from app.models.agent_run import AgentRun

        now = utc_now()
        total = 0

        for statuses, threshold in thresholds:
            stale = await self.repo.list_recoverable_stale(
                statuses=statuses,
                stale_before=now - threshold,
            )
            for execution in stale:
                try:
                    # 1. Cancel active session if any
                    session = session_registry.get(execution.id)
                    if session:
                        await session.cancel()

                    # 2. Load run for envelope metadata
                    run = (await self.db.execute(
                        select(AgentRun).where(AgentRun.id == execution.run_id)
                    )).scalar_one_or_none()

                    # 3. Atomically mark execution + run as failed
                    error_msg = f"No heartbeat for {int(threshold.total_seconds() // 60)}+ minutes"
                    envelope = ExecutionEventEnvelope(
                        execution_id=execution.id,
                        run_id=execution.run_id,
                        workspace_id=run.workspace_id if run else uuid.UUID(int=0),
                        event_type=ExecutionEventType.EXECUTION_COMPLETED,
                        payload={
                            "status": "failed",
                            "error": {
                                "code": "STALE_REAPED",
                                "message": error_msg,
                                "data": {
                                    "reason": "stale_execution",
                                },
                            },
                            "result_summary": "Reaped: stale execution",
                        },
                        terminal_status="failed",
                        error={
                            "code": "STALE_REAPED",
                            "message": error_msg,
                            "data": {
                                "reason": "stale_execution",
                            },
                        },
                        result_summary="Reaped: stale execution",
                        trigger_source=run.trigger_source if run else None,
                        thread_id=run.thread_id if run else None,
                        task_id=run.task_id if run else None,
                    )
                    await execution_event_bus.publish(envelope, self.db)

                    total += 1
                    logger.info(
                        f"Reaped stale execution {execution.id} "
                        f"(status={execution.status}, "
                        f"age={now - (execution.started_at or execution.created_at)})"
                    )
                except Exception as exc:
                    logger.warning(f"Failed to reap execution {execution.id}: {exc}")

        return total
