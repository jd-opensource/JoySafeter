from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope
from app.joysafeter_orchestrator.events.subscriber import SubscriberPhase

logger = logging.getLogger(__name__)


class SessionStateSubscriber:
    """Phase 1: update session status and persist status-change events."""

    name = "session_state"
    phase = SubscriberPhase.PERSIST

    async def handle(self, envelope: JoySafeterEventEnvelope) -> None:
        if not envelope.is_status_change:
            return

        if envelope.session_id is None:
            return

        from app.joysafeter_orchestrator.services import SessionService
        from app.joysafeter_shared.database import AsyncSessionLocal

        status_str = self._event_type_to_status(envelope.event_type)
        if status_str is None:
            return

        async with AsyncSessionLocal() as db:
            svc = SessionService(db)
            try:
                task_id = envelope.task_id or self._payload_task_id(envelope.payload)
                if task_id and status_str in {"idle", "running"}:
                    updated = await svc.update_session_status_for_task_event(
                        envelope.session_id,
                        status_str,
                        task_id,
                        stop_reason=envelope.stop_reason,
                    )
                else:
                    updated = await svc.update_session_status(
                        envelope.session_id, status_str, stop_reason=envelope.stop_reason
                    )
            except Exception:
                logger.debug(
                    "Session %s status transition to '%s' rejected, skipping",
                    envelope.session_id,
                    status_str,
                )
                envelope.suppress_broadcast = True
                return
            if not updated:
                logger.debug(
                    "Session %s state event not applied, skipping state event persist",
                    envelope.session_id,
                )
                envelope.suppress_broadcast = True
                return
            payload = dict(envelope.payload or {})
            if task_id and "task_id" not in payload:
                payload["task_id"] = str(task_id)
            await svc.send_event(envelope.session_id, envelope.event_type, payload)

    @staticmethod
    def _event_type_to_status(event_type: str) -> Optional[str]:
        mapping = {
            "session.status_running": "running",
            "session.status_idle": "idle",
            "session.status_rescheduling": "rescheduling",
            "session.status_terminated": "terminated",
        }
        return mapping.get(event_type)

    @staticmethod
    def _payload_task_id(payload: dict | None) -> Optional[uuid.UUID]:
        if not isinstance(payload, dict):
            return None
        raw = payload.get("task_id")
        if not raw:
            return None
        try:
            return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
        except (TypeError, ValueError):
            return None
