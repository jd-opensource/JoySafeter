"""ObservationTracerProvider — per-execution OTel TracerProvider lifecycle."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Tracer

from app.core.observation.otel.broadcast_processor import BroadcastProcessor
from app.core.observation.otel.persistence_processor import PersistenceProcessor
from app.core.observation.otel.processor_base import LiveSpanProcessor
from app.core.observation.otel.span_wrapper import ObservationSpan


class ObservationTracerProvider:
    def __init__(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        workspace_id: uuid.UUID,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        broadcast_fn: Callable[..., Coroutine[Any, Any, None]] | None,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "joysafeter",
                    "execution.id": str(execution_id),
                    "trace.id": str(trace_id),
                    "workspace.id": str(workspace_id),
                }
            )
        )
        self._persistence = PersistenceProcessor(execution_id, trace_id, workspace_id, db_session_factory, event_loop)
        self._trace_id = trace_id
        self._broadcast = BroadcastProcessor(execution_id, trace_id, broadcast_fn, event_loop)
        self._provider.add_span_processor(self._persistence)
        self._provider.add_span_processor(self._broadcast)
        self._tracer = self._provider.get_tracer("joysafeter.observation")
        self._live_processors: list[LiveSpanProcessor] = [self._broadcast]

    def get_tracer(self) -> Tracer:
        return self._tracer

    def dispatch_live_event(self, span: ObservationSpan, event_name: str, attributes: dict) -> None:
        for proc in self._live_processors:
            proc.on_event(span, event_name, attributes)

    def get_persistence_aggregates(self) -> dict:
        return self._persistence.get_aggregates()

    def broadcast_trace_complete(self, status: str, aggregates: dict) -> None:
        self._broadcast.emit_trace_complete(status, str(self._trace_id), aggregates)

    async def shutdown(self) -> None:
        await self._persistence.async_shutdown()
        self._broadcast.shutdown()
