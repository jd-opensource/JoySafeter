"""BroadcastProcessor — instant WebSocket relay via LiveSpanProcessor."""
from __future__ import annotations

import asyncio
import itertools
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from loguru import logger

from app.core.observation.otel.processor_base import LiveSpanProcessor
from app.core.observation.otel.span_wrapper import ObservationSpan


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

    @staticmethod
    def _ns_to_iso(ns: int | None) -> str | None:
        if ns is None:
            return None
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat()

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
                "type": attrs.get("observation.type", "SPAN"),
                "level": attrs.get("observation.level", "DEFAULT"),
                "input": self._parse_json(attrs.get("observation.input")),
                "metadata": self._parse_json(attrs.get("observation.metadata")),
                "model": attrs.get("llm.model"),
                "start_time": self._ns_to_iso(span.start_time),
            },
        })

    def on_end(self, span: Any) -> None:
        attrs = span.attributes or {}
        self._emit("span_close", {
            "observation_id": str(attrs.get("observation.id", "")),
            "parent_observation_id": self._resolve_parent_obs_id(span),
            "data": {
                "output": self._parse_json(attrs.get("observation.output")),
                "level": attrs.get("observation.level", "DEFAULT"),
                "end_time": self._ns_to_iso(span.end_time),
                "usage": self._build_usage(attrs),
                "cost": self._build_cost(attrs),
                "status_message": attrs.get("observation.status_message"),
            },
        })

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
            pass  # WS disconnect / loop closed — never crash the pipeline

    @staticmethod
    def _log_if_failed(future: Any) -> None:
        exc = future.exception()
        if exc:
            logger.warning("broadcast failed: %s", exc)

    @staticmethod
    def _parse_json(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, ValueError):
                return val
        return val

    @staticmethod
    def _build_usage(attrs: dict) -> dict | None:
        inp = attrs.get("llm.usage.input")
        out = attrs.get("llm.usage.output")
        total = attrs.get("llm.usage.total")
        if inp is None and out is None and total is None:
            return None
        return {
            "input": int(inp) if inp is not None else 0,
            "output": int(out) if out is not None else 0,
            "total": int(total) if total is not None else 0,
        }

    @staticmethod
    def _build_cost(attrs: dict) -> dict | None:
        total = attrs.get("llm.cost.total")
        if total is None:
            return None
        return {"total": float(total)}

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
