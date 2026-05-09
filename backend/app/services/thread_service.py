"""
ThreadService — manages Thread lifecycle.
"""

from __future__ import annotations

import uuid
from typing import List

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.models.agent_run import AgentRun
from app.models.thread import Thread
from app.repositories.thread import ThreadRepository
from app.schemas.thread import CreateThreadRequest, UpdateThreadRequest
from app.services.execution_orchestrator import ACTIVE_RUN_STATUSES


class ThreadService:
    """Manages Thread entities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.thread_repo = ThreadRepository(db)

    # ---- Thread CRUD ----

    async def list_threads(self, agent_id: uuid.UUID) -> List[Thread]:
        return await self.thread_repo.list_by_agent(agent_id)

    async def get_thread(self, thread_id: uuid.UUID) -> Thread:
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundError("Thread not found", code="THREAD_NOT_FOUND", data={"thread_id": str(thread_id)})
        return thread

    async def create_thread(
        self,
        workspace_id: uuid.UUID,
        user_id: str,
        data: CreateThreadRequest,
    ) -> Thread:
        thread = await self.thread_repo.create(
            {
                "agent_id": data.agent_id,
                "workspace_id": workspace_id,
                "title": data.title,
                "status": "active",
                "created_by": user_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(thread)
        logger.info(f"Created thread {thread.id} for agent {data.agent_id}")
        return thread

    async def update_thread(
        self,
        thread_id: uuid.UUID,
        data: UpdateThreadRequest,
    ) -> Thread:
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundError("Thread not found", code="THREAD_NOT_FOUND", data={"thread_id": str(thread_id)})

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return thread

        updated = await self.thread_repo.update(thread_id, update_data)
        assert updated is not None
        await self.db.commit()
        await self.db.refresh(updated)
        return updated

    async def archive_thread(self, thread_id: uuid.UUID) -> Thread:
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundError("Thread not found", code="THREAD_NOT_FOUND", data={"thread_id": str(thread_id)})

        # Refuse to archive while a run is in flight — otherwise we'd kill a
        # live container out from under the engine.
        active_run_id = (
            await self.db.execute(
                select(AgentRun.id).where(
                    AgentRun.thread_id == thread_id,
                    AgentRun.status.in_(ACTIVE_RUN_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if active_run_id:
            raise InvalidRequestError(
                "Cannot archive a thread with an active run",
                code="THREAD_ACTIVE_RUN_EXISTS",
                data={"thread_id": str(thread_id), "run_id": str(active_run_id)},
            )

        updated = await self.thread_repo.update(thread_id, {"status": "archived"})
        assert updated is not None
        await self.db.commit()
        await self.db.refresh(updated)

        # Tear down the cached container + clear DB binding.
        from app.core.agent.cli_backends.container_pool import container_pool

        try:
            await container_pool.evict(thread_id)
        except Exception as exc:
            logger.warning(f"[thread:{thread_id}] container_pool.evict failed: {exc}")

        logger.info(f"Archived thread {thread_id}")
        return updated

    # ---- Thread Events (aggregation) ----

    async def list_thread_events(
        self,
        thread_id: uuid.UUID,
        after_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> tuple[list[dict], int]:
        """Aggregate execution events across all runs in a thread."""
        from sqlalchemy import and_, func, not_, select

        from app.models.agent_run import AgentRun
        from app.models.execution import Execution, ExecutionEvent

        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundError("Thread not found", code="THREAD_NOT_FOUND", data={"thread_id": str(thread_id)})

        base_filter = and_(
            AgentRun.thread_id == thread_id,
            not_(ExecutionEvent.event_type.like("copilot_%")),
        )

        count_q = (
            select(func.count(ExecutionEvent.id))
            .join(Execution, ExecutionEvent.execution_id == Execution.id)
            .join(AgentRun, Execution.run_id == AgentRun.id)
            .where(base_filter)
        )
        total = (await self.db.execute(count_q)).scalar() or 0

        query = (
            select(
                ExecutionEvent.id,
                ExecutionEvent.execution_id,
                ExecutionEvent.sequence_no,
                ExecutionEvent.event_type,
                ExecutionEvent.payload,
                ExecutionEvent.created_at,
                Execution.status.label("execution_status"),
                AgentRun.id.label("run_id"),
            )
            .join(Execution, ExecutionEvent.execution_id == Execution.id)
            .join(AgentRun, Execution.run_id == AgentRun.id)
            .where(base_filter)
            .order_by(AgentRun.created_at, Execution.attempt_index, ExecutionEvent.sequence_no)
        )

        if after_id:
            ref_event = (
                await self.db.execute(select(ExecutionEvent.created_at).where(ExecutionEvent.id == after_id))
            ).scalar()
            if ref_event:
                query = query.where(ExecutionEvent.created_at > ref_event)

        query = query.limit(limit)
        rows = (await self.db.execute(query)).mappings().all()
        return [dict(r) for r in rows], total
