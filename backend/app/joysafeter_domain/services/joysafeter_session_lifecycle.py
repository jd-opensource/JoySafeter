import uuid
from typing import Optional

from sqlalchemy import func, select
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
        return True
