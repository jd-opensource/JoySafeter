import asyncio
import uuid
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import ConflictError
from app.joysafeter_domain.models.session import (
    JoySafeterSession,
    JoySafeterSessionEvent,
    SessionStatus,
)
from app.joysafeter_shared.utils.datetime import utc_now


_VALID_TRANSITIONS: dict[str, set[str]] = {
    SessionStatus.RUNNING.value: {
        SessionStatus.IDLE.value,
        SessionStatus.RESCHEDULING.value,
        SessionStatus.RUNNING.value,
    },
    SessionStatus.IDLE.value: {SessionStatus.RUNNING.value},
    SessionStatus.TERMINATED.value: {
        SessionStatus.IDLE.value,
        SessionStatus.RUNNING.value,
        SessionStatus.RESCHEDULING.value,
    },
    SessionStatus.RESCHEDULING.value: {
        SessionStatus.RUNNING.value,
        SessionStatus.IDLE.value,
    },
}


class JoySafeterSessionLifecycleService:
    """Centralized session status transitions with event persistence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def transition_and_emit(
        self,
        session_id: uuid.UUID,
        status: str,
        event_type: str,
        payload: dict,
        stop_reason: Optional[dict] = None,
    ) -> bool:
        for attempt in range(3):
            try:
                return await self._transition_and_emit_once(
                    session_id,
                    status,
                    event_type,
                    payload,
                    stop_reason=stop_reason,
                )
            except Exception as exc:
                if attempt >= 2 or not _is_retryable_db_error(exc):
                    raise
                await self.db.rollback()
                await asyncio.sleep(0.05 * (2**attempt))

        raise RuntimeError("unreachable")

    async def _transition_and_emit_once(
        self,
        session_id: uuid.UUID,
        status: str,
        event_type: str,
        payload: dict,
        stop_reason: Optional[dict] = None,
    ) -> bool:
        await self._lock_event_sequence(session_id)

        result = await self.db.execute(
            select(JoySafeterSession)
            .where(JoySafeterSession.id == session_id)
            .with_for_update()
        )
        session = result.scalar_one_or_none()
        if not session:
            return False

        if session.status == status and status == SessionStatus.IDLE.value:
            if stop_reason is not None:
                session.stop_reason = stop_reason
                session.updated_at = utc_now()
                await self.db.commit()
            return True

        allowed_from = _VALID_TRANSITIONS.get(status)
        if allowed_from is not None and session.status not in allowed_from:
            raise ConflictError(
                code="CONFLICT",
                message=f"Cannot transition from '{session.status}' to '{status}'",
            )

        session.status = status
        if stop_reason is not None or status in (
            SessionStatus.IDLE.value,
            SessionStatus.TERMINATED.value,
        ):
            session.stop_reason = stop_reason
        session.updated_at = utc_now()

        seq_result = await self.db.execute(
            select(func.coalesce(func.max(JoySafeterSessionEvent.seq), 0)).where(
                JoySafeterSessionEvent.session_id == session_id
            )
        )
        event = JoySafeterSessionEvent(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            seq=(seq_result.scalar() or 0) + 1,
            processed_at=utc_now(),
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        from app.joysafeter_domain.services.session_event_realtime import publish_session_event_realtime

        await publish_session_event_realtime(
            session_id=session_id,
            event_id=event.id,
            event_type=event.event_type,
            seq=event.seq,
            payload=event.payload,
        )
        return True

    async def _lock_event_sequence(self, session_id: uuid.UUID) -> None:
        lock_key = int.from_bytes(session_id.bytes[8:], "big", signed=True)
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


_RETRYABLE_DB_ERROR_MARKERS = (
    "DeadlockDetectedError",
    "deadlock detected",
    "SerializationError",
    "could not serialize access",
)


def _is_retryable_db_error(exc: Exception) -> bool:
    message = str(exc)
    return any(marker in message for marker in _RETRYABLE_DB_ERROR_MARKERS)
