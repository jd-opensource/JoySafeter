import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.conductor.models.session import (
    ConductorSession,
    ConductorSessionEvent,
    SessionStatus,
)
from app.utils.datetime import utc_now


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
    ) -> ConductorSession:
        session = ConductorSession(
            agent_id=agent_id,
            title=title,
            status=SessionStatus.IDLE.value,
            metadata_=metadata or {},
            vault_ids=vault_ids or [],
            environment_ref=environment_ref,
            agent_version=agent_version,
            agent_snapshot=agent_snapshot,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_session(self, session_id: uuid.UUID) -> Optional[ConductorSession]:
        result = await self.db.execute(
            select(ConductorSession).where(ConductorSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[ConductorSession], bool]:
        q = select(ConductorSession).where(ConductorSession.archived_at.is_(None))
        if after_id:
            q = q.where(ConductorSession.id < after_id)
        q = q.order_by(ConductorSession.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        sessions = list(result.scalars().all())
        has_more = len(sessions) > limit
        return sessions[:limit], has_more

    async def list_sessions_by_agent(
        self,
        agent_id: uuid.UUID,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[ConductorSession], bool]:
        q = select(ConductorSession).where(
            and_(
                ConductorSession.agent_id == agent_id,
                ConductorSession.archived_at.is_(None),
            )
        )
        if after_id:
            q = q.where(ConductorSession.id < after_id)
        q = q.order_by(ConductorSession.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        sessions = list(result.scalars().all())
        has_more = len(sessions) > limit
        return sessions[:limit], has_more

    async def delete_session(self, session_id: uuid.UUID) -> bool:
        session = await self.get_session(session_id)
        if not session:
            return False
        await self.db.delete(session)
        await self.db.commit()
        return True

    async def archive_session(self, session_id: uuid.UUID) -> bool:
        session = await self.get_session(session_id)
        if not session:
            return False
        if session.archived_at:
            return True
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
            select(ConductorSession)
            .where(ConductorSession.id == session_id)
            .with_for_update()
        )
        session = result.scalar_one_or_none()
        if not session:
            return False
        session.status = status
        if stop_reason is not None:
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
            select(ConductorSession)
            .where(ConductorSession.id == session_id)
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

        # Per-model breakdown
        model_name = task_usage.get("model")
        if model_name:
            by_model = current.get("by_model", {})
            model_entry = by_model.get(model_name, {})
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ):
                model_entry[key] = model_entry.get(key, 0) + (task_usage.get(key, 0) or 0)
            by_model[model_name] = model_entry
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
    ) -> ConductorSessionEvent:
        next_seq = await self._next_seq(session_id)
        event = ConductorSessionEvent(
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
    ) -> tuple[list[ConductorSessionEvent], bool]:
        q = select(ConductorSessionEvent).where(
            ConductorSessionEvent.session_id == session_id
        )
        if after_seq is not None:
            q = q.where(ConductorSessionEvent.seq > after_seq)
        q = q.order_by(ConductorSessionEvent.seq.asc()).limit(limit + 1)
        result = await self.db.execute(q)
        events = list(result.scalars().all())
        has_more = len(events) > limit
        return events[:limit], has_more

    async def _next_seq(self, session_id: uuid.UUID) -> int:
        await self.db.execute(
            select(ConductorSession)
            .where(ConductorSession.id == session_id)
            .with_for_update()
        )
        result = await self.db.execute(
            select(func.coalesce(func.max(ConductorSessionEvent.seq), 0)).where(
                ConductorSessionEvent.session_id == session_id
            )
        )
        return result.scalar() + 1

    async def attach_memory_stores(
        self,
        session_id: uuid.UUID,
        resources: list[dict],
    ) -> list:
        from app.conductor.models.memory import ConductorSessionMemoryStore

        created = []
        for res in resources:
            row = ConductorSessionMemoryStore(
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
        from app.conductor.models.memory import ConductorSessionMemoryStore

        result = await self.db.execute(
            select(ConductorSessionMemoryStore).where(
                ConductorSessionMemoryStore.session_id == session_id
            )
        )
        return list(result.scalars().all())

    async def mark_event_processed(self, event_id: uuid.UUID) -> None:
        await self.db.execute(
            update(ConductorSessionEvent)
            .where(ConductorSessionEvent.id == event_id)
            .values(processed_at=func.coalesce(ConductorSessionEvent.processed_at, func.now()))
        )
        await self.db.commit()

    async def list_unprocessed_events(
        self, session_id: uuid.UUID, event_types: list[str]
    ) -> list[ConductorSessionEvent]:
        q = select(ConductorSessionEvent).where(
            and_(
                ConductorSessionEvent.session_id == session_id,
                ConductorSessionEvent.processed_at.is_(None),
                ConductorSessionEvent.event_type.in_(event_types),
            )
        ).order_by(ConductorSessionEvent.seq.asc())
        result = await self.db.execute(q)
        return list(result.scalars().all())
