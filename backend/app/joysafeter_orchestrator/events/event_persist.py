from __future__ import annotations

import logging

from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope
from app.joysafeter_orchestrator.events.subscriber import SubscriberPhase
from app.joysafeter_worker.events.batch_writer import BufferedEvent, EventBatchSender

logger = logging.getLogger(__name__)


class EventPersistSubscriber:
    """Phase 1: persist session events via EventBatchSender."""

    name = "event_persist"
    phase = SubscriberPhase.PERSIST

    def __init__(self, event_buffer: EventBatchSender) -> None:
        self._event_buffer = event_buffer

    async def handle(self, envelope: JoySafeterEventEnvelope) -> None:
        if envelope.is_status_change and not envelope.event_id:
            return

        if envelope.session_id is None:
            return

        buffered = BufferedEvent(
            session_id=envelope.session_id,
            event_type=envelope.event_type,
            payload=envelope.payload,
            seq=envelope.seq,
            id=envelope.event_id,
        )
        await self._event_buffer.send(buffered)

        if envelope.flush_immediately:
            await self._event_buffer.flush()
