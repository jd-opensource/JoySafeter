"""BroadcastProcessor — instant WebSocket relay via LiveSpanProcessor."""
from __future__ import annotations

import asyncio
import itertools
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
        broadcast_fn: Callable[..., Coroutine[Any, Any, None]] | None,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._execution_id = execution_id
        self._broadcast_fn = broadcast_fn
        self._loop = event_loop
        self._seq = itertools.count(1)
        self._otel_span_id_to_observation_id: dict[int, str] = {}

    def _resolve_parent_obs_id(self, span: Any) -> str | None:
        if span.parent:
            return self._otel_span_id_to_observation_id.get(span.parent.span_id)
        return None

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        attrs = span.attributes or {}
        obs_id = str(attrs.get("observation.id", ""))
        if obs_id and hasattr(span, "context"):
            self._otel_span_id_to_observation_id[span.context.span_id] = obs_id
        self._emit("span_open", {
            "observation_id": obs_id,
            "parent_observation_id": self._resolve_parent_obs_id(span),
            "data": {
                "name": span.name,
                "type": attrs.get("observation.type", ObservationType.SPAN.value),
                "level": attrs.get("observation.level", ObservationLevel.DEFAULT.value),
                "input": parse_json_attr(attrs.get("observation.input")),
                "metadata": parse_json_attr(attrs.get("observation.metadata")),
                "model": attrs.get("llm.model"),
                "start_time": ns_to_iso(span.start_time),
            },
        })

    def on_end(self, span: Any) -> None:
        attrs = span.attributes or {}
        self._emit("span_close", {
            "observation_id": str(attrs.get("observation.id", "")),
            "parent_observation_id": self._resolve_parent_obs_id(span),
            "data": {
                "output": parse_json_attr(attrs.get("observation.output")),
                "level": attrs.get("observation.level", ObservationLevel.DEFAULT.value),
                "end_time": ns_to_iso(span.end_time),
                "usage": build_usage(attrs),
                "cost": build_cost(attrs),
                "status_message": attrs.get("observation.status_message"),
            },
        })

        if hasattr(span, "context") and span.context:
            self._otel_span_id_to_observation_id.pop(span.context.span_id, None)

    def on_event(
        self, span: ObservationSpan, event_name: str, attributes: dict
    ) -> None:
        parent_obs_id: str | None = None
        raw_span = getattr(span, "_span", None)
        parent = getattr(raw_span, "parent", None)
        if parent is not None:
            parent_obs_id = self._otel_span_id_to_observation_id.get(
                parent.span_id
            )
        self._emit(event_name, {
            "observation_id": str(span.observation_id),
            "parent_observation_id": parent_obs_id,
            "data": dict(attributes),
        })

    def _emit(self, event: str, payload: dict) -> None:
        if not self._broadcast_fn:
            return
        seq = next(self._seq)
        message = {
            "channel": "observation",
            "trace_id": str(self._execution_id),
            "seq": seq,
            "event": event,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            **payload,
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
