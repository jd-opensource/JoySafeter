"""ObservationTracerProvider — per-execution facade over the global OTel TracerProvider."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine

from opentelemetry import trace
from opentelemetry.trace import Tracer

from app.joysafeter_shared.observation.otel.broadcast_processor import BroadcastProcessor
from app.joysafeter_shared.observation.otel.global_provider import get_global_provider
from app.joysafeter_shared.observation.otel.persistence_processor import PersistenceProcessor
from app.joysafeter_shared.observation.otel.span_wrapper import ObservationSpan

_persistence: PersistenceProcessor | None = None
_broadcast: BroadcastProcessor | None = None


def init_global_processors() -> tuple[PersistenceProcessor, BroadcastProcessor]:
    """Create and attach global processors to the global TracerProvider.

    Called once during app startup, after ``init_global_provider()``.
    Idempotent — returns the existing instances on repeated calls.
    """
    global _persistence, _broadcast
    if _persistence is not None and _broadcast is not None:
        return _persistence, _broadcast

    provider = get_global_provider()

    _persistence = PersistenceProcessor()
    _broadcast = BroadcastProcessor()
    provider.add_span_processor(_persistence)
    provider.add_span_processor(_broadcast)

    return _persistence, _broadcast


def get_persistence_processor() -> PersistenceProcessor:
    if _persistence is None:
        raise RuntimeError("call init_global_processors() during app startup")
    return _persistence


def get_broadcast_processor() -> BroadcastProcessor:
    if _broadcast is None:
        raise RuntimeError("call init_global_processors() during app startup")
    return _broadcast


class ObservationTracerProvider:
    """Per-execution facade — registers with global processors, dispatches live events."""

    def __init__(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        project_id: str,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        broadcast_fn: Callable[..., Coroutine[Any, Any, None]] | None,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._execution_id = execution_id
        self._execution_id_str = str(execution_id)
        self._trace_id = trace_id

        self._persistence = get_persistence_processor()
        self._broadcast = get_broadcast_processor()

        self._persistence.register_execution(
            execution_id,
            trace_id,
            project_id,
            db_session_factory,
            event_loop,
        )
        self._broadcast.register_execution(
            execution_id,
            trace_id,
            broadcast_fn,
            event_loop,
        )

        self._tracer = trace.get_tracer("joysafeter.observation")

    def get_tracer(self) -> Tracer:
        return self._tracer

    def dispatch_live_event(self, span: ObservationSpan, event_name: str, attributes: dict) -> None:
        attributes["execution.id"] = self._execution_id_str
        self._broadcast.on_event(span, event_name, attributes)

    def get_persistence_aggregates(self) -> dict:
        return self._persistence.get_execution_aggregates(self._execution_id)

    def broadcast_trace_complete(self, status: str, aggregates: dict) -> None:
        self._broadcast.emit_trace_complete(
            self._execution_id,
            status,
            str(self._trace_id),
            aggregates,
        )

    async def shutdown(self) -> None:
        await self._persistence.async_shutdown_execution(self._execution_id)
        self._broadcast.unregister_execution(self._execution_id)
