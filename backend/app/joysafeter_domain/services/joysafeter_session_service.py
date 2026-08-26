"""Session lifecycle, persistence, and realtime event services."""

from __future__ import annotations

# ruff: noqa: E402 — sections merged verbatim; imports intentionally follow their banners
# ============================================================================
# session_event_realtime.py
# ============================================================================
import json
import logging
import os
from typing import Any, TypedDict, cast

from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.config.service_role import current_role
from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_shared.ids import (
    AgentId,
    CredentialGroupId,
    EventId,
    ProjectId,
    SandboxId,
    SessionId,
    SessionResourceId,
    TaskId,
    as_uuid,
)
from app.joysafeter_shared.json_boundary import normalize_json_value

logger = logging.getLogger(__name__)


class SessionEventBatchItem(TypedDict):
    session_id: SessionId
    event_type: str
    payload: dict[str, Any]


def build_session_event_payload(
    *,
    event_id: EventId | None,
    event_type: str,
    seq: int | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    event: dict[str, Any] = {"type": event_type}
    if event_id:
        event["id"] = event_id
    if seq:
        event["seq"] = seq
    if isinstance(payload, dict):
        event.update(payload)
    return event


async def publish_session_event_realtime(
    *,
    session_id: SessionId,
    event_id: EventId | None,
    event_type: str,
    seq: int | None,
    payload: dict[str, Any] | None,
) -> None:
    redis = RedisClient.get_client()
    if redis is None:
        return

    event = build_session_event_payload(
        event_id=event_id,
        event_type=event_type,
        seq=seq,
        payload=payload,
    )
    wrapper = json.dumps(
        normalize_json_value(
            {
                "source_instance": f"{joysafeter_config.instance_id}:{current_role().value}:{os.getpid()}",
                "event": event,
            }
        ),
        ensure_ascii=False,
        allow_nan=False,
    )
    channel = f"joysafeter:session_events:{as_uuid(session_id)}"
    try:
        await redis.publish(channel, wrapper)
    except Exception as exc:
        logger.warning(
            "Failed to publish session event realtime",
            extra={
                "error": async_boundary_error_payload(
                    code="SESSION_REALTIME_REDIS_PUBLISH_FAILED",
                    message="Failed to publish session event realtime",
                    boundary="session_event_realtime",
                    operation="redis_publish",
                    data={
                        "session_id": str(session_id),
                        "event_id": str(event_id) if event_id else None,
                        "event_type": event_type,
                        "seq": seq,
                        "channel": channel,
                    },
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )


# ============================================================================
# joysafeter_session_lifecycle.py
# ============================================================================

import asyncio
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_credential import JoySafeterSessionCredentialGroup
from app.joysafeter_domain.models.joysafeter_session import (
    JoySafeterSession,
    JoySafeterSessionEvent,
    SessionStatus,
)
from app.joysafeter_shared.common.app_errors import ConflictError, NotFoundError, ResourceConflictError
from app.joysafeter_shared.utils.datetime import utc_now
from app.joysafeter_shared.utils.locks import session_advisory_lock_key

_VALID_TRANSITIONS: dict[str, set[str]] = {
    SessionStatus.RUNNING.value: {
        SessionStatus.IDLE.value,
        SessionStatus.RESCHEDULING.value,
        SessionStatus.RUNNING.value,
    },
    SessionStatus.IDLE.value: {
        SessionStatus.RUNNING.value,
        SessionStatus.RESCHEDULING.value,
    },
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
        session_id: SessionId,
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
        session_id: SessionId,
        status: str,
        event_type: str,
        payload: dict,
        stop_reason: Optional[dict] = None,
    ) -> bool:
        await self._lock_event_sequence(session_id)

        result = await self.db.execute(
            select(JoySafeterSession).where(JoySafeterSession.id == session_id).with_for_update()
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
            id=EventId.new(),
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            seq=(seq_result.scalar() or 0) + 1,
            processed_at=utc_now(),
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        pass  # publish_session_event_realtime defined in this module

        await publish_session_event_realtime(
            session_id=session_id,
            event_id=event.id,
            event_type=event.event_type,
            seq=event.seq,
            payload=event.payload,
        )
        return True

    async def _lock_event_sequence(self, session_id: SessionId) -> None:
        lock_key = session_advisory_lock_key(session_id)
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


# ============================================================================
# session_service.py
# ============================================================================

from collections import defaultdict

from sqlalchemy import and_, update

from app.joysafeter_domain.models.joysafeter_session import (
    SessionStatus,
)
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor

# State machine ``_VALID_TRANSITIONS`` and ``_RETRYABLE_DB_ERROR_MARKERS`` /
# ``_is_retryable_db_error`` were defined identically in an earlier merged
# section; the module-level definitions above are reused here verbatim.

_STATUS_EVENT_TYPES = {
    "session.status_idle",
    "session.status_rescheduling",
    "session.status_running",
    "session.status_terminated",
    "session.thread_status_idle",
    "session.thread_status_running",
    "session.thread_status_terminated",
}


def _normalized_stop_reason(stop_reason: Optional[dict]) -> dict:
    return stop_reason or {}


def _status_event_key(payload: dict) -> tuple[object, object]:
    return payload.get("task_id"), payload.get("stop_reason") or {}


class SessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_credential_group_ids(self, session_id: SessionId) -> list[CredentialGroupId]:
        result = await self.db.execute(
            select(JoySafeterSessionCredentialGroup.credential_group_id).where(
                JoySafeterSessionCredentialGroup.session_id == session_id
            )
        )
        return list(result.scalars().all())

    async def credential_group_ids_map(self, session_ids: list[SessionId]) -> dict[SessionId, list[CredentialGroupId]]:
        """Batch-load bound credential-group ids for a set of sessions (list view)."""
        if not session_ids:
            return {}
        result = await self.db.execute(
            select(
                JoySafeterSessionCredentialGroup.session_id,
                JoySafeterSessionCredentialGroup.credential_group_id,
            ).where(JoySafeterSessionCredentialGroup.session_id.in_(session_ids))
        )
        out: dict[SessionId, list[CredentialGroupId]] = {}
        for session_id, group_id in result.all():
            out.setdefault(session_id, []).append(group_id)
        return out

    async def get_session(
        self,
        session_id: SessionId,
        project_id: ProjectId | None = None,
    ) -> Optional[JoySafeterSession]:
        conditions = [JoySafeterSession.id == session_id]
        if project_id is not None:
            conditions.append(JoySafeterSession.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSession).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        limit: int = 20,
        after_id: Optional[SessionId] = None,
        project_id: ProjectId | None = None,
        include_archived: bool = False,
    ) -> tuple[list[JoySafeterSession], bool]:
        q = select(JoySafeterSession)
        if not include_archived:
            q = q.where(JoySafeterSession.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterSession.project_id == project_id)
        q = apply_created_at_desc_cursor(q, JoySafeterSession, after_id).limit(limit + 1)
        result = await self.db.execute(q)
        sessions = list(result.scalars().all())
        has_more = len(sessions) > limit
        return sessions[:limit], has_more

    async def list_sessions_by_agent(
        self,
        agent_id: AgentId,
        limit: int = 20,
        after_id: Optional[SessionId] = None,
        project_id: ProjectId | None = None,
        include_archived: bool = False,
    ) -> tuple[list[JoySafeterSession], bool]:
        q = select(JoySafeterSession).where(JoySafeterSession.agent_id == agent_id)
        if not include_archived:
            q = q.where(JoySafeterSession.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterSession.project_id == project_id)
        q = apply_created_at_desc_cursor(q, JoySafeterSession, after_id).limit(limit + 1)
        result = await self.db.execute(q)
        sessions = list(result.scalars().all())
        has_more = len(sessions) > limit
        return sessions[:limit], has_more

    async def delete_session(self, session_id: SessionId, project_id: ProjectId | None = None) -> bool:
        session = await self.get_session(session_id, project_id=project_id)
        if not session:
            return False
        from app.joysafeter_domain.models.joysafeter_memory import JoySafeterSessionMemoryStore
        from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask

        terminal_values = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]
        active_conditions = [
            JoySafeterTask.chat_session_id == session_id,
            JoySafeterTask.status.notin_(terminal_values),
        ]
        if project_id is not None:
            active_conditions.append(JoySafeterTask.project_id == project_id)
        active_result = await self.db.execute(
            select(func.count()).select_from(JoySafeterTask).where(and_(*active_conditions))
        )
        if (active_result.scalar() or 0) > 0:
            raise ConflictError(code="CONFLICT", message="Cannot delete session with active tasks")

        task_detach_conditions = [JoySafeterTask.chat_session_id == session_id]
        if project_id is not None:
            task_detach_conditions.append(JoySafeterTask.project_id == project_id)
        await self.db.execute(update(JoySafeterTask).where(and_(*task_detach_conditions)).values(chat_session_id=None))
        from sqlalchemy import delete as sa_delete

        await self.db.execute(
            sa_delete(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id == session_id)
        )
        await self.db.delete(session)
        await self.db.commit()
        return True

    async def archive_session(self, session_id: SessionId, project_id: ProjectId | None = None) -> bool:
        session = await self.get_session(session_id, project_id=project_id)
        if not session:
            return False
        if session.status == SessionStatus.RUNNING.value:
            raise ConflictError(code="CONFLICT", message="Cannot archive running session")
        from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask

        terminal_values = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]
        active_conditions = [
            JoySafeterTask.chat_session_id == session_id,
            JoySafeterTask.status.notin_(terminal_values),
        ]
        if project_id is not None:
            active_conditions.append(JoySafeterTask.project_id == project_id)
        active_result = await self.db.execute(
            select(func.count()).select_from(JoySafeterTask).where(and_(*active_conditions))
        )
        if (active_result.scalar() or 0) > 0:
            raise ConflictError(code="CONFLICT", message="Cannot archive session with active tasks")
        if session.archived_at:
            return True
        if session.status != SessionStatus.TERMINATED.value:
            terminated = await self.update_session_status(
                session_id,
                SessionStatus.TERMINATED.value,
                project_id=project_id,
                require_no_active_tasks=True,
            )
            if not terminated:
                raise ConflictError(code="CONFLICT", message="Cannot archive session with active tasks")
        session.archived_at = utc_now()
        await self.db.commit()
        return True

    async def update_session_status(
        self,
        session_id: SessionId,
        status: str,
        stop_reason: Optional[dict] = None,
        project_id: ProjectId | None = None,
        require_no_active_tasks: bool = False,
    ) -> bool:
        # CRITICAL FIX: Acquire advisory lock BEFORE row lock to prevent deadlocks.
        # The batch_writer acquires advisory lock then touches session rows via FK.
        # If we acquire row lock first then advisory lock, we get AB-BA deadlock.
        # Lock ordering must be: advisory lock → row lock (same as SessionLifecycleService).
        lock_key = session_advisory_lock_key(session_id)
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

        conditions = [JoySafeterSession.id == session_id]
        if project_id is not None:
            conditions.append(JoySafeterSession.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSession).where(and_(*conditions)).with_for_update())
        session = result.scalar_one_or_none()
        if not session:
            return False

        if session.status == status and _normalized_stop_reason(session.stop_reason) == _normalized_stop_reason(
            stop_reason
        ):
            return False

        if require_no_active_tasks:
            from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask

            terminal_values = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]
            active_conditions = [
                JoySafeterTask.chat_session_id == session_id,
                JoySafeterTask.status.notin_(terminal_values),
            ]
            if project_id is not None:
                active_conditions.append(JoySafeterTask.project_id == project_id)
            active_result = await self.db.execute(
                select(func.count()).select_from(JoySafeterTask).where(and_(*active_conditions))
            )
            if (active_result.scalar() or 0) > 0:
                return False

        # State machine guard
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
        await self.db.commit()
        return True

    async def update_session_status_for_task_event(
        self,
        session_id: SessionId,
        status: str,
        task_id: TaskId,
        stop_reason: Optional[dict] = None,
    ) -> bool:
        """Accept and apply a task-scoped session status transition.

        Runner/session status events can arrive late after failover, cancellation,
        or a fast follow-up task.  A stale task must not move the session back to
        running/idle after the current task ownership has changed.

        Returns True when the event belongs to the current task context and may
        be persisted/broadcast, even if the session row was already in that
        status. Returns False only when the event is stale or references the
        wrong task/session.
        """
        from app.joysafeter_domain.models.joysafeter_task import (
            JOYSAFETER_TERMINAL_STATUSES,
            JoySafeterTask,
        )

        lock_key = session_advisory_lock_key(session_id)
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

        result = await self.db.execute(
            select(JoySafeterSession).where(JoySafeterSession.id == session_id).with_for_update()
        )
        session = result.scalar_one_or_none()
        if not session:
            return False

        task_result = await self.db.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))
        task = task_result.scalar_one_or_none()
        if not task or task.chat_session_id != session_id:
            return False

        terminal_values = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]
        if status == SessionStatus.RUNNING.value and task.status in terminal_values:
            return False

        if status in (SessionStatus.IDLE.value, SessionStatus.RUNNING.value):
            active_other_result = await self.db.execute(
                select(func.count())
                .select_from(JoySafeterTask)
                .where(
                    and_(
                        JoySafeterTask.chat_session_id == session_id,
                        JoySafeterTask.id != task_id,
                        JoySafeterTask.status.notin_(terminal_values),
                    )
                )
            )
            if (active_other_result.scalar() or 0) > 0:
                return False

        if session.status == status and _normalized_stop_reason(session.stop_reason) == _normalized_stop_reason(
            stop_reason
        ):
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
        await self.db.commit()
        return True

    async def update_session_sandbox(
        self,
        session_id: SessionId,
        sandbox_id: SandboxId,
        harness_session_id: Optional[str] = None,
        work_dir: Optional[str] = None,
    ) -> bool:
        session = await self.get_session(session_id)
        if not session:
            return False
        session.last_sandbox_id = sandbox_id
        if harness_session_id:
            session.last_harness_session_id = harness_session_id
        if work_dir:
            session.last_work_dir = work_dir
        session.updated_at = utc_now()
        await self.db.commit()
        return True

    async def accumulate_usage(self, session_id: SessionId, task_usage: dict) -> bool:
        result = await self.db.execute(
            select(JoySafeterSession).where(JoySafeterSession.id == session_id).with_for_update()
        )
        session = result.scalar_one_or_none()
        if not session:
            return False
        current = dict(session.usage or {})
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            current[key] = current.get(key, 0) + (task_usage.get(key, 0) or 0)

        by_model = current.get("by_model", {})
        task_by_model = task_usage.get("by_model") or {}
        for model_name, model_data in task_by_model.items():
            if not isinstance(model_data, dict):
                continue
            existing = by_model.get(model_name, {})
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ):
                existing[key] = existing.get(key, 0) + (model_data.get(key, 0) or 0)
            by_model[model_name] = existing
        current["by_model"] = by_model

        session.usage = current
        session.updated_at = utc_now()
        await self.db.commit()
        return True

    async def send_event(
        self,
        session_id: SessionId,
        event_type: str,
        payload: dict,
    ) -> JoySafeterSessionEvent:
        for attempt in range(3):
            try:
                return await self._send_event_once(session_id, event_type, payload)
            except Exception as exc:
                if attempt >= 2 or not _is_retryable_db_error(exc):
                    raise
                await self.db.rollback()
                await asyncio.sleep(0.05 * (2**attempt))

        raise RuntimeError("unreachable")

    async def _send_event_once(
        self,
        session_id: SessionId,
        event_type: str,
        payload: dict,
    ) -> JoySafeterSessionEvent:
        await self._lock_event_sequence(session_id)

        if event_type in _STATUS_EVENT_TYPES:
            latest_result = await self.db.execute(
                select(JoySafeterSessionEvent)
                .where(JoySafeterSessionEvent.session_id == session_id)
                .order_by(JoySafeterSessionEvent.seq.desc(), JoySafeterSessionEvent.id.desc())
                .limit(1)
            )
            latest = latest_result.scalar_one_or_none()
            if (
                latest
                and latest.event_type == event_type
                and _status_event_key(latest.payload or {}) == _status_event_key(payload or {})
            ):
                return latest

        next_seq = await self._next_seq_locked(session_id)
        event = JoySafeterSessionEvent(
            id=EventId.new(),
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            seq=next_seq,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        pass  # publish_session_event_realtime defined in this module

        await publish_session_event_realtime(
            session_id=session_id,
            event_id=event.id,
            event_type=event.event_type,
            seq=event.seq,
            payload=event.payload,
        )
        return event

    async def list_events(
        self,
        session_id: SessionId,
        limit: int = 50,
        after_seq: Optional[int] = None,
        project_id: ProjectId | None = None,
        before_seq: Optional[int] = None,
        order: str = "asc",
    ) -> tuple[list[JoySafeterSessionEvent], bool]:
        q = select(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id == session_id)
        if project_id is not None:
            q = q.where(
                select(JoySafeterSession.id)
                .where(
                    JoySafeterSession.id == session_id,
                    JoySafeterSession.project_id == project_id,
                )
                .exists()
            )
        if after_seq is not None:
            q = q.where(JoySafeterSessionEvent.seq > after_seq)
        if before_seq is not None:
            q = q.where(JoySafeterSessionEvent.seq < before_seq)

        if order == "desc":
            q = q.order_by(JoySafeterSessionEvent.seq.desc(), JoySafeterSessionEvent.id.desc())
        else:
            q = q.order_by(JoySafeterSessionEvent.seq.asc(), JoySafeterSessionEvent.id.asc())
        q = q.limit(limit + 1)
        result = await self.db.execute(q)
        events = list(result.scalars().all())
        has_more = len(events) > limit
        return events[:limit], has_more

    async def find_user_message_event_by_idempotency_key(
        self,
        session_id: SessionId,
        idempotency_key: str,
        project_id: ProjectId | None = None,
    ) -> Optional[JoySafeterSessionEvent]:
        conditions: list[Any] = [
            JoySafeterSessionEvent.session_id == session_id,
            JoySafeterSessionEvent.event_type == "user.message",
            text("payload->>'_idempotency_key' = :idempotency_key"),
        ]
        if project_id is not None:
            conditions.append(
                select(JoySafeterSession.id)
                .where(
                    JoySafeterSession.id == session_id,
                    JoySafeterSession.project_id == project_id,
                )
                .exists()
            )
        result = await self.db.execute(
            select(JoySafeterSessionEvent)
            .where(and_(*conditions))
            .params(idempotency_key=idempotency_key)
            .order_by(JoySafeterSessionEvent.seq.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_status_running_event_for_task(
        self,
        session_id: SessionId,
        task_id: TaskId,
        project_id: ProjectId | None = None,
    ) -> Optional[JoySafeterSessionEvent]:
        conditions: list[Any] = [
            JoySafeterSessionEvent.session_id == session_id,
            JoySafeterSessionEvent.event_type == "session.status_running",
            text("payload->>'task_id' = :task_id"),
        ]
        if project_id is not None:
            conditions.append(
                select(JoySafeterSession.id)
                .where(
                    JoySafeterSession.id == session_id,
                    JoySafeterSession.project_id == project_id,
                )
                .exists()
            )
        result = await self.db.execute(
            select(JoySafeterSessionEvent)
            .where(and_(*conditions))
            .params(task_id=str(task_id))
            .order_by(JoySafeterSessionEvent.seq.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def resolve_control_tool_use_call_id(self, session_id: SessionId, raw_tool_use_id: str) -> str:
        raw_tool_use_id = str(raw_tool_use_id or "").strip()
        if not raw_tool_use_id:
            return raw_tool_use_id

        try:
            event_id = EventId.from_public(raw_tool_use_id)
        except (TypeError, ValueError):
            return raw_tool_use_id

        result = await self.db.execute(
            select(JoySafeterSessionEvent)
            .where(
                and_(
                    JoySafeterSessionEvent.id == event_id,
                    JoySafeterSessionEvent.session_id == session_id,
                    JoySafeterSessionEvent.event_type.in_(["agent.tool_use", "agent.custom_tool_use"]),
                )
            )
            .limit(1)
        )
        event = result.scalar_one_or_none()
        if event is None or not isinstance(event.payload, dict):
            return raw_tool_use_id

        for key in ("_call_id", "call_id", "tool_use_call_id", "tool_use_id"):
            value = event.payload.get(key)
            if isinstance(value, str) and value:
                return value
        return raw_tool_use_id

    async def task_has_agent_output(self, task_id: TaskId, session_id: SessionId) -> bool:
        """Check if a task has emitted agent.message events (produced output)."""
        from sqlalchemy import text as sa_text

        result = await self.db.execute(
            sa_text(
                "SELECT EXISTS("
                "  SELECT 1 FROM joysafeter_session_events"
                "  WHERE session_id = :sid"
                "  AND event_type = 'agent.message'"
                "  AND seq > ("
                "    SELECT COALESCE(MAX(seq), 0) FROM joysafeter_session_events"
                "    WHERE session_id = :sid"
                "    AND event_type = 'session.status_running'"
                "    AND payload->>'task_id' = :tid"
                "  )"
                ")"
            ),
            {"sid": as_uuid(session_id), "tid": str(task_id)},
        )
        return result.scalar() or False

    async def repair_missing_agent_message(
        self,
        session_id: SessionId,
        task_id: TaskId,
        output: Optional[str],
    ) -> bool:
        """Emit a synthetic agent.message from a task's final output iff none exists.

        A runner can crash after persisting task.output but before streaming the
        agent.message chat event. Both the result handler and the failover path
        need to backfill that message; centralizing the check-and-emit here keeps
        the two paths from drifting and makes the emit idempotent w.r.t. an
        agent.message already present for the task (a task legitimately produces
        many, so we only backfill when there are none). Returns True if emitted.
        """
        text_output = (output or "").strip()
        if not text_output:
            return False
        if await self.task_has_agent_output(task_id, session_id):
            return False
        await self.send_event(session_id, "agent.message", {"content": [{"type": "text", "text": output}]})
        return True

    async def _lock_event_sequence(self, session_id: SessionId) -> None:
        # Keep seq allocation serialized with the worker batch writer, which
        # uses the same per-session transaction advisory lock.  Mixing row locks
        # and advisory locks for the same event stream can deadlock under
        # concurrent status/event writes.
        lock_key = session_advisory_lock_key(session_id)
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    async def _next_seq_locked(self, session_id: SessionId) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.max(JoySafeterSessionEvent.seq), 0)).where(
                JoySafeterSessionEvent.session_id == session_id
            )
        )
        return cast(int, result.scalar()) + 1

    async def attach_memory_stores(
        self,
        session_id: SessionId,
        resources: list[dict],
        project_id: ProjectId | None = None,
    ) -> list:
        from app.joysafeter_domain.models.joysafeter_memory import JoySafeterMemoryStore, JoySafeterSessionMemoryStore

        session = await self.get_session(session_id, project_id=project_id)
        if session is None:
            raise NotFoundError(
                code="SESSION_NOT_FOUND",
                message="Session not found",
                data={"session_id": str(session_id)},
                user_action="refresh",
            )
        if session.archived_at:
            raise ResourceConflictError(
                code="SESSION_ARCHIVED",
                message="Session is archived",
                data={"session_id": str(session_id)},
                user_action="refresh",
            )
        if session.status == "terminated":
            raise ResourceConflictError(
                code="SESSION_TERMINATED",
                message="Session is terminated",
                data={"session_id": str(session_id), "session_status": session.status},
                user_action="refresh",
            )
        if session.status == "rescheduling":
            raise ResourceConflictError(
                code="SESSION_RESCHEDULING",
                message="Session is rescheduling, try again later",
                data={"session_id": str(session_id), "session_status": session.status},
                retryable=True,
                user_action="retry",
            )
        if session.status != "idle":
            raise ResourceConflictError(
                code="SESSION_ALREADY_RUNNING",
                message="Session resources can only be changed while the session is idle",
                data={"session_id": str(session_id), "session_status": session.status},
                retryable=True,
                user_action="retry",
            )

        validated_resources = []
        seen_store_ids = set()
        for res in resources:
            store_id = res["memory_store_id"]
            if store_id in seen_store_ids:
                raise ResourceConflictError(
                    code="SESSION_MEMORY_STORE_ALREADY_ATTACHED",
                    message=f"Memory store is already attached to session: {store_id}",
                    data={"session_id": str(session_id), "memory_store_id": str(store_id)},
                    user_action="fix_input",
                )
            seen_store_ids.add(store_id)
            store_conditions = [
                JoySafeterMemoryStore.id == store_id,
            ]
            if project_id is not None:
                store_conditions.append(JoySafeterMemoryStore.project_id == project_id)
            store_result = await self.db.execute(select(JoySafeterMemoryStore).where(*store_conditions))
            store = store_result.scalar_one_or_none()
            if store is None:
                raise NotFoundError(
                    code="SESSION_MEMORY_STORE_NOT_FOUND",
                    message=f"Memory store not found: {store_id}",
                    data={"memory_store_id": str(store_id)},
                    user_action="refresh",
                )
            if store.archived_at is not None:
                raise ResourceConflictError(
                    code="SESSION_MEMORY_STORE_ARCHIVED",
                    message=f"Memory store is archived: {store_id}",
                    data={"memory_store_id": str(store_id)},
                    user_action="refresh",
                )
            existing_result = await self.db.execute(
                select(JoySafeterSessionMemoryStore).where(
                    JoySafeterSessionMemoryStore.session_id == session_id,
                    JoySafeterSessionMemoryStore.store_id == store_id,
                )
            )
            if existing_result.scalar_one_or_none() is not None:
                raise ResourceConflictError(
                    code="SESSION_MEMORY_STORE_ALREADY_ATTACHED",
                    message=f"Memory store is already attached to session: {store_id}",
                    data={"session_id": str(session_id), "memory_store_id": str(store_id)},
                    user_action="fix_input",
                )
            validated_resources.append(res)

        created = []
        for res in validated_resources:
            row = JoySafeterSessionMemoryStore(
                id=SessionResourceId.new(),
                session_id=session_id,
                store_id=res["memory_store_id"],
                access=res.get("access", "read_write"),
                instructions=res.get("instructions"),
                mount_name=res.get("mount_name") or str(res["memory_store_id"]),
            )
            self.db.add(row)
            created.append(row)
        if created:
            await self.db.commit()
            for row in created:
                await self.db.refresh(row)
        return created

    async def list_session_memory_stores(self, session_id: SessionId) -> list:
        from app.joysafeter_domain.models.joysafeter_memory import JoySafeterSessionMemoryStore

        result = await self.db.execute(
            select(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id == session_id)
        )
        return list(result.scalars().all())

    async def mark_event_processed(self, event_id: EventId) -> None:
        await self.db.execute(
            update(JoySafeterSessionEvent)
            .where(JoySafeterSessionEvent.id == event_id)
            .values(processed_at=func.coalesce(JoySafeterSessionEvent.processed_at, func.now()))
        )
        await self.db.commit()

    async def list_unprocessed_events(
        self, session_id: SessionId, event_types: list[str], limit: int = 100
    ) -> list[JoySafeterSessionEvent]:
        q = (
            select(JoySafeterSessionEvent)
            .where(
                and_(
                    JoySafeterSessionEvent.session_id == session_id,
                    JoySafeterSessionEvent.processed_at.is_(None),
                    JoySafeterSessionEvent.event_type.in_(event_types),
                )
            )
            .order_by(JoySafeterSessionEvent.id.asc())
            .limit(limit)
        )
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def batch_insert_session_events(self, events: list[SessionEventBatchItem]) -> list:
        if not events:
            return []

        # Group events by session_id
        groups: dict[SessionId, list[SessionEventBatchItem]] = defaultdict(list)
        for ev in events:
            session_id = ev["session_id"]
            if type(session_id) is not SessionId:
                raise TypeError("session_id must be a SessionId")
            groups[session_id].append(ev)

        created = []
        for session_id in sorted(groups.keys()):
            group = groups[session_id]
            await self._lock_event_sequence(session_id)
            max_seq = await self._max_seq_locked(session_id)

            # Assign sequential seq numbers and bulk insert
            for i, ev in enumerate(group, start=1):
                event = JoySafeterSessionEvent(
                    id=EventId.new(),
                    session_id=session_id,
                    event_type=ev["event_type"],
                    payload=ev["payload"],
                    seq=max_seq + i,
                )
                self.db.add(event)
                created.append(event)

        await self.db.commit()
        for event in created:
            await self.db.refresh(event)
        pass  # publish_session_event_realtime defined in this module

        for event in created:
            await publish_session_event_realtime(
                session_id=event.session_id,
                event_id=event.id,
                event_type=event.event_type,
                seq=event.seq,
                payload=event.payload,
            )
        return created

    async def _max_seq_locked(self, session_id: SessionId) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.max(JoySafeterSessionEvent.seq), 0)).where(
                JoySafeterSessionEvent.session_id == session_id
            )
        )
        return result.scalar() or 0

    async def list_session_events_filtered(
        self,
        session_id: SessionId,
        after_seq: Optional[int],
        limit: int,
        event_types: list[str],
    ) -> list[JoySafeterSessionEvent]:
        q = select(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id == session_id)
        if after_seq is not None:
            q = q.where(JoySafeterSessionEvent.seq > after_seq)
        if event_types:
            q = q.where(JoySafeterSessionEvent.event_type.in_(event_types))
        q = q.order_by(JoySafeterSessionEvent.id.asc()).limit(limit)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def list_all_memories_for_session(self, session_id: SessionId) -> list[dict]:
        from app.joysafeter_domain.models.joysafeter_memory import (
            JoySafeterMemory,
            JoySafeterSessionMemoryStore,
        )

        # Get all mounted stores for this session
        result = await self.db.execute(
            select(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id == session_id)
        )
        mounts = list(result.scalars().all())

        output = []
        for mount in mounts:
            # Load all memories for this store
            mem_result = await self.db.execute(
                select(JoySafeterMemory).where(JoySafeterMemory.store_id == mount.store_id)
            )
            memories = list(mem_result.scalars().all())
            output.append(
                {
                    "store_id": mount.store_id,
                    "mount_name": mount.mount_name,
                    "access": mount.access,
                    "memories": [{"path": m.path, "content": m.content} for m in memories],
                }
            )
        return output
