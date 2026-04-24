"""
StateTransitionSubscriber — Phase 1.

Handles execution_completed events: transitions Execution and AgentRun
state machines. Flushes but does NOT commit.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.envelope import ExecutionEventEnvelope
from app.core.events.subscriber import SubscriberPhase
from app.core.state_machines.engine import InvalidTransition
from app.core.state_machines.transitions import transition_execution, transition_run
from app.models.agent_run import AgentRun
from app.models.execution import Execution


class StateTransitionSubscriber:
    name = "state_transition"
    phase = SubscriberPhase.PERSIST

    async def handle(
        self,
        envelope: ExecutionEventEnvelope,
        db: Optional[AsyncSession] = None,
    ) -> None:
        if envelope.event_type != "execution_completed":
            return

        if db is None:
            raise RuntimeError("StateTransitionSubscriber requires a db session")
        if not envelope.terminal_status:
            raise RuntimeError("execution_completed envelope missing terminal_status")

        execution = (await db.execute(
            select(Execution).where(Execution.id == envelope.execution_id)
        )).scalar_one()
        try:
            await transition_execution(execution, envelope.terminal_status, db)
        except InvalidTransition:
            logger.warning(
                f"[StateTransition] Skipping execution {execution.id}: already {execution.status}"
            )

        run = (await db.execute(
            select(AgentRun).where(AgentRun.id == envelope.run_id)
        )).scalar_one()
        try:
            await transition_run(run, envelope.terminal_status, db, envelope.result_summary)
        except InvalidTransition:
            logger.warning(
                f"[StateTransition] Skipping run {run.id}: already {run.status}"
            )

        await db.flush()
