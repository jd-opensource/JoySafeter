"""Base SpanProcessor extension that adds an on_event hook for live streaming."""
from __future__ import annotations

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
