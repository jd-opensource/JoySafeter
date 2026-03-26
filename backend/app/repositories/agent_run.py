"""
AgentRun repository helpers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, AgentRunEvent, AgentRunSnapshot, AgentRunStatus

from .base import BaseRepository


class AgentRunRepository(BaseRepository[AgentRun]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentRun, db)

    async def get_by_id_and_user(self, run_id: uuid.UUID, user_id: str) -> Optional[AgentRun]:
        result = await self.db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_snapshot(self, run_id: uuid.UUID) -> Optional[AgentRunSnapshot]:
        result = await self.db.execute(select(AgentRunSnapshot).where(AgentRunSnapshot.run_id == run_id))
        return result.scalar_one_or_none()

    async def list_events_after(
        self, run_id: uuid.UUID, after_seq: int = 0, limit: int = 500
    ) -> Sequence[AgentRunEvent]:
        result = await self.db.execute(
            select(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == run_id,
                AgentRunEvent.seq > after_seq,
            )
            .order_by(AgentRunEvent.seq.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_run_for_update(self, run_id: uuid.UUID, user_id: Optional[str] = None) -> Optional[AgentRun]:
        query = select(AgentRun).where(AgentRun.id == run_id)
        if user_id is not None:
            query = query.where(AgentRun.user_id == user_id)
        result = await self.db.execute(query.with_for_update())
        return result.scalar_one_or_none()

    async def find_latest_active_skill_creator_run(
        self,
        *,
        user_id: str,
        graph_id: uuid.UUID,
        thread_id: Optional[str] = None,
    ) -> Optional[AgentRun]:
        return await self.find_latest_active_run(
            user_id=user_id,
            agent_name="skill_creator",
            graph_id=graph_id,
            thread_id=thread_id,
        )

    async def find_latest_active_run(
        self,
        *,
        user_id: str,
        agent_name: str,
        graph_id: uuid.UUID,
        thread_id: Optional[str] = None,
    ) -> Optional[AgentRun]:
        active_statuses = (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.INTERRUPT_WAIT)
        query = select(AgentRun).where(
            AgentRun.user_id == user_id,
            AgentRun.agent_name == agent_name,
            AgentRun.graph_id == graph_id,
            AgentRun.status.in_(active_statuses),
        )
        if thread_id:
            query = query.where(AgentRun.thread_id == thread_id)
        result = await self.db.execute(query.order_by(desc(AgentRun.updated_at)).limit(1))
        return result.scalar_one_or_none()

    async def list_recent_runs_for_user(
        self,
        *,
        user_id: str,
        run_type: Optional[str] = None,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> Sequence[AgentRun]:
        query = select(AgentRun).where(AgentRun.user_id == user_id)
        if run_type:
            query = query.where(AgentRun.run_type == run_type)
        if agent_name:
            query = query.where(AgentRun.agent_name == agent_name)
        if status:
            query = query.where(AgentRun.status == status)
        if search:
            query = query.where(AgentRun.title.ilike(f"%{search}%"))
        result = await self.db.execute(query.order_by(desc(AgentRun.updated_at)).limit(limit))
        return result.scalars().all()

    async def list_recoverable_stale_runs(
        self,
        *,
        stale_before: datetime,
    ) -> Sequence[AgentRun]:
        recoverable_statuses = (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING)
        result = await self.db.execute(
            select(AgentRun)
            .where(
                AgentRun.status.in_(recoverable_statuses),
                or_(
                    and_(
                        AgentRun.last_heartbeat_at.is_(None),
                        AgentRun.updated_at < stale_before,
                    ),
                    AgentRun.last_heartbeat_at < stale_before,
                ),
            )
            .order_by(desc(AgentRun.updated_at))
        )
        return result.scalars().all()
