from __future__ import annotations

import logging
from typing import Optional

from app.conductor.events.envelope import ConductorEventEnvelope
from app.conductor.events.subscriber import SubscriberPhase

logger = logging.getLogger(__name__)


class SessionStateSubscriber:
    """Phase 1: update session status and persist status-change events."""

    name = "session_state"
    phase = SubscriberPhase.PERSIST

    async def handle(self, envelope: ConductorEventEnvelope) -> None:
        if not envelope.is_status_change:
            return

        if envelope.session_id is None:
            return

        from app.core.database import AsyncSessionLocal
        from app.conductor.services.session_service import SessionService
        from app.conductor.models.session import SessionStatus

        status_str = self._event_type_to_status(envelope.event_type)
        if status_str is None:
            return

        async with AsyncSessionLocal() as db:
            svc = SessionService(db)
            try:
                updated = await svc.update_session_status(
                    envelope.session_id, status_str, stop_reason=envelope.stop_reason
                )
            except Exception:
                logger.debug(
                    "Session %s status transition to '%s' rejected, skipping",
                    envelope.session_id,
                    status_str,
                )
                return
            if not updated:
                logger.debug(
                    "Session %s not found, skipping state event persist",
                    envelope.session_id,
                )
                return
            await svc.send_event(
                envelope.session_id, envelope.event_type, envelope.payload
            )

    @staticmethod
    def _event_type_to_status(event_type: str) -> Optional[str]:
        mapping = {
            "session.status_running": "running",
            "session.status_idle": "idle",
            "session.status_rescheduling": "rescheduling",
            "session.status_terminated": "terminated",
        }
        return mapping.get(event_type)
