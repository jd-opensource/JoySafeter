"""Contract: LiveSpanProcessor extends OTel SpanProcessor with on_event hook."""
from opentelemetry.sdk.trace import SpanProcessor

from app.core.observation.otel.processor_base import LiveSpanProcessor


def test_live_span_processor_is_span_processor():
    assert issubclass(LiveSpanProcessor, SpanProcessor)


def test_on_event_default_is_noop():
    class P(LiveSpanProcessor):
        pass
    p = P()
    # default on_event must not raise even when not overridden
    p.on_event(span=None, event_name="x", attributes={})
