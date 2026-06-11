import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import ConflictError
from app.joysafeter_domain.models.session import (
    JoySafeterSession,
    JoySafeterSessionEvent,
    SessionStatus,
)
from app.joysafeter_shared.utils.datetime import utc_now

# State machine: maps target status -> set of allowed source statuses
_VALID_TRANSITIONS: dict[str, set[str]] = {
    SessionStatus.RUNNING.value: {SessionStatus.IDLE.value, SessionStatus.RESCHEDULING.value, SessionStatus.RUNNING.value},
    SessionStatus.IDLE.value: {SessionStatus.RUNNING.value},
    SessionStatus.TERMINATED.value: {
        SessionStatus.IDLE.value,
        SessionStatus.RUNNING.value,
        SessionStatus.RESCHEDULING.value,
    },
    SessionStatus.RESCHEDULING.value: {SessionStatus.RUNNING.value, SessionStatus.IDLE.value},
}

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

    async def create_session(
        self,
        agent_id: uuid.UUID,
        title: Optional[str] = None,
        metadata: Optional[dict] = None,
        vault_ids: Optional[list[str]] = None,
        environment_ref: Optional[str] = None,
        agent_version: Optional[int] = None,
        agent_snapshot: Optional[dict] = None,
        project_id: Optional[str] = None,
    ) -> JoySafeterSession:
        kwargs = dict(
            agent_id=agent_id,
            title=title,
            status=SessionStatus.IDLE.value,
            metadata_=metadata or {},
            vault_ids=vault_ids or [],
            environment_ref=environment_ref,
            agent_version=agent_version,
            agent_snapshot=agent_snapshot,
        )
        if project_id is not None:
            kwargs["project_id"] = project_id
        session = JoySafeterSession(**kwargs)
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_session(self, session_id: uuid.UUID) -> Optional[JoySafeterSession]:
        result = await self.db.execute(
            select(JoySafeterSession).where(JoySafeterSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> tuple[list[JoySafeterSession], bool]:
        q = select(JoySafeterSession)
        if not include_archived:
            q = q.where(JoySafeterSession.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterSession.project_id == project_id)
        if after_id:
            cursor_created_at = select(JoySafeterSession.created_at).where(
                JoySafeterSession.id == after_id
            ).scalar_subquery()
            q = q.where(JoySafeterSession.created_at < cursor_created_at)
        q = q.order_by(JoySafeterSession.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        sessions = list(result.scalars().all())
        has_more = len(sessions) > limit
        return sessions[:limit], has_more

    async def list_sessions_by_agent(
        self,
        agent_id: uuid.UUID,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> tuple[list[JoySafeterSession], bool]:
        q = select(JoySafeterSession).where(JoySafeterSession.agent_id == agent_id)
        if not include_archived:
            q = q.where(JoySafeterSession.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterSession.project_id == project_id)
        if after_id:
            cursor_created_at = select(JoySafeterSession.created_at).where(
                JoySafeterSession.id == after_id
            ).scalar_subquery()
            q = q.where(JoySafeterSession.created_at < cursor_created_at)
        q = q.order_by(JoySafeterSession.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        sessions = list(result.scalars().all())
        has_more = len(sessions) > limit
        return sessions[:limit], has_more

    async def delete_session(self, session_id: uuid.UUID) -> bool:
        session = await self.get_session(session_id)
        if not session:
            return False
        from app.joysafeter_domain.models.task import JoySafeterTask
        from app.joysafeter_domain.models.joysafeter_memory import JoySafeterSessionMemoryStore
        await self.db.execute(
            update(JoySafeterTask)
            .where(JoySafeterTask.chat_session_id == session_id)
            .values(chat_session_id=None)
        )
        from sqlalchemy import delete as sa_delete
        await self.db.execute(
            sa_delete(JoySafeterSessionMemoryStore)
            .where(JoySafeterSessionMemoryStore.session_id == session_id)
        )
        await self.db.delete(session)
        await self.db.commit()
        return True

    async def archive_session(self, session_id: uuid.UUID) -> bool:
        session = await self.get_session(session_id)
        if not session:
            return False
        if session.status == SessionStatus.RUNNING.value:
            raise ConflictError(code="CONFLICT", message="Cannot archive running session")
        if session.archived_at:
            return True
        if session.status != SessionStatus.TERMINATED.value:
            await self.update_session_status(session_id, SessionStatus.TERMINATED.value)
        session.archived_at = utc_now()
        await self.db.commit()
        return True

    async def update_session_status(
        self,
        session_id: uuid.UUID,
        status: str,
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

        if (
            session.status == status
            and _normalized_stop_reason(session.stop_reason) == _normalized_stop_reason(stop_reason)
        ):
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

    async def update_session_sandbox(
        self,
        session_id: uuid.UUID,
        sandbox_id: uuid.UUID,
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

    async def accumulate_usage(
        self, session_id: uuid.UUID, task_usage: dict
    ) -> bool:
        result = await self.db.execute(
            select(JoySafeterSession)
            .where(JoySafeterSession.id == session_id)
            .with_for_update()
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
        session_id: uuid.UUID,
        event_type: str,
        payload: dict,
    ) -> JoySafeterSessionEvent:
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

        next_seq = await self._next_seq(session_id)
        event = JoySafeterSessionEvent(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            seq=next_seq,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def list_events(
        self,
        session_id: uuid.UUID,
        limit: int = 50,
        after_seq: Optional[int] = None,
    ) -> tuple[list[JoySafeterSessionEvent], bool]:
        q = select(JoySafeterSessionEvent).where(
            JoySafeterSessionEvent.session_id == session_id
        )
        if after_seq is not None:
            q = q.where(JoySafeterSessionEvent.seq > after_seq)
        q = q.order_by(JoySafeterSessionEvent.seq.asc(), JoySafeterSessionEvent.id.asc()).limit(limit + 1)
        result = await self.db.execute(q)
        events = list(result.scalars().all())
        has_more = len(events) > limit
        return events[:limit], has_more

    async def task_has_agent_output(
        self, task_id: uuid.UUID, session_id: uuid.UUID
    ) -> bool:
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
            {"sid": session_id, "tid": str(task_id)},
        )
        return result.scalar() or False

    async def _next_seq(self, session_id: uuid.UUID) -> int:
        await self.db.execute(
            select(JoySafeterSession)
            .where(JoySafeterSession.id == session_id)
            .with_for_update()
        )
        result = await self.db.execute(
            select(func.coalesce(func.max(JoySafeterSessionEvent.seq), 0)).where(
                JoySafeterSessionEvent.session_id == session_id
            )
        )
        return result.scalar() + 1

    async def attach_memory_stores(
        self,
        session_id: uuid.UUID,
        resources: list[dict],
    ) -> list:
        from app.joysafeter_domain.models.joysafeter_memory import JoySafeterSessionMemoryStore

        created = []
        for res in resources:
            row = JoySafeterSessionMemoryStore(
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

    async def list_session_memory_stores(self, session_id: uuid.UUID) -> list:
        from app.joysafeter_domain.models.joysafeter_memory import JoySafeterSessionMemoryStore

        result = await self.db.execute(
            select(JoySafeterSessionMemoryStore).where(
                JoySafeterSessionMemoryStore.session_id == session_id
            )
        )
        return list(result.scalars().all())

    async def mark_event_processed(self, event_id: uuid.UUID) -> None:
        await self.db.execute(
            update(JoySafeterSessionEvent)
            .where(JoySafeterSessionEvent.id == event_id)
            .values(processed_at=func.coalesce(JoySafeterSessionEvent.processed_at, func.now()))
        )
        await self.db.commit()

    async def list_unprocessed_events(
        self, session_id: uuid.UUID, event_types: list[str], limit: int = 100
    ) -> list[JoySafeterSessionEvent]:
        q = select(JoySafeterSessionEvent).where(
            and_(
                JoySafeterSessionEvent.session_id == session_id,
                JoySafeterSessionEvent.processed_at.is_(None),
                JoySafeterSessionEvent.event_type.in_(event_types),
            )
        ).order_by(JoySafeterSessionEvent.id.asc()).limit(limit)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def batch_insert_session_events(self, events: list[dict]) -> list:
        if not events:
            return []

        # Group events by session_id
        groups: dict[uuid.UUID, list[dict]] = defaultdict(list)
        for ev in events:
            groups[ev["session_id"]].append(ev)

        created = []
        for session_id, group in groups.items():
            # Lock session row and compute max seq
            await self.db.execute(
                select(JoySafeterSession)
                .where(JoySafeterSession.id == session_id)
                .with_for_update()
            )
            result = await self.db.execute(
                select(func.coalesce(func.max(JoySafeterSessionEvent.seq), 0)).where(
                    JoySafeterSessionEvent.session_id == session_id
                )
            )
            max_seq = result.scalar()

            # Assign sequential seq numbers and bulk insert
            for i, ev in enumerate(group, start=1):
                event = JoySafeterSessionEvent(
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
        return created

    async def list_session_events_filtered(
        self,
        session_id: uuid.UUID,
        after_seq: Optional[int],
        limit: int,
        event_types: list[str],
    ) -> list[JoySafeterSessionEvent]:
        q = select(JoySafeterSessionEvent).where(
            JoySafeterSessionEvent.session_id == session_id
        )
        if after_seq is not None:
            q = q.where(JoySafeterSessionEvent.seq > after_seq)
        if event_types:
            q = q.where(JoySafeterSessionEvent.event_type.in_(event_types))
        q = q.order_by(JoySafeterSessionEvent.id.asc()).limit(limit)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def list_all_memories_for_session(self, session_id: uuid.UUID) -> list[dict]:
        from app.joysafeter_domain.models.joysafeter_memory import (
            JoySafeterMemory,
            JoySafeterSessionMemoryStore,
        )

        # Get all mounted stores for this session
        result = await self.db.execute(
            select(JoySafeterSessionMemoryStore).where(
                JoySafeterSessionMemoryStore.session_id == session_id
            )
        )
        mounts = list(result.scalars().all())

        output = []
        for mount in mounts:
            # Load all memories for this store
            mem_result = await self.db.execute(
                select(JoySafeterMemory).where(
                    JoySafeterMemory.store_id == mount.store_id
                )
            )
            memories = list(mem_result.scalars().all())
            output.append(
                {
                    "store_id": mount.store_id,
                    "mount_name": mount.mount_name,
                    "access": mount.access,
                    "memories": [
                        {"path": m.path, "content": m.content} for m in memories
                    ],
                }
            )
        return output
