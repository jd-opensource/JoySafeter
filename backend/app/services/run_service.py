"""
Service layer for durable agent runs.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Awaitable, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import RedisClient
from app.core.settings import settings
from app.models.agent_run import AgentRun, AgentRunEvent, AgentRunSnapshot, AgentRunStatus
from app.repositories.agent_run import AgentRunRepository
from app.services.agent_registry import AgentDefinition
from app.services.run_reducers import agent_registry
from app.utils.datetime import utc_now
from app.websocket.run_subscription_manager import run_subscription_manager

# Throttle Redis snapshot writes for content_delta events (500ms per run).
_SNAPSHOT_THROTTLE_SECONDS = 0.5
_snapshot_last_published: dict[str, float] = {}


def _build_snapshot_dict(run_id: str, snapshot: AgentRunSnapshot) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": snapshot.status,
        "last_seq": snapshot.last_seq,
        "projection": snapshot.projection,
    }


class RunService:
    """Orchestrates durable agent run lifecycle, event sourcing, and snapshot management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AgentRunRepository(db)

    async def list_agents(self) -> list[AgentDefinition]:
        """Return all registered agent definitions.

        Returns:
            List of available agent definitions.
        """
        return agent_registry.list_definitions()

    def get_agent_definition(self, agent_name: str) -> AgentDefinition:
        """Look up an agent definition by name.

        Args:
            agent_name: Registered name of the agent.

        Returns:
            The matching agent definition.

        Raises:
            ValueError: If no agent with the given name is registered.
        """
        try:
            return agent_registry.get(agent_name)
        except KeyError:
            raise ValueError(f"Unknown agent: {agent_name}")

    def get_agent_display_name(self, agent_name: str | None) -> str | None:
        """Return the human-readable display name for an agent.

        Args:
            agent_name: Registered agent name, or None.

        Returns:
            The display name if the agent is found, otherwise the raw agent_name.
        """
        definition = agent_registry.find(agent_name)
        return definition.display_name if definition else agent_name

    async def create_run(
        self,
        *,
        user_id: str,
        agent_name: str,
        graph_id: uuid.UUID,
        thread_id: Optional[str],
        message: str,
        input: Optional[dict[str, Any]] = None,
        workspace_id: Optional[uuid.UUID] = None,
        source: str = "run_center",
        run_type: Optional[str] = None,
    ) -> AgentRun:
        """Create a new agent run with its initial snapshot and user message event.

        Args:
            user_id: ID of the user initiating the run.
            agent_name: Registered agent name to execute.
            graph_id: Graph to run the agent against.
            thread_id: Conversation thread ID; auto-generated if None.
            message: Initial user message for the run.
            input: Optional extra input parameters forwarded to the agent.
            workspace_id: Optional workspace scope for the run.
            source: Origin label (e.g. "run_center", "skills_creator_page").
            run_type: Override the agent's default run type if provided.

        Returns:
            The newly created AgentRun record.

        Raises:
            ValueError: If agent_name is not registered.
        """
        definition = self.get_agent_definition(agent_name)
        resolved_thread_id = thread_id or str(uuid.uuid4())
        run_input = dict(input or {})
        run = AgentRun(
            user_id=user_id,
            workspace_id=workspace_id,
            graph_id=graph_id,
            thread_id=resolved_thread_id,
            run_type=definition.run_type if run_type is None else run_type,
            agent_name=agent_name,
            source=source,
            status=AgentRunStatus.QUEUED,
            title=message[:100] if message else definition.display_name,
            request_payload={
                "agent_name": agent_name,
                "message": message,
                "graph_id": str(graph_id),
                "thread_id": resolved_thread_id,
                "input": run_input,
                # Spread run_input at top level so consumers that read keys
                # directly (e.g. edit_skill_id) continue to work.
                **run_input,
            },
            last_heartbeat_at=utc_now(),
        )
        self.db.add(run)
        await self.db.flush()

        snapshot = AgentRunSnapshot(
            run_id=run.id,
            last_seq=0,
            status=run.status.value,
            projection=definition.make_initial_projection(
                {
                    "graph_id": str(graph_id),
                    "thread_id": resolved_thread_id,
                    **run_input,
                },
                run.status.value,
            ),
        )
        self.db.add(snapshot)
        await self.db.flush()

        await self.append_event(
            run_id=run.id,
            event_type="user_message_added",
            payload={
                "message": {
                    "id": f"msg-user-{uuid.uuid4()}",
                    "role": "user",
                    "content": message,
                    "timestamp": int(utc_now().timestamp() * 1000),
                }
            },
            commit=False,
        )
        await self.db.commit()
        await self.db.refresh(run)
        await RedisClient.set_run_snapshot(
            str(run.id),
            _build_snapshot_dict(str(run.id), snapshot),
        )
        return run

    async def create_skill_creator_run(
        self,
        *,
        user_id: str,
        graph_id: uuid.UUID,
        thread_id: Optional[str],
        message: str,
        edit_skill_id: Optional[str],
        workspace_id: Optional[uuid.UUID] = None,
    ) -> AgentRun:
        """Create a run specifically for the skill_creator agent.

        Args:
            user_id: ID of the user initiating the run.
            graph_id: Graph to run the agent against.
            thread_id: Conversation thread ID; auto-generated if None.
            message: Initial user message for skill creation/editing.
            edit_skill_id: Existing skill ID to edit, or None for new skill creation.
            workspace_id: Optional workspace scope for the run.

        Returns:
            The newly created AgentRun record.
        """
        return await self.create_run(
            user_id=user_id,
            agent_name="skill_creator",
            graph_id=graph_id,
            thread_id=thread_id,
            message=message,
            input={"edit_skill_id": edit_skill_id},
            workspace_id=workspace_id,
            source="skills_creator_page",
        )

    async def get_run(self, run_id: uuid.UUID, user_id: str) -> Optional[AgentRun]:
        """Fetch a single run by ID, scoped to the given user.

        Args:
            run_id: Unique identifier of the run.
            user_id: Owner user ID used for access control.

        Returns:
            The AgentRun if found and owned by the user, otherwise None.
        """
        return await self.repo.get_by_id_and_user(run_id, user_id)

    async def get_snapshot(self, run_id: uuid.UUID, user_id: str) -> Optional[AgentRunSnapshot]:
        """Fetch the latest projection snapshot for a run.

        Args:
            run_id: Unique identifier of the run.
            user_id: Owner user ID used for access control.

        Returns:
            The snapshot if the run exists and belongs to the user, otherwise None.
        """
        run = await self.get_run(run_id, user_id)
        if not run:
            return None
        return await self.repo.get_snapshot(run_id)

    async def list_events_after(
        self, run_id: uuid.UUID, user_id: str, after_seq: int = 0, limit: int = 500
    ) -> list[AgentRunEvent]:
        """List run events with sequence numbers greater than after_seq.

        Args:
            run_id: Unique identifier of the run.
            user_id: Owner user ID used for access control.
            after_seq: Return only events with seq > this value.
            limit: Maximum number of events to return.

        Returns:
            List of events ordered by sequence number, or empty list if the
            run is not found.
        """
        run = await self.get_run(run_id, user_id)
        if not run:
            return []
        return list(await self.repo.list_events_after(run_id, after_seq=after_seq, limit=limit))

    async def find_latest_active_skill_creator_run(
        self, *, user_id: str, graph_id: uuid.UUID, thread_id: Optional[str] = None
    ) -> Optional[AgentRun]:
        """Find the most recent active skill_creator run for a user and graph.

        Args:
            user_id: Owner user ID.
            graph_id: Graph the run belongs to.
            thread_id: Optional thread ID to narrow the search.

        Returns:
            The latest active skill_creator run, or None.
        """
        return await self.find_latest_active_run(
            user_id=user_id,
            agent_name="skill_creator",
            graph_id=graph_id,
            thread_id=thread_id,
        )

    async def find_latest_active_run(
        self,
        *,
        user_id: str,
        agent_name: str,
        graph_id: uuid.UUID,
        thread_id: Optional[str] = None,
    ) -> Optional[AgentRun]:
        """Find the most recent active run for a given agent, user, and graph.

        Args:
            user_id: Owner user ID.
            agent_name: Registered agent name.
            graph_id: Graph the run belongs to.
            thread_id: Optional thread ID to narrow the search.

        Returns:
            The latest active AgentRun, or None if no active run exists.
        """
        return await self.repo.find_latest_active_run(
            user_id=user_id,
            agent_name=agent_name,
            graph_id=graph_id,
            thread_id=thread_id,
        )

    async def list_recent_runs(
        self,
        *,
        user_id: str,
        run_type: Optional[str] = None,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        """List recent runs for a user with optional filters.

        Args:
            user_id: Owner user ID.
            run_type: Filter by run type (e.g. "skill_creator").
            agent_name: Filter by agent name.
            status: Filter by run status string.
            search: Free-text search against run titles.
            limit: Maximum number of runs to return.

        Returns:
            List of matching AgentRun records, most recent first.
        """
        return list(
            await self.repo.list_recent_runs_for_user(
                user_id=user_id,
                run_type=run_type,
                agent_name=agent_name,
                status=status,
                search=search,
                limit=limit,
            )
        )

    async def mark_status(
        self,
        *,
        run_id: uuid.UUID,
        user_id: Optional[str],
        status: AgentRunStatus,
        runtime_owner_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        result_summary: Optional[dict[str, Any]] = None,
    ) -> Optional[AgentRun]:
        """Transition a run to a new status, update its snapshot, and broadcast the change.

        Handles runtime ownership assignment on RUNNING, clears it on terminal
        states, and publishes status updates via Redis and WebSocket.

        Args:
            run_id: Unique identifier of the run.
            user_id: Owner user ID, or None for system-level transitions.
            status: Target status to transition to.
            runtime_owner_id: Runtime instance claiming this run (for RUNNING).
            error_code: Machine-readable error code (for FAILED).
            error_message: Human-readable error description (for FAILED).
            result_summary: Optional summary dict merged into the run record.

        Returns:
            The updated AgentRun, or None if the run was not found.
        """
        run = await self.repo.get_run_for_update(run_id, user_id=user_id)
        if not run:
            return None

        heartbeat_at = utc_now()
        run.status = status
        run.error_code = error_code
        run.error_message = error_message
        run.last_heartbeat_at = heartbeat_at
        if status == AgentRunStatus.RUNNING:
            run.runtime_owner_id = runtime_owner_id or run.runtime_owner_id or settings.run_runtime_instance_id
        elif status in {
            AgentRunStatus.INTERRUPT_WAIT,
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }:
            run.runtime_owner_id = None
        if result_summary is not None:
            run.result_summary = result_summary
        if status in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
            run.finished_at = heartbeat_at
            _snapshot_last_published.pop(str(run_id), None)

        snapshot = await self.repo.get_snapshot(run_id)
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
        try:
            coros: list[Awaitable[Any]] = []
            if snapshot:
                coros.append(
                    RedisClient.set_run_snapshot(
                        str(run.id),
                        _build_snapshot_dict(str(run.id), snapshot),
                    )
                )
            coros.append(
                run_subscription_manager.broadcast_event(
                    str(run.id),
                    {
                        "type": "run_status",
                        "run_id": str(run.id),
                        "status": status.value,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                )
            )
            await asyncio.gather(*coros)
        except Exception as exc:
            logger.warning(f"Failed to publish run status to Redis/WS | run_id={run_id} | error={exc}")
        return run

    async def touch_run_heartbeat(
        self,
        *,
        run_id: uuid.UUID,
        runtime_owner_id: Optional[str] = None,
    ) -> Optional[AgentRun]:
        """Update the heartbeat timestamp for an active run to prevent stale-run recovery.

        Only updates runs in QUEUED or RUNNING status. Also sets the
        runtime_owner_id if not already assigned.

        Args:
            run_id: Unique identifier of the run.
            runtime_owner_id: Runtime instance ID to record as the owner.

        Returns:
            The updated AgentRun, or None if the run was not found.
        """
        run = await self.repo.get_run_for_update(run_id)
        if not run:
            return None
        if run.status not in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING}:
            return run

        run.runtime_owner_id = runtime_owner_id or run.runtime_owner_id or settings.run_runtime_instance_id
        run.last_heartbeat_at = utc_now()
        await self.db.commit()
        return run

    async def recover_stale_incomplete_runs(
        self,
        *,
        runtime_owner_id: str,
        stale_before: datetime,
    ) -> list[AgentRun]:
        """Mark stale incomplete runs as FAILED and record recovery metadata.

        Finds runs whose last heartbeat is older than stale_before and
        transitions them to FAILED with a ``runtime_recovered`` error code.

        Args:
            runtime_owner_id: ID of the runtime performing the recovery.
            stale_before: Cutoff timestamp; runs with an older heartbeat are
                considered stale.

        Returns:
            List of AgentRun records that were recovered (marked as FAILED).
        """
        stale_runs = await self.repo.list_recoverable_stale_runs(
            stale_before=stale_before,
        )
        recovered: list[AgentRun] = []
        recovered_at = utc_now().isoformat()
        for run in stale_runs:
            result_summary = dict(run.result_summary or {})
            result_summary.update(
                {
                    "recovered_by_runtime": runtime_owner_id,
                    "recovered_at": recovered_at,
                    "previous_runtime_owner_id": run.runtime_owner_id,
                }
            )
            error_message = (
                "Recovered stale run after runtime heartbeat timeout"
                if run.runtime_owner_id
                else "Recovered stale run without active runtime owner heartbeat"
            )
            updated_run = await self.mark_status(
                run_id=run.id,
                user_id=run.user_id,
                status=AgentRunStatus.FAILED,
                error_code="runtime_recovered",
                error_message=error_message,
                result_summary=result_summary,
            )
            if updated_run is not None:
                recovered.append(updated_run)
        return recovered

    async def append_event(
        self,
        *,
        run_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
        trace_id: Optional[uuid.UUID] = None,
        observation_id: Optional[uuid.UUID] = None,
        parent_observation_id: Optional[uuid.UUID] = None,
        commit: bool = True,
    ) -> AgentRunEvent:
        """Append a new event to a run's event log and update its snapshot projection.

        Increments the run's sequence counter, applies the agent's reducer to
        update the snapshot projection, and publishes the event via Redis and
        WebSocket. Snapshot writes to Redis are throttled for content_delta events.

        Args:
            run_id: Unique identifier of the run.
            event_type: Type label for the event (e.g. "user_message_added",
                "content_delta").
            payload: Arbitrary event data.
            trace_id: Optional tracing ID for observability.
            observation_id: Optional observation ID for observability.
            parent_observation_id: Optional parent observation ID for nesting.
            commit: Whether to commit the transaction and publish to Redis/WS.

        Returns:
            The newly created AgentRunEvent.

        Raises:
            ValueError: If the run is not found.
        """
        run = await self.repo.get_run_for_update(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        next_seq = int(run.last_seq) + 1
        event = AgentRunEvent(
            run_id=run.id,
            seq=next_seq,
            event_type=event_type,
            payload=payload,
            trace_id=trace_id,
            observation_id=observation_id,
            parent_observation_id=parent_observation_id,
        )
        self.db.add(event)
        run.last_seq = next_seq
        run.last_heartbeat_at = utc_now()

        snapshot = await self.repo.get_snapshot(run.id)
        if snapshot is None:
            snapshot = AgentRunSnapshot(
                run_id=run.id,
                last_seq=0,
                status=run.status.value,
                projection={},
            )
            self.db.add(snapshot)

        definition = agent_registry.find(run.agent_name)
        if definition is not None:
            snapshot.projection = definition.reducer(
                snapshot.projection,
                event_type=event_type,
                payload=payload,
                status=run.status.value,
            )
        snapshot.last_seq = next_seq
        snapshot.status = run.status.value

        await self.db.flush()
        if commit:
            await self.db.commit()
            try:
                # Throttle Redis snapshot writes for content_delta —
                # always publish the event, but skip the heavier snapshot
                # cache refresh if we published one within the last 500ms.
                run_id_str = str(run.id)
                now = utc_now().timestamp()
                should_publish_snapshot = True
                if event_type == "content_delta":
                    last = _snapshot_last_published.get(run_id_str, 0.0)
                    if (now - last) < _SNAPSHOT_THROTTLE_SECONDS:
                        should_publish_snapshot = False

                if should_publish_snapshot:
                    await RedisClient.set_run_snapshot(
                        run_id_str,
                        _build_snapshot_dict(run_id_str, snapshot),
                    )
                    _snapshot_last_published[run_id_str] = now

                await asyncio.gather(
                    RedisClient.publish_run_event(
                        run_id_str,
                        {
                            "run_id": run_id_str,
                            "seq": event.seq,
                            "event_type": event.event_type,
                            "data": event.payload,
                        },
                    ),
                    run_subscription_manager.broadcast_event(
                        run_id_str,
                        {
                            "type": "event",
                            "run_id": run_id_str,
                            "seq": event.seq,
                            "event_type": event.event_type,
                            "data": event.payload,
                            "trace_id": str(event.trace_id) if event.trace_id else None,
                            "observation_id": str(event.observation_id) if event.observation_id else None,
                            "parent_observation_id": (
                                str(event.parent_observation_id) if event.parent_observation_id else None
                            ),
                            "created_at": event.created_at.isoformat() if event.created_at else None,
                        },
                    ),
                )
            except Exception as exc:
                logger.warning(f"Failed to publish run event to Redis/WS | run_id={run_id} | error={exc}")
        return event
