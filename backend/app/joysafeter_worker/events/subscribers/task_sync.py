"""
TaskSyncSubscriber — Phase 2.

On execution_completed or run terminal status change, syncs the task status
from the run. Uses an independent DB session.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_worker.events.envelope import ExecutionEventEnvelope
from app.joysafeter_worker.events.event_types import ExecutionEventType
from app.joysafeter_worker.events.subscriber import SubscriberPhase
from app.joysafeter_domain.state_machines.definitions import RUN_TERMINAL

_HANDLED = {
    ExecutionEventType.EXECUTION_COMPLETED,
    ExecutionEventType.RUN_STATUS_CHANGE,
}


class TaskSyncSubscriber:
    name = "task_sync"
    phase = SubscriberPhase.BROADCAST

    async def handle(
        self,
        envelope: ExecutionEventEnvelope,
        db: Optional[AsyncSession] = None,
    ) -> None:
        if envelope.event_type not in _HANDLED:
            return

        if envelope.event_type == ExecutionEventType.RUN_STATUS_CHANGE:
            if envelope.target_status not in RUN_TERMINAL:
                return

        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_domain.state_machines.transitions import sync_task_from_run
        from app.joysafeter_domain.models.agent_run import AgentRun

        async with AsyncSessionLocal() as session:
            run = (await session.execute(select(AgentRun).where(AgentRun.id == envelope.run_id))).scalar_one_or_none()
            if not run:
                logger.warning(f"[TaskSync] Run {envelope.run_id} not found")
                return
            if not run.task_id:
                return
            await sync_task_from_run(run, session)
            await session.commit()
            logger.info(f"[TaskSync] Synced task {run.task_id} from run {envelope.run_id}")
