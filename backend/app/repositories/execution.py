"""
Execution repository helpers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

# TODO: Phase 4/5 cleanup - ExecutionSnapshot, MissionExecutionStatus removed
# from app.models.execution import Execution, ExecutionEvent, ExecutionSnapshot, MissionExecutionStatus
from app.models.execution import Execution, ExecutionEvent
ExecutionSnapshot = None  # TODO: Phase 4/5 cleanup
MissionExecutionStatus = type("MissionExecutionStatus", (), {
    "QUEUED": "queued", "DISPATCHED": "dispatched", "RUNNING": "running",
    "INTERRUPT_WAIT": "interrupt_wait", "APPROVAL_WAIT": "approval_wait",
    "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"
})()

from .base import BaseRepository


class ExecutionRepository(BaseRepository[Execution]):
    def __init__(self, db: AsyncSession):
        super().__init__(Execution, db)

    async def get_by_id_and_user(self, execution_id: uuid.UUID, user_id: str) -> Optional[Execution]:
        result = await self.db.execute(
            select(Execution).where(
                Execution.id == execution_id,
                Execution.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, execution_id: uuid.UUID, user_id: Optional[str] = None) -> Optional[Execution]:
        query = select(Execution).where(Execution.id == execution_id)
        if user_id is not None:
            query = query.where(Execution.user_id == user_id)
        result = await self.db.execute(query.with_for_update())
        return result.scalar_one_or_none()

    async def get_snapshot(self, execution_id: uuid.UUID) -> Optional[ExecutionSnapshot]:
        result = await self.db.execute(select(ExecutionSnapshot).where(ExecutionSnapshot.execution_id == execution_id))
        return result.scalar_one_or_none()

    async def list_events_after(
        self, execution_id: uuid.UUID, after_seq: int = 0, limit: int = 500
    ) -> Sequence[ExecutionEvent]:
        result = await self.db.execute(
            select(ExecutionEvent)
            .where(
                ExecutionEvent.execution_id == execution_id,
                ExecutionEvent.seq > after_seq,
            )
            .order_by(ExecutionEvent.seq.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_by_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        mission_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> Sequence[Execution]:
        query = select(Execution).where(Execution.workspace_id == workspace_id)
        if user_id:
            query = query.where(Execution.user_id == user_id)
        if status:
            query = query.where(Execution.status == status)
        if source:
            query = query.where(Execution.source == source)
        if mission_id:
            query = query.where(Execution.mission_id == mission_id)
        result = await self.db.execute(query.order_by(desc(Execution.created_at)).limit(limit))
        return result.scalars().all()

    async def list_children(self, parent_execution_id: uuid.UUID) -> Sequence[Execution]:
        result = await self.db.execute(
            select(Execution).where(Execution.parent_execution_id == parent_execution_id).order_by(Execution.created_at)
        )
        return result.scalars().all()

    async def list_recoverable_stale(
        self,
        *,
        stale_before: datetime,
        statuses: tuple[MissionExecutionStatus, ...] | None = None,
    ) -> Sequence[Execution]:
        if statuses is None:
            statuses = (
                MissionExecutionStatus.QUEUED,
                MissionExecutionStatus.DISPATCHED,
                MissionExecutionStatus.RUNNING,
            )
        result = await self.db.execute(
            select(Execution)
            .where(
                Execution.status.in_(statuses),
                or_(
                    and_(
                        Execution.last_heartbeat_at.is_(None),
                        Execution.updated_at < stale_before,
                    ),
                    Execution.last_heartbeat_at < stale_before,
                ),
            )
            .order_by(desc(Execution.updated_at))
        )
        return result.scalars().all()
