"""
Service layer for CLI agent executions.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def get_execution(self, execution_id: uuid.UUID, user_id: str) -> Optional[Execution]:
        """Get execution by ID (user_id kept for API compatibility; no row-level auth here)."""
        return await self.get_execution_internal(execution_id)

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
