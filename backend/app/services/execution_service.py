"""
Service layer for CLI agent executions.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import (
    Execution,
    ExecutionEvent,
    ExecutionSnapshot,
    ExecutionSource,
    MissionExecutionStatus,
)
from app.repositories.execution import ExecutionRepository
from app.services.execution_reducer import apply_execution_event, make_initial_projection
from app.utils.datetime import utc_now


class ExecutionService:
    """Orchestrates execution lifecycle, event sourcing, and snapshot management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExecutionRepository(db)

    async def create_execution(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: str,
        source: ExecutionSource,
        runtime_type: str,
        source_id: Optional[str] = None,
        title: Optional[str] = None,
        mission_id: Optional[uuid.UUID] = None,
        agent_profile_id: Optional[uuid.UUID] = None,
        parent_execution_id: Optional[uuid.UUID] = None,
        runtime_config: Optional[dict[str, Any]] = None,
    ) -> Execution:
        execution = Execution(
            workspace_id=workspace_id,
            user_id=user_id,
            source=source,
            source_id=source_id,
            status=MissionExecutionStatus.QUEUED,
            title=title,
            mission_id=mission_id,
            agent_profile_id=agent_profile_id,
            parent_execution_id=parent_execution_id,
            runtime_type=runtime_type,
            runtime_config=runtime_config,
            last_heartbeat_at=utc_now(),
        )
        self.db.add(execution)
        await self.db.flush()

        snapshot = ExecutionSnapshot(
            execution_id=execution.id,
            last_seq=0,
            status=execution.status.value,
            projection=make_initial_projection(
                {
                    "source": source.value,
                    "mission_id": str(mission_id) if mission_id else None,
                    "agent_profile_id": str(agent_profile_id) if agent_profile_id else None,
                },
                execution.status.value,
            ),
        )
        self.db.add(snapshot)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def get_execution(self, execution_id: uuid.UUID, user_id: str) -> Optional[Execution]:
        return await self.repo.get_by_id_and_user(execution_id, user_id)

    async def get_snapshot(self, execution_id: uuid.UUID, user_id: str) -> Optional[ExecutionSnapshot]:
        execution = await self.get_execution(execution_id, user_id)
        if not execution:
            return None
        return await self.repo.get_snapshot(execution_id)

    async def list_events_after(
        self, execution_id: uuid.UUID, user_id: str, after_seq: int = 0, limit: int = 500
    ) -> list[ExecutionEvent]:
        execution = await self.get_execution(execution_id, user_id)
        if not execution:
            return []
        return list(await self.repo.list_events_after(execution_id, after_seq=after_seq, limit=limit))

    async def list_executions(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        mission_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> list[Execution]:
        return list(
            await self.repo.list_by_workspace(
                workspace_id=workspace_id,
                user_id=user_id,
                status=status,
                source=source,
                mission_id=mission_id,
                limit=limit,
            )
        )

    async def list_children(
        self, parent_execution_id: uuid.UUID
    ) -> list[Execution]:
        return list(await self.repo.list_children(parent_execution_id))

    async def mark_status(
        self,
        *,
        execution_id: uuid.UUID,
        user_id: Optional[str] = None,
        status: MissionExecutionStatus,
        container_id: Optional[str] = None,
        session_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        result_summary: Optional[dict[str, Any]] = None,
    ) -> Optional[Execution]:
        execution = await self.repo.get_for_update(execution_id, user_id=user_id)
        if not execution:
            return None

        now = utc_now()
        execution.status = status
        execution.error_code = error_code
        execution.error_message = error_message
        execution.last_heartbeat_at = now

        if container_id is not None:
            execution.container_id = container_id
        if session_id is not None:
            execution.session_id = session_id
        if result_summary is not None:
            execution.result_summary = result_summary

        if status == MissionExecutionStatus.RUNNING and not execution.started_at:
            execution.started_at = now
        if status in {MissionExecutionStatus.COMPLETED, MissionExecutionStatus.FAILED, MissionExecutionStatus.CANCELLED}:
            execution.finished_at = now

        snapshot = await self.repo.get_snapshot(execution_id)
        if snapshot:
            snapshot.status = status.value
            projection = dict(snapshot.projection or {})
            projection["status"] = status.value
            if error_message:
                meta = dict(projection.get("meta") or {})
                meta["error"] = error_message
                projection["meta"] = meta
            snapshot.projection = projection

        await self.db.commit()
        return execution

    async def append_event(
        self,
        *,
        execution_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
        trace_id: Optional[uuid.UUID] = None,
        observation_id: Optional[uuid.UUID] = None,
        parent_observation_id: Optional[uuid.UUID] = None,
        commit: bool = True,
    ) -> ExecutionEvent:
        execution = await self.repo.get_for_update(execution_id)
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")

        next_seq = int(execution.last_seq) + 1
        event = ExecutionEvent(
            execution_id=execution.id,
            seq=next_seq,
            event_type=event_type,
            payload=payload,
            trace_id=trace_id,
            observation_id=observation_id,
            parent_observation_id=parent_observation_id,
        )
        self.db.add(event)
        execution.last_seq = next_seq
        execution.last_heartbeat_at = utc_now()

        snapshot = await self.repo.get_snapshot(execution.id)
        if snapshot is None:
            snapshot = ExecutionSnapshot(
                execution_id=execution.id,
                last_seq=0,
                status=execution.status.value,
                projection={},
            )
            self.db.add(snapshot)

        snapshot.projection = apply_execution_event(
            snapshot.projection,
            event_type=event_type,
            payload=payload,
            status=execution.status.value,
        )
        snapshot.last_seq = next_seq
        snapshot.status = execution.status.value

        await self.db.flush()
        if commit:
            await self.db.commit()
        return event

    async def batch_append_events(
        self,
        *,
        execution_id: uuid.UUID,
        events: list[dict[str, Any]],
    ) -> list[ExecutionEvent]:
        """Append multiple events in a single commit.

        Each entry in *events* must contain 'event_type' and 'payload' keys,
        and may optionally include 'trace_id', 'observation_id', and
        'parent_observation_id'.
        """
        results: list[ExecutionEvent] = []
        for evt in events:
            result = await self.append_event(
                execution_id=execution_id,
                event_type=evt["event_type"],
                payload=evt["payload"],
                trace_id=evt.get("trace_id"),
                observation_id=evt.get("observation_id"),
                parent_observation_id=evt.get("parent_observation_id"),
                commit=False,
            )
            results.append(result)
        await self.db.commit()
        return results

    async def touch_heartbeat(
        self, *, execution_id: uuid.UUID
    ) -> Optional[Execution]:
        execution = await self.repo.get_for_update(execution_id)
        if not execution:
            return None
        active = {MissionExecutionStatus.QUEUED, MissionExecutionStatus.DISPATCHED, MissionExecutionStatus.RUNNING}
        if execution.status not in active:
            return execution
        execution.last_heartbeat_at = utc_now()
        await self.db.commit()
        return execution
