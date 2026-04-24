"""
Service layer for CLI agent executions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, List, Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundException
from app.core.events import ExecutionEventEnvelope, execution_event_bus
from app.core.events.event_types import ExecutionEventType
from app.core.state_machines.definitions import EXECUTION_TERMINAL
from app.models.execution import (
    Execution,
    ExecutionEvent,
)
from app.repositories.execution import ExecutionRepository, ExecutionEventRepository
from app.utils.datetime import utc_now

TERMINAL_EXECUTION_STATUSES = EXECUTION_TERMINAL


@dataclass
class EventContext:
    """Run-level metadata injected by the caller (e.g. ExecutionRunner).

    Allows append_event to construct a complete ExecutionEventEnvelope
    without querying the DB for run metadata on every event.
    """
    run_id: uuid.UUID
    workspace_id: uuid.UUID
    trigger_source: Optional[str] = None
    thread_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None


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

        Raises NotFoundException when called without user_id (API path) so callers get a clean 404.
        When user_id is provided (WebSocket path) returns None on miss.
        """
        execution = await self.get_execution_internal(execution_id)
        if execution is None and user_id is None:
            raise NotFoundException(f"Execution {execution_id} not found")
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
        user_id: Optional[str] = None,
        status: str,
        container_id: Optional[str] = None,
        session_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        result_summary: Optional[dict[str, Any]] = None,
    ) -> Optional[Execution]:
        """Publish a status-change event through the bus.

        StateTransitionSubscriber handles the actual DB transition and
        metadata writes in Phase 1 of the bus pipeline.
        """
        execution = (await self.db.execute(
            select(Execution).where(Execution.id == execution_id)
        )).scalar_one_or_none()
        if not execution:
            return None

        # Build event context — prefer injected context, fall back to execution row
        ctx = self._event_ctx
        if ctx is None:
            ctx = EventContext(
                run_id=execution.run_id,
                workspace_id=execution.workspace_id,
            )

        envelope = ExecutionEventEnvelope(
            execution_id=execution_id,
            run_id=ctx.run_id,
            workspace_id=ctx.workspace_id,
            event_type=ExecutionEventType.EXECUTION_STATUS_CHANGE,
            payload={"status": status},
            created_at=utc_now(),
            trigger_source=ctx.trigger_source,
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            target_status=status,
            error_code=error_code,
            error_message=error_message,
            container_id=container_id or session_id,
            metrics=result_summary,
        )
        await execution_event_bus.publish(envelope, self.db)

        # Refresh to return the updated row
        await self.db.refresh(execution)
        return execution

    async def append_event(
        self,
        *,
        execution_id: uuid.UUID,
        event_type: str,
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
            created_at=utc_now(),
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

        return results

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
        }
        return snap

    async def create_execution(
        self,
        *,
        user_id: str,
        workspace_id: uuid.UUID,
        source: str = "api",
        runtime_type: str = "claude_code",
        title: Optional[str] = None,
        parent_execution_id: Optional[uuid.UUID] = None,
    ) -> Execution:
        """Create a bare Execution record (used by coordinator sub-agent spawning).

        This creates an Execution that is not yet attached to an AgentRun.  The
        caller (coordinator_tools) is responsible for driving the runner directly.
        """
        execution = Execution(
            attempt_index=1,
            executor_kind=runtime_type,
            status="pending",
        )
        # Store optional metadata in the metrics JSON column if available
        meta: dict[str, Any] = {"source": source}
        if title:
            meta["title"] = title
        if parent_execution_id:
            meta["parent_execution_id"] = str(parent_execution_id)
        execution.metrics = meta

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
          3. Mark execution as failed         → self.mark_status
          4. Mark parent run as failed        → transition_run
          5. Sync task status                 → sync_task_from_run

        Args:
            thresholds: list of ``((status, ...), timedelta)`` pairs defining
                which execution statuses to scan and how old they must be.

        Returns:
            Total number of reaped executions.
        """
        from app.core.agent.cli_backends.session_registry import session_registry
        from app.core.state_machines.transitions import transition_run, sync_task_from_run
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

                    # 2. Mark execution failed
                    await self.mark_status(
                        execution_id=execution.id,
                        status="failed",
                        error_code="stale_reaped",
                        error_message=(
                            f"No heartbeat for {int(threshold.total_seconds() // 60)}+ minutes"
                        ),
                    )

                    # 3. Transition parent run to failed
                    run = (await self.db.execute(
                        select(AgentRun).where(AgentRun.id == execution.run_id)
                    )).scalar_one_or_none()
                    if run and run.status not in ("succeeded", "failed", "cancelled"):
                        await transition_run(run, "failed", self.db, "Reaped: stale execution")
                        await self.db.commit()
                        # 4. Sync task status from run
                        await sync_task_from_run(run, self.db)

                    total += 1
                    logger.info(
                        f"Reaped stale execution {execution.id} "
                        f"(status={execution.status}, "
                        f"age={now - (execution.started_at or execution.created_at)})"
                    )
                except Exception as exc:
                    logger.warning(f"Failed to reap execution {execution.id}: {exc}")

        return total
