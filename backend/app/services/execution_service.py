"""
Service layer for CLI agent executions.
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundException
from app.models.execution import (
    Execution,
    ExecutionEvent,
)
from app.repositories.execution import ExecutionRepository, ExecutionEventRepository
from app.utils.datetime import utc_now

TERMINAL_EXECUTION_STATUSES = frozenset({"completed", "failed", "cancelled"})


class ExecutionService:
    """Manages execution lifecycle and event appending."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExecutionRepository(db)
        self.event_repo = ExecutionEventRepository(db)

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
        result = await self.db.execute(
            select(Execution).where(Execution.id == execution_id).with_for_update()
        )
        execution = result.scalar_one_or_none()
        if not execution:
            return None

        now = utc_now()
        execution.status = status
        if error_code is not None:
            execution.error_code = error_code
        if error_message is not None:
            execution.error_message = error_message
        if container_id is not None:
            execution.runtime_session_ref = container_id
        if session_id is not None:
            execution.runtime_session_ref = session_id
        if result_summary is not None:
            execution.metrics = result_summary

        if status == "running" and not execution.started_at:
            execution.started_at = now
        if status in TERMINAL_EXECUTION_STATUSES:
            execution.ended_at = now

        await self.db.commit()

        from app.websocket.execution_subscription_manager import execution_subscription_manager
        await execution_subscription_manager.broadcast_event(
            str(execution_id),
            {"type": "execution_status", "execution_id": str(execution_id), "status": status},
        )

        return execution

    async def _next_sequence_no(self, execution_id: uuid.UUID) -> int:
        """Get the next sequence number for an execution's events."""
        result = await self.db.execute(
            select(func.coalesce(func.max(ExecutionEvent.sequence_no), 0)).where(
                ExecutionEvent.execution_id == execution_id
            )
        )
        return (result.scalar() or 0) + 1

    async def append_event(
        self,
        *,
        execution_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
        commit: bool = True,
    ) -> ExecutionEvent:
        seq = await self._next_sequence_no(execution_id)
        event = ExecutionEvent(
            execution_id=execution_id,
            sequence_no=seq,
            event_type=event_type,
            payload=payload,
        )
        self.db.add(event)

        if commit:
            await self.db.commit()
            await self.db.refresh(event)
            from app.websocket.execution_subscription_manager import execution_subscription_manager
            await execution_subscription_manager.broadcast_event(
                str(execution_id),
                {
                    "type": "event",
                    "execution_id": str(execution_id),
                    "seq": seq,
                    "event_type": event_type,
                    "data": payload,
                    "created_at": str(event.created_at),
                },
            )
        else:
            await self.db.flush()
            await self.db.refresh(event)

        return event

    async def batch_append_events(
        self,
        *,
        execution_id: uuid.UUID,
        events: list[dict[str, Any]],
    ) -> list[ExecutionEvent]:
        """Append multiple events in a single commit."""
        results: list[ExecutionEvent] = []
        for evt in events:
            result = await self.append_event(
                execution_id=execution_id,
                event_type=evt["event_type"],
                payload=evt["payload"],
                commit=False,
            )
            results.append(result)

        await self.db.commit()

        from app.websocket.execution_subscription_manager import execution_subscription_manager
        for saved_event in results:
            await execution_subscription_manager.broadcast_event(
                str(execution_id),
                {
                    "type": "event",
                    "execution_id": str(execution_id),
                    "seq": saved_event.sequence_no,
                    "event_type": saved_event.event_type,
                    "data": saved_event.payload,
                    "created_at": str(saved_event.created_at),
                },
            )

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
