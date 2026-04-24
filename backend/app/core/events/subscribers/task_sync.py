"""
TaskSyncSubscriber — Phase 2.

On execution_completed with a task_id, syncs the task status from the run.
Uses an independent DB session.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.envelope import ExecutionEventEnvelope
from app.core.events.subscriber import SubscriberPhase


class TaskSyncSubscriber:
    name = "task_sync"
    phase = SubscriberPhase.BROADCAST

    async def handle(
        self,
        envelope: ExecutionEventEnvelope,
        db: Optional[AsyncSession] = None,
    ) -> None:
        if envelope.event_type != "execution_completed":
            return
        if not envelope.task_id:
            return

        from app.core.database import AsyncSessionLocal
        from app.core.state_machines.transitions import sync_task_from_run
        from app.models.agent_run import AgentRun

        async with AsyncSessionLocal() as session:
            run = (await session.execute(
                select(AgentRun).where(AgentRun.id == envelope.run_id)
            )).scalar_one_or_none()
            if not run:
                logger.warning(f"[TaskSync] Run {envelope.run_id} not found")
                return
            await sync_task_from_run(run, session)
            await session.commit()
            logger.info(
                f"[TaskSync] Synced task {envelope.task_id} from run {envelope.run_id}"
            )
