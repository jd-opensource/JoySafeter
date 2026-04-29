"""BroadcastProcessor — instant WebSocket relay via LiveSpanProcessor."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from loguru import logger

from app.core.observation.otel.processor_base import (
    LiveSpanProcessor,
    build_cost,
    build_usage,
    ns_to_iso,
    parse_json_attr,
)
from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationLevel, ObservationType


class BroadcastProcessor(LiveSpanProcessor):
    def __init__(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        broadcast_fn: Callable[..., Coroutine[Any, Any, None]] | None,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._execution_id = execution_id
        self._trace_id = trace_id
        self._broadcast_fn = broadcast_fn
        self._loop = event_loop
        self._otel_span_id_to_observation_id: dict[int, str] = {}

    def _resolve_parent_obs_id(self, span: Any) -> str | None:
        if span.parent:
            return self._otel_span_id_to_observation_id.get(span.parent.span_id)
        return None

    def _build_observation(self, span: Any, *, include_end: bool = False) -> dict:
        attrs = span.attributes or {}
        obs: dict = {
            "id": str(attrs.get("observation.id", "")),
            "trace_id": str(self._trace_id),
            "parent_observation_id": self._resolve_parent_obs_id(span),
            "type": attrs.get("observation.type", ObservationType.SPAN.value),
            "name": span.name,
            "level": attrs.get("observation.level", ObservationLevel.DEFAULT.value),
            "status_message": attrs.get("observation.status_message"),
            "start_time": ns_to_iso(span.start_time),
            "end_time": ns_to_iso(span.end_time) if include_end else None,
            "input": parse_json_attr(attrs.get("observation.input")),
            "output": parse_json_attr(attrs.get("observation.output")) if include_end else None,
            "metadata": parse_json_attr(attrs.get("observation.metadata")),
            "model": attrs.get("llm.model"),
            "usage_details": build_usage(attrs) if include_end else None,
            "cost_details": build_cost(attrs) if include_end else None,
        }
        return obs

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        attrs = span.attributes or {}
        obs_id = str(attrs.get("observation.id", ""))
        if obs_id and hasattr(span, "context"):
            self._otel_span_id_to_observation_id[span.context.span_id] = obs_id
        self._emit("span_open", self._build_observation(span))

    def on_end(self, span: Any) -> None:
        self._emit("span_close", self._build_observation(span, include_end=True))

        if hasattr(span, "context") and span.context:
            self._otel_span_id_to_observation_id.pop(span.context.span_id, None)

    def on_event(
        self, span: ObservationSpan, event_name: str, attributes: dict
    ) -> None:
        parent_obs_id: str | None = None
        parent_span_id = span.get_parent_span_id()
        if parent_span_id is not None:
            parent_obs_id = self._otel_span_id_to_observation_id.get(parent_span_id)
        self._emit(event_name, {
            "id": str(span.observation_id),
            "trace_id": str(self._trace_id),
            "parent_observation_id": parent_obs_id,
        }, data=dict(attributes))

    def emit_trace_complete(self, status: str, trace_id: str, aggregates: dict) -> None:
        self._emit(
            "trace_complete",
            observation=None,
            data={"status": status, "trace_id": trace_id, **aggregates},
        )

    def _emit(
        self,
        event: str,
        observation: dict | None,
        data: dict | None = None,
    ) -> None:
        if not self._broadcast_fn:
            return
        message = {
            "type": "observation",
            "execution_id": str(self._execution_id),
            "event": event,
            "observation": observation,
            "data": data or {},
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._broadcast_fn(self._execution_id, message), self._loop
            )
            future.add_done_callback(self._log_if_failed)
        except Exception:
            logger.opt(exception=True).debug("broadcast schedule failed")

    @staticmethod
    def _log_if_failed(future: Any) -> None:
        exc = future.exception()
        if exc:
            logger.warning("broadcast failed: %s", exc)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
