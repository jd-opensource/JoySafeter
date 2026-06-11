"""
PersistenceSubscriber — Phase 1.

Writes ExecutionEvent rows to the database and fills envelope.seq.
Flushes but does NOT commit — the bus commits after all Phase 1 subscribers.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import InternalServiceError
from app.joysafeter_worker.events.envelope import ExecutionEventEnvelope
from app.joysafeter_worker.events.subscriber import SubscriberPhase
from app.joysafeter_domain.models.execution import ExecutionEvent


class PersistenceSubscriber:
    name = "persistence"
    phase = SubscriberPhase.PERSIST

    async def handle(
        self,
        envelope: ExecutionEventEnvelope,
        db: Optional[AsyncSession] = None,
    ) -> None:
        if db is None:
            raise InternalServiceError(
                "Persistence subscriber requires a database session",
                code="EVENT_SUBSCRIBER_DB_SESSION_MISSING",
                data={"subscriber": self.name},
            )

        await self._lock_event_sequence(db, envelope.execution_id)
        seq = await self._next_seq_locked(db, envelope.execution_id)

        event = ExecutionEvent(
            execution_id=envelope.execution_id,
            sequence_no=seq,
            event_type=envelope.event_type,
            payload=envelope.payload,
        )
        db.add(event)
        await db.flush()

        # Fill seq so Phase 2 subscribers can use it.
        # Safe: Phase 2 runs only after Phase 1 completes and bus commits.
        envelope.seq = seq

    @staticmethod
    async def _lock_event_sequence(db: AsyncSession, execution_id) -> None:
        lock_key = int.from_bytes(execution_id.bytes[8:], "big", signed=True)
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    @staticmethod
    async def _next_seq_locked(db: AsyncSession, execution_id) -> int:
        max_seq = (
            await db.execute(
                select(func.coalesce(func.max(ExecutionEvent.sequence_no), 0)).where(
                    ExecutionEvent.execution_id == execution_id
                )
            )
        ).scalar()
        return (max_seq or 0) + 1
