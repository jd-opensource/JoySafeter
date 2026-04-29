"""ObservationSpan — typed wrapper over an OTel Span with observation-schema setters."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import Span

from app.core.observation.types import ObservationLevel, ObservationType

if TYPE_CHECKING:
    from app.core.observation.otel.provider import ObservationTracerProvider


def _safe_json(value: Any) -> str:
    return json.dumps(value, default=str)


class ObservationSpan:
    __slots__ = ("_span", "observation_id", "_provider")

    def __init__(
        self,
        otel_span: Span,
        observation_id: uuid.UUID,
        provider: "ObservationTracerProvider",
    ) -> None:
        self._span = otel_span
        self.observation_id = observation_id
        self._provider = provider

    # --- typed attribute setters ---

    def set_input(self, value: Any) -> None:
        self._span.set_attribute("observation.input", _safe_json(value))

    def set_output(self, value: Any) -> None:
        self._span.set_attribute("observation.output", _safe_json(value))

    def set_metadata(self, value: dict) -> None:
        self._span.set_attribute("observation.metadata", _safe_json(value))

    def set_model(self, name: str) -> None:
        self._span.set_attribute("llm.model", name)

    def set_model_parameters(self, params: dict) -> None:
        self._span.set_attribute("llm.parameters", _safe_json(params))

    def set_usage(self, usage: dict) -> None:
        for key in ("input", "output", "total"):
            if key in usage:
                self._span.set_attribute(f"llm.usage.{key}", usage[key])

    def set_cost(self, cost: dict) -> None:
        for key in ("input", "output", "total"):
            if key in cost:
                self._span.set_attribute(f"llm.cost.{key}", cost[key])

    def set_level(self, level: ObservationLevel) -> None:
        self._span.set_attribute("observation.level", level.value)

    def set_status_message(self, msg: str) -> None:
        self._span.set_attribute("observation.status_message", msg)

    def set_observation_type(self, t: ObservationType) -> None:
        self._span.set_attribute("observation.type", t.value)

    def set_prompt(self, name: str, version: str | None) -> None:
        self._span.set_attribute("llm.prompt.name", name)
        if version is not None:
            self._span.set_attribute("llm.prompt.version", version)

    def set_tool_calls(self, calls: list) -> None:
        self._span.set_attribute("tool.calls", _safe_json(calls))

    def set_tool_definitions(self, defs: list) -> None:
        self._span.set_attribute("tool.definitions", _safe_json(defs))

    def set_completion_start_time(self, ts: datetime) -> None:
        self._span.set_attribute("llm.completion_start_time", ts.isoformat())

    # --- streaming events ---

    def add_llm_token(self, token: str, index: int) -> None:
        attrs = {"token": token, "index": index}
        self._span.add_event("stream.llm_token", attrs)
        self._provider.dispatch_live_event(self, "llm_token", attrs)

    def add_intermediate_update(self, payload: dict) -> None:
        self._span.add_event("stream.intermediate_update", {
            "payload_json": json.dumps(payload, default=str),
        })
        self._provider.dispatch_live_event(self, "span_update", payload)

    def add_event(self, name: str, attributes: dict[str, str] | None = None) -> None:
        self._span.add_event(name, attributes or {})

    # --- lifecycle ---

    def record_error(self, exc: Exception, level: ObservationLevel) -> None:
        self._span.set_attribute("observation.level", level.value)
        self._span.set_attribute("observation.status_message", str(exc))

    def get_context(self) -> Any:
        """Return an OTel Context with this span set as current."""
        from opentelemetry import trace as _trace
        return _trace.set_span_in_context(self._span)

    def end(self) -> None:
        self._span.end()
