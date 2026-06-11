"""
PersistenceSubscriber — Phase 1.

Writes ExecutionEvent rows to the database and fills envelope.seq.
Flushes but does NOT commit — the bus commits after all Phase 1 subscribers.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import InternalServiceError
from app.joysafeter_worker.events.envelope import ExecutionEventEnvelope
from app.joysafeter_worker.events.event_types import ExecutionEventType
from app.joysafeter_worker.events.subscriber import SubscriberPhase
from app.joysafeter_domain.models.execution import ExecutionEvent


class PersistenceSubscriber:
    name = "persistence"
    phase = SubscriberPhase.PERSIST

    def __init__(self) -> None:
        # single-process sequence cache:
        # This in-memory counter avoids a MAX() query on every event and is safe
        # only when one backend process owns event writes for an execution and
        # those writes are serialized/single-writer per execution. Multi-worker
        # or multi-instance deployments need distributed event sequencing before
        # this cache can be treated as globally safe.
        self._seq_cache: dict[str, int] = defaultdict(int)

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

        eid = str(envelope.execution_id)

        # Seed cache on first event for this execution
        if eid not in self._seq_cache:
            max_seq = (
                await db.execute(
                    select(func.coalesce(func.max(ExecutionEvent.sequence_no), 0)).where(
                        ExecutionEvent.execution_id == envelope.execution_id
                    )
                )
            ).scalar()
            self._seq_cache[eid] = max_seq or 0

        self._seq_cache[eid] += 1
        seq = self._seq_cache[eid]

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

        # Clean up cache on terminal events
        if envelope.event_type == ExecutionEventType.EXECUTION_COMPLETED:
            self._seq_cache.pop(eid, None)
