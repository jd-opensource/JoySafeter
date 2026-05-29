from __future__ import annotations

import logging

from app.core.events.envelope import ConductorEventEnvelope
from app.core.events.subscriber import SubscriberPhase
from app.core.session_broadcaster import SessionBroadcaster

logger = logging.getLogger(__name__)


class SessionBroadcastSubscriber:
    """Phase 2: broadcast session events to WebSocket subscribers via SessionBroadcaster."""

    name = "session_broadcast"
    phase = SubscriberPhase.BROADCAST

    def __init__(self, broadcaster: SessionBroadcaster) -> None:
        self._broadcaster = broadcaster

    async def handle(self, envelope: ConductorEventEnvelope) -> None:
        if envelope.session_id is None:
            return

        event_dict = {"type": envelope.event_type}

        if envelope.is_status_change:
            if envelope.stop_reason:
                event_dict["stop_reason"] = envelope.stop_reason
        else:
            if envelope.seq:
                event_dict["seq"] = envelope.seq
            if envelope.payload:
                event_dict.update(envelope.payload)

        await self._broadcaster.send(envelope.session_id, event_dict)
