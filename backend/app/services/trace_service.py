"""
Execution trace service.

Encapsulate CRUD operations for ExecutionTrace / ExecutionObservation.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.execution_trace import (
    ExecutionObservation,
    ExecutionTrace,
    ObservationLevel,
    ObservationStatus,
    ObservationType,
    TraceStatus,
)
from app.services.base import BaseService


class TraceService(BaseService):
    """Execution trace service."""

    # ==================== Query Helpers ====================

    @staticmethod
    def _apply_trace_filters(
        stmt,
        *,
        graph_id: Optional[uuid.UUID] = None,
        workspace_id: Optional[uuid.UUID] = None,
        thread_id: Optional[str] = None,
    ):
        if graph_id is not None:
            stmt = stmt.where(ExecutionTrace.graph_id == graph_id)
        if workspace_id is not None:
            stmt = stmt.where(ExecutionTrace.workspace_id == workspace_id)
        if thread_id is not None:
            stmt = stmt.where(ExecutionTrace.thread_id == thread_id)
        return stmt

    # ==================== Trace CRUD ====================

    async def create_trace(
        self,
        *,
        trace_id: Optional[uuid.UUID] = None,
        workspace_id: Optional[uuid.UUID] = None,
        graph_id: Optional[uuid.UUID] = None,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None,
        name: Optional[str] = None,
        input_data: Optional[dict] = None,
        metadata: Optional[dict] = None,
        tags: Optional[list] = None,
    ) -> ExecutionTrace:
        """Create a new execution trace."""
        trace = ExecutionTrace(
            id=trace_id or uuid.uuid4(),
            workspace_id=workspace_id,
            graph_id=graph_id,
            thread_id=thread_id,
            user_id=user_id,
            name=name,
            status=TraceStatus.RUNNING,
            input=input_data,
            metadata_=metadata,
            tags=tags,
            start_time=datetime.now(timezone.utc),
        )
        self.db.add(trace)
        await self.db.flush()
        return trace

    async def complete_trace(
        self,
        trace_id: uuid.UUID,
        *,
        status: TraceStatus = TraceStatus.COMPLETED,
        output: Optional[dict] = None,
        total_tokens: Optional[int] = None,
        total_cost: Optional[float] = None,
    ) -> Optional[ExecutionTrace]:
        """Complete an execution trace."""
        result = await self.db.execute(select(ExecutionTrace).where(ExecutionTrace.id == trace_id))
        trace = result.scalar_one_or_none()
        if trace is None:
            return None

        now = datetime.now(timezone.utc)
        trace.status = status
        trace.output = output
        trace.end_time = now
        trace.duration_ms = int((now - trace.start_time).total_seconds() * 1000)
        trace.total_tokens = total_tokens
        trace.total_cost = total_cost
        trace.updated_at = now
        await self.db.flush()
        return trace

    async def get_trace(self, trace_id: uuid.UUID) -> Optional[ExecutionTrace]:
        """Get a single Trace (with observations)."""
        result = await self.db.execute(
            select(ExecutionTrace)
            .options(selectinload(ExecutionTrace.observations))
            .where(ExecutionTrace.id == trace_id)
        )
        return result.scalar_one_or_none()

    async def list_traces(
        self,
        *,
        graph_id: Optional[uuid.UUID] = None,
        workspace_id: Optional[uuid.UUID] = None,
        thread_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ExecutionTrace]:
        """List traces (without observation details, to reduce overhead)."""
        stmt = select(ExecutionTrace).order_by(ExecutionTrace.start_time.desc())
        stmt = self._apply_trace_filters(stmt, graph_id=graph_id, workspace_id=workspace_id, thread_id=thread_id)

        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_traces(
        self,
        *,
        graph_id: Optional[uuid.UUID] = None,
        workspace_id: Optional[uuid.UUID] = None,
        thread_id: Optional[str] = None,
    ) -> int:
        """Count traces matching the given filters (for pagination total)."""
        stmt = select(func.count()).select_from(ExecutionTrace)
        stmt = self._apply_trace_filters(stmt, graph_id=graph_id, workspace_id=workspace_id, thread_id=thread_id)
        result = await self.db.execute(stmt)
        total = result.scalar_one()
        return int(total or 0)

    # ==================== Observation CRUD ====================

    async def create_observation(
        self,
        *,
        observation_id: Optional[uuid.UUID] = None,
        trace_id: uuid.UUID,
        parent_observation_id: Optional[uuid.UUID] = None,
        type: ObservationType,
        name: Optional[str] = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
        start_time: Optional[datetime] = None,
        input_data: Optional[dict] = None,
        model_name: Optional[str] = None,
        model_provider: Optional[str] = None,
        model_parameters: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> ExecutionObservation:
        """Create a new Observation."""
        obs = ExecutionObservation(
            id=observation_id or uuid.uuid4(),
            trace_id=trace_id,
            parent_observation_id=parent_observation_id,
            type=type,
            name=name,
            level=level,
            start_time=start_time or datetime.now(timezone.utc),
            input=input_data,
            model_name=model_name,
            model_provider=model_provider,
            model_parameters=model_parameters,
            metadata_=metadata,
        )
        self.db.add(obs)
        await self.db.flush()
        return obs

    async def complete_observation(
        self,
        observation_id: uuid.UUID,
        *,
        output: Optional[dict] = None,
        level: Optional[ObservationLevel] = None,
        status_message: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        input_cost: Optional[float] = None,
        output_cost: Optional[float] = None,
        total_cost: Optional[float] = None,
        completion_start_time: Optional[datetime] = None,
    ) -> Optional[ExecutionObservation]:
        """Complete an Observation."""
        result = await self.db.execute(select(ExecutionObservation).where(ExecutionObservation.id == observation_id))
        obs = result.scalar_one_or_none()
        if obs is None:
            return None

        now = datetime.now(timezone.utc)
        obs.end_time = now
        obs.duration_ms = int((now - obs.start_time).total_seconds() * 1000)
        obs.status = ObservationStatus.FAILED if (level == ObservationLevel.ERROR) else ObservationStatus.COMPLETED
        if output is not None:
            obs.output = output
        if level is not None:
            obs.level = level
        if status_message is not None:
            obs.status_message = status_message
        if prompt_tokens is not None:
            obs.prompt_tokens = prompt_tokens
        if completion_tokens is not None:
            obs.completion_tokens = completion_tokens
        if total_tokens is not None:
            obs.total_tokens = total_tokens
        if input_cost is not None:
            obs.input_cost = input_cost
        if output_cost is not None:
            obs.output_cost = output_cost
        if total_cost is not None:
            obs.total_cost = total_cost
        if completion_start_time is not None:
            obs.completion_start_time = completion_start_time

        await self.db.flush()
        return obs

    async def get_observations_for_trace(self, trace_id: uuid.UUID) -> list[ExecutionObservation]:
        """Get all Observations for a Trace (flat list, sorted by time)."""
        result = await self.db.execute(
            select(ExecutionObservation)
            .where(ExecutionObservation.trace_id == trace_id)
            .order_by(ExecutionObservation.start_time.asc())
        )
        return list(result.scalars().all())

    # ==================== Batch operations ====================

    async def batch_create_trace_with_observations(
        self,
        trace: ExecutionTrace,
        observations: list[ExecutionObservation],
    ) -> ExecutionTrace:
        """Batch-create a Trace and all its Observations (single commit)."""
        self.db.add(trace)
        for obs in observations:
            self.db.add(obs)
        await self.db.flush()
        return trace

    async def aggregate_trace_tokens(self, trace_id: uuid.UUID) -> tuple[int, float]:
        """Aggregate tokens and cost across all GENERATION Observations under a Trace."""
        observations = await self.get_observations_for_trace(trace_id)
        total_tokens = 0
        total_cost = 0.0
        for obs in observations:
            if obs.type == ObservationType.GENERATION:
                total_tokens += obs.total_tokens or 0
                total_cost += obs.total_cost or 0.0
        return total_tokens, total_cost
