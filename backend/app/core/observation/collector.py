"""ObservationCollector — OTel-backed central API for observation tracing."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine

import sqlalchemy as sa
from loguru import logger
from opentelemetry import context as otel_context
from opentelemetry import trace

from app.core.observation.instrumentation.langchain_handler import (
    ObservationCallbackHandler,
)
from app.core.observation.model import Trace
from app.core.observation.otel.provider import ObservationTracerProvider
from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationLevel, ObservationType
from app.utils.datetime import utc_now


class ObservationCollector:
    def __init__(
        self,
        trace_id: uuid.UUID,
        execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        broadcast_fn: Callable[..., Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        self._provider = ObservationTracerProvider(
            execution_id=execution_id,
            trace_id=trace_id,
            workspace_id=workspace_id,
            db_session_factory=db_session_factory,
            broadcast_fn=broadcast_fn,
            event_loop=loop,
        )
        self._tracer = self._provider.get_tracer()
        self._trace_id = trace_id
        self._execution_id = execution_id
        self._db_session_factory = db_session_factory

        # Attach a lightweight context span so get_current_span() returns a
        # valid span throughout the execution lifetime.  This makes loguru's
        # _get_otel_trace_id() and propagate.inject() work inside engine tasks.
        self._ctx_span = trace.get_tracer("joysafeter.execution").start_span(
            "execution",
        )
        self._ctx_token = otel_context.attach(
            trace.set_span_in_context(self._ctx_span)
        )

    def start_span(
        self,
        obs_type: ObservationType,
        name: str,
        *,
        parent: ObservationSpan | None = None,
        input: Any = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> ObservationSpan:
        obs_id = uuid.uuid4()

        parent_ctx = None
        if parent:
            parent_ctx = parent.get_context()

        otel_span = self._tracer.start_span(
            name,
            context=parent_ctx,
            attributes={
                "execution.id": str(self._execution_id),
                "observation.id": str(obs_id),
                "observation.type": obs_type.value,
                "observation.level": level.value,
            },
        )

        obs = ObservationSpan(otel_span, obs_id, self._provider)

        if input is not None:
            obs.set_input(input)
        if metadata:
            obs.set_metadata(metadata)

        return obs

    def start_agent(self, name: str, **kw: Any) -> ObservationSpan:
        return self.start_span(ObservationType.AGENT, name, **kw)

    def child_span(
        self,
        parent: ObservationSpan,
        obs_type: ObservationType,
        name: str,
        *,
        input: Any = None,
        **kw: Any,
    ) -> ObservationSpan:
        return self.start_span(obs_type, name, parent=parent, input=input, **kw)

    def record_generation(
        self,
        name: str,
        *,
        parent: ObservationSpan | None = None,
        input: Any = None,
        output: Any = None,
        model: str | None = None,
        usage_details: dict | None = None,
        cost_details: dict | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> ObservationSpan:
        span = self.start_span(
            ObservationType.GENERATION,
            name,
            parent=parent,
            input=input,
            metadata=metadata,
            level=level,
        )
        if output is not None:
            span.set_output(output)
        if model:
            span.set_model(model)
        if usage_details:
            span.set_usage(usage_details)
        if cost_details:
            span.set_cost(cost_details)
        span.end()
        return span

    def record_tool(
        self,
        name: str,
        *,
        parent: ObservationSpan | None = None,
        input: Any = None,
        output: Any = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> ObservationSpan:
        span = self.start_span(
            ObservationType.TOOL,
            name,
            parent=parent,
            input=input,
            metadata=metadata,
            level=level,
        )
        if output is not None:
            span.set_output(output)
        span.end()
        return span

    def record_event(
        self,
        name: str,
        *,
        parent: ObservationSpan | None = None,
        input: Any = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> ObservationSpan:
        span = self.start_span(
            ObservationType.EVENT,
            name,
            parent=parent,
            input=input,
            metadata=metadata,
            level=level,
        )
        span.end()
        return span

    def create_langchain_handler(self) -> ObservationCallbackHandler:
        return ObservationCallbackHandler(self._tracer, self._provider, self._execution_id)

    async def finalize(self, status: str = "complete") -> None:
        agg = self._provider.get_persistence_aggregates()
        final_status = "error" if agg["has_error"] else status
        self._provider.broadcast_trace_complete(final_status, agg)
        await self._provider.shutdown()
        self._ctx_span.end()
        otel_context.detach(self._ctx_token)
        await self._update_trace_row(final_status, agg)

    async def _update_trace_row(self, status: str, agg: dict) -> None:
        try:
            session = await self._db_session_factory()
            now = utc_now()
            await session.execute(
                sa.update(Trace)
                .where(Trace.id == self._trace_id)
                .values(
                    status=status,
                    end_time=now,
                    total_observations=agg["total_observations"],
                    total_tokens=agg["total_tokens"],
                    total_cost=agg["total_cost"],
                )
            )
            await session.commit()
        except Exception:
            logger.opt(exception=True).warning("Failed to update Trace row")
