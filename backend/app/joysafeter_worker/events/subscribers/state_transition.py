"""
StateTransitionSubscriber — Phase 1.

Handles execution and run state transitions driven by events:
- execution_status_change → non-terminal transitions (dispatched, running, approval_wait)
- execution_completed → terminal transitions (succeeded, failed, cancelled) for both Execution and Run
- run_status_change → direct Run transitions (e.g. running, cancelled, reaper-failed)

Flushes but does NOT commit — the bus commits once after all Phase 1 subscribers.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import InternalServiceError
from app.joysafeter_worker.events.envelope import ExecutionEventEnvelope
from app.joysafeter_worker.events.event_types import ExecutionEventType
from app.joysafeter_worker.events.subscriber import SubscriberPhase
from app.joysafeter_domain.state_machines.definitions import EXECUTION_TERMINAL
from app.joysafeter_domain.state_machines.engine import InvalidTransition
from app.joysafeter_domain.state_machines.transitions import transition_execution, transition_run
from app.joysafeter_domain.models.agent_run import AgentRun
from app.joysafeter_domain.models.execution import Execution

_HANDLED = {
    ExecutionEventType.EXECUTION_STATUS_CHANGE,
    ExecutionEventType.EXECUTION_COMPLETED,
    ExecutionEventType.RUN_STATUS_CHANGE,
}


class StateTransitionSubscriber:
    name = "state_transition"
    phase = SubscriberPhase.PERSIST

    async def handle(
        self,
        envelope: ExecutionEventEnvelope,
        db: Optional[AsyncSession] = None,
    ) -> None:
        if envelope.event_type not in _HANDLED:
            return

        if db is None:
            raise InternalServiceError(
                "State transition subscriber requires a database session",
                code="EVENT_SUBSCRIBER_DB_SESSION_MISSING",
                data={"subscriber": self.name},
            )

        if envelope.event_type == ExecutionEventType.EXECUTION_STATUS_CHANGE:
            await self._handle_status_change(envelope, db)
        elif envelope.event_type == ExecutionEventType.EXECUTION_COMPLETED:
            await self._handle_completed(envelope, db)
        elif envelope.event_type == ExecutionEventType.RUN_STATUS_CHANGE:
            await self._handle_run_status_change(envelope, db)

    async def _handle_status_change(self, envelope: ExecutionEventEnvelope, db: AsyncSession) -> None:
        if not envelope.target_status:
            raise InternalServiceError(
                "Execution status change event is missing target status",
                code="EVENT_TARGET_STATUS_MISSING",
                data={"event_type": str(envelope.event_type), "execution_id": str(envelope.execution_id)},
            )

        if envelope.target_status in EXECUTION_TERMINAL:
            raise InternalServiceError(
                "Terminal execution status must use execution completed events",
                code="EVENT_TERMINAL_STATUS_INVALID",
                data={
                    "event_type": str(envelope.event_type),
                    "execution_id": str(envelope.execution_id),
                    "target_status": envelope.target_status,
                },
            )

        execution = (await db.execute(select(Execution).where(Execution.id == envelope.execution_id))).scalar_one()

        try:
            await transition_execution(execution, envelope.target_status, db)
        except InvalidTransition:
            logger.warning(f"[StateTransition] Skipping execution {execution.id}: already {execution.status}")
            return

        self._apply_metadata(execution, envelope)
        await db.flush()

    async def _handle_completed(self, envelope: ExecutionEventEnvelope, db: AsyncSession) -> None:
        if not envelope.terminal_status:
            raise InternalServiceError(
                "Execution completed event is missing terminal status",
                code="EVENT_TERMINAL_STATUS_MISSING",
                data={"event_type": str(envelope.event_type), "execution_id": str(envelope.execution_id)},
            )

        execution = (await db.execute(select(Execution).where(Execution.id == envelope.execution_id))).scalar_one()
        try:
            await transition_execution(execution, envelope.terminal_status, db)
        except InvalidTransition:
            logger.warning(f"[StateTransition] Skipping execution {execution.id}: already {execution.status}")
            return

        self._apply_metadata(execution, envelope)

        run = (await db.execute(select(AgentRun).where(AgentRun.id == envelope.run_id))).scalar_one()
        try:
            await transition_run(run, envelope.terminal_status, db, envelope.result_summary)
        except InvalidTransition:
            logger.warning(f"[StateTransition] Skipping run {run.id}: already {run.status}")

        await db.flush()

    async def _handle_run_status_change(self, envelope: ExecutionEventEnvelope, db: AsyncSession) -> None:
        if not envelope.target_status:
            raise InternalServiceError(
                "Run status change event is missing target status",
                code="EVENT_TARGET_STATUS_MISSING",
                data={"event_type": str(envelope.event_type), "run_id": str(envelope.run_id)},
            )

        run = (await db.execute(select(AgentRun).where(AgentRun.id == envelope.run_id))).scalar_one()

        try:
            await transition_run(run, envelope.target_status, db, envelope.result_summary)
        except InvalidTransition:
            logger.warning(f"[StateTransition] Skipping run {run.id}: already {run.status}")

    @staticmethod
    def _apply_metadata(execution: Execution, envelope: ExecutionEventEnvelope) -> None:
        """Write optional metadata fields from the envelope onto the execution row."""
        if envelope.error is not None:
            execution.error = envelope.error
        if envelope.container_id is not None:
            execution.runtime_session_ref = envelope.container_id
        if envelope.metrics is not None:
            execution.metrics = envelope.metrics
