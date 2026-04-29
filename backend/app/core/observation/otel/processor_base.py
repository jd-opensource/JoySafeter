"""Base SpanProcessor extension that adds an on_event hook for live streaming."""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from opentelemetry.sdk.trace import SpanProcessor


class LiveSpanProcessor(SpanProcessor):
    """SpanProcessor variant that also receives live (mid-span) events.

    OTel's stock SpanProcessor only fires on_start/on_end. LiveSpanProcessor
    adds on_event so streaming token / intermediate-update events can be
    pushed out the moment they happen — bypassing on_end batching.
    """

    def on_event(self, span: Any, event_name: str, attributes: dict) -> None:
        """Called by ObservationSpan when a live event is emitted. Default: no-op."""
        return None


def parse_json_attr(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def ns_to_datetime(ns: int | None) -> datetime | None:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def ns_to_iso(ns: int | None) -> str | None:
    dt = ns_to_datetime(ns)
    return dt.isoformat() if dt else None


def build_usage(attrs: Mapping[str, Any]) -> dict | None:
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


def build_cost(attrs: Mapping[str, Any]) -> dict | None:
    inp = attrs.get("llm.cost.input")
    out = attrs.get("llm.cost.output")
    total = attrs.get("llm.cost.total")
    if inp is None and out is None and total is None:
        return None
    return {
        "input": float(inp) if inp is not None else 0.0,
        "output": float(out) if out is not None else 0.0,
        "total": float(total) if total is not None else 0.0,
    }
