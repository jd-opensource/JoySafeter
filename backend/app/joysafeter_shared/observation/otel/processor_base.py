"""Base SpanProcessor extension and shared utilities for observation processors."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

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


def resolve_execution_id(span: Any) -> str | None:
    """Extract ``execution.id`` string from a span's attributes, or *None*."""
    attrs = getattr(span, "attributes", None) or {}
    val = attrs.get("execution.id")
    return str(val) if val else None


B = TypeVar("B")


class BucketRegistry(Generic[B]):
    """Thread-safe str-keyed bucket registry used by both processors."""

    def __init__(self) -> None:
        self._buckets: dict[str, B] = {}
        self._lock = threading.Lock()

    def put(self, execution_id: uuid.UUID, bucket: B) -> None:
        with self._lock:
            self._buckets[str(execution_id)] = bucket

    def pop(self, execution_id: uuid.UUID) -> B | None:
        with self._lock:
            return self._buckets.pop(str(execution_id), None)

    def get_by_id(self, execution_id: uuid.UUID) -> B | None:
        with self._lock:
            return self._buckets.get(str(execution_id))

    def get_by_span(self, span: Any) -> B | None:
        exec_id = resolve_execution_id(span)
        if exec_id is None:
            return None
        with self._lock:
            return self._buckets.get(exec_id)

    def get_by_str(self, exec_id_str: str) -> B | None:
        with self._lock:
            return self._buckets.get(exec_id_str)

    def pop_stale(self, max_age_seconds: float) -> list[tuple[str, B]]:
        """Remove and return buckets older than *max_age_seconds*.

        Requires buckets to have a ``created_at: float`` attribute
        (monotonic timestamp).
        """
        now = time.monotonic()
        stale: list[tuple[str, B]] = []
        with self._lock:
            for eid, bucket in list(self._buckets.items()):
                created = getattr(bucket, "created_at", None)
                if created is not None and now - created > max_age_seconds:
                    stale.append((eid, bucket))
                    self._buckets.pop(eid)
        return stale

    def clear(self) -> list[B]:
        with self._lock:
            buckets = list(self._buckets.values())
            self._buckets.clear()
        return buckets


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
