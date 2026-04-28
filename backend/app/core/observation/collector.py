# backend/app/core/observation/collector.py
"""Central ObservationCollector — all engines call this to emit trace observations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.observation.model import Observation
from app.core.observation.types import ObservationLevel, ObservationType, SpanHandle


class ObservationCollector:
    """Creates, tracks, and finalises observation spans for a single trace."""

    def __init__(
        self,
        *,
        trace_id: uuid.UUID,
        execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
        writer: Any,
        broadcaster: Any,
    ) -> None:
        self._trace_id = trace_id
        self._execution_id = execution_id
        self._workspace_id = workspace_id
        self._writer = writer
        self._broadcaster = broadcaster

        self._open_spans: dict[uuid.UUID, Observation] = {}
        self._has_error = False
        self._total_tokens = 0
        self._total_cost = 0.0

    # ------------------------------------------------------------------
    # Span lifecycle
    # ------------------------------------------------------------------

    async def start_span(
        self,
        observation_type: ObservationType,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> SpanHandle:
        obs = Observation(
            id=uuid.uuid4(),
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            parent_observation_id=parent_id,
            type=str(observation_type),
            name=name,
            level=str(level),
            start_time=datetime.now(timezone.utc),
            input=input,
            meta=metadata,
        )
        await self._writer.insert(obs)
        self._open_spans[obs.id] = obs
        await self._broadcaster.emit("span_open", self._obs_to_dict(obs))
        return SpanHandle(observation_id=obs.id, collector=self)

    async def end_span(
        self,
        span: SpanHandle,
        *,
        output: dict | None = None,
        level: ObservationLevel | None = None,
    ) -> None:
        end_time = datetime.now(timezone.utc)
        fields: dict[str, Any] = {"end_time": end_time}
        if output is not None:
            fields["output"] = output
        if level is not None:
            fields["level"] = str(level)

        await self._writer.update(span.observation_id, fields)
        self._open_spans.pop(span.observation_id, None)

        # Build a dict snapshot for broadcasting
        obs = Observation(
            id=span.observation_id,
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            type="",
            name="",
            start_time=datetime.now(timezone.utc),
            end_time=end_time,
        )
        if output is not None:
            obs.output = output
        await self._broadcaster.emit("span_close", self._obs_to_dict(obs))

    # ------------------------------------------------------------------
    # Convenience: instant (complete) observations
    # ------------------------------------------------------------------

    async def record_generation(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        output: dict | None = None,
        model: str | None = None,
        usage_details: dict | None = None,
        cost_details: dict | None = None,
        latency_ms: int | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs = Observation(
            id=uuid.uuid4(),
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            parent_observation_id=parent_id,
            type=str(ObservationType.GENERATION),
            name=name,
            level=str(level),
            start_time=now,
            end_time=now,
            input=input,
            output=output,
            model=model,
            usage_details=usage_details,
            cost_details=cost_details,
            meta=metadata,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))

        # Accumulate tokens and cost
        if usage_details and "total" in usage_details:
            self._total_tokens += usage_details["total"]
        if cost_details and "total" in cost_details:
            self._total_cost += cost_details["total"]

        return obs.id

    async def record_tool(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        output: dict | None = None,
        latency_ms: int | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs = Observation(
            id=uuid.uuid4(),
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            parent_observation_id=parent_id,
            type=str(ObservationType.TOOL),
            name=name,
            level=str(level),
            start_time=now,
            end_time=now,
            input=input,
            output=output,
            meta=metadata,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))
        return obs.id

    async def record_event(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        obs = Observation(
            id=uuid.uuid4(),
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            parent_observation_id=parent_id,
            type=str(ObservationType.EVENT),
            name=name,
            level=str(level),
            start_time=datetime.now(timezone.utc),
            end_time=None,
            input=input,
            meta=metadata,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))

        if level == ObservationLevel.ERROR:
            self._has_error = True

        return obs.id

    # ------------------------------------------------------------------
    # Convenience: named span starters
    # ------------------------------------------------------------------

    async def start_agent(self, name: str, **kwargs: Any) -> SpanHandle:
        return await self.start_span(ObservationType.AGENT, name, **kwargs)

    async def start_chain(self, name: str, **kwargs: Any) -> SpanHandle:
        return await self.start_span(ObservationType.CHAIN, name, **kwargs)

    # ------------------------------------------------------------------
    # Convenience: additional instant records
    # ------------------------------------------------------------------

    async def record_retriever(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        output: dict | None = None,
        latency_ms: int | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs = Observation(
            id=uuid.uuid4(),
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            parent_observation_id=parent_id,
            type=str(ObservationType.RETRIEVER),
            name=name,
            level=str(level),
            start_time=now,
            end_time=now,
            input=input,
            output=output,
            meta=metadata,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))
        return obs.id

    async def record_embedding(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        output: dict | None = None,
        model: str | None = None,
        usage_details: dict | None = None,
        cost_details: dict | None = None,
        latency_ms: int | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs = Observation(
            id=uuid.uuid4(),
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            parent_observation_id=parent_id,
            type=str(ObservationType.EMBEDDING),
            name=name,
            level=str(level),
            start_time=now,
            end_time=now,
            input=input,
            output=output,
            model=model,
            usage_details=usage_details,
            cost_details=cost_details,
            meta=metadata,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))
        return obs.id

    # ------------------------------------------------------------------
    # Flush / Finalize
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        await self._writer.flush()

    async def finalize(self) -> None:
        # Close any open spans with WARNING level
        for obs_id, obs in list(self._open_spans.items()):
            end_time = datetime.now(timezone.utc)
            fields: dict[str, Any] = {
                "end_time": end_time,
                "level": str(ObservationLevel.WARNING),
            }
            await self._writer.update(obs_id, fields)

        self._open_spans.clear()
        await self._writer.finalize()

        # Emit trace_complete with aggregated stats
        status = "error" if self._has_error else "complete"
        await self._broadcaster.emit("trace_complete", {
            "trace_id": str(self._trace_id),
            "execution_id": str(self._execution_id),
            "status": status,
            "total_tokens": self._total_tokens,
            "total_cost": self._total_cost,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _obs_to_dict(obs: Observation) -> dict[str, Any]:
        return {
            "id": str(obs.id),
            "trace_id": str(obs.trace_id),
            "parent_observation_id": str(obs.parent_observation_id) if obs.parent_observation_id else None,
            "type": obs.type,
            "name": obs.name,
            "level": obs.level,
            "start_time": obs.start_time.isoformat() if obs.start_time else None,
            "end_time": obs.end_time.isoformat() if obs.end_time else None,
            "completion_start_time": (
                obs.completion_start_time.isoformat() if obs.completion_start_time else None
            ),
            "input": obs.input,
            "output": obs.output,
            "metadata": obs.meta,
            "model": obs.model,
            "usage_details": obs.usage_details,
            "cost_details": obs.cost_details,
            "tool_calls": obs.tool_calls,
            "tool_call_names": obs.tool_call_names,
        }
