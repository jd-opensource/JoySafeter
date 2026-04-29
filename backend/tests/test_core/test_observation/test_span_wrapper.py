"""ObservationSpan: typed wrapper providing observation-schema attribute setters."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationLevel, ObservationType


def _make_span_and_provider():
    span = MagicMock()
    span.set_attribute = MagicMock()
    span.add_event = MagicMock()
    span.end = MagicMock()
    provider = MagicMock()
    obs_id = uuid.uuid4()
    return ObservationSpan(span, obs_id, provider), span, provider, obs_id


def test_set_input_serializes_to_json_attribute():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_input({"messages": [{"role": "user"}]})
    span.set_attribute.assert_any_call(
        "observation.input", json.dumps({"messages": [{"role": "user"}]})
    )


def test_set_output():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_output({"result": "ok"})
    span.set_attribute.assert_any_call(
        "observation.output", json.dumps({"result": "ok"})
    )


def test_set_model():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_model("gpt-4o")
    span.set_attribute.assert_any_call("llm.model", "gpt-4o")


def test_set_usage():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_usage({"input": 10, "output": 5, "total": 15})
    span.set_attribute.assert_any_call("llm.usage.input", 10)
    span.set_attribute.assert_any_call("llm.usage.output", 5)
    span.set_attribute.assert_any_call("llm.usage.total", 15)


def test_set_observation_type():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_observation_type(ObservationType.GENERATION)
    span.set_attribute.assert_any_call("observation.type", "GENERATION")


def test_set_level():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_level(ObservationLevel.ERROR)
    span.set_attribute.assert_any_call("observation.level", "ERROR")


def test_add_llm_token_fires_span_event_and_live_dispatch():
    obs, span, provider, _ = _make_span_and_provider()
    obs.add_llm_token("Hello", 0)
    span.add_event.assert_called_once_with(
        "stream.llm_token", {"token": "Hello", "index": 0}
    )
    provider.dispatch_live_event.assert_called_once_with(
        obs, "llm_token", {"token": "Hello", "index": 0}
    )


def test_add_intermediate_update_serializes_payload():
    obs, span, provider, _ = _make_span_and_provider()
    obs.add_intermediate_update({"type": "AGENT"})
    call_args = span.add_event.call_args
    assert call_args[0][0] == "stream.intermediate_update"
    payload = json.loads(call_args[0][1]["payload_json"])
    assert payload == {"type": "AGENT"}


def test_record_error_sets_attributes():
    obs, span, _, _ = _make_span_and_provider()
    exc = ValueError("test error")
    obs.record_error(exc, ObservationLevel.ERROR)
    span.set_attribute.assert_any_call("observation.level", "ERROR")
    span.set_attribute.assert_any_call("observation.status_message", "test error")


def test_end_calls_span_end():
    obs, span, _, _ = _make_span_and_provider()
    obs.end()
    span.end.assert_called_once()


def test_set_completion_start_time():
    obs, span, _, _ = _make_span_and_provider()
    ts = datetime(2026, 4, 29, 10, 0, 0, tzinfo=timezone.utc)
    obs.set_completion_start_time(ts)
    span.set_attribute.assert_any_call(
        "llm.completion_start_time", "2026-04-29T10:00:00+00:00"
    )


def test_set_prompt():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_prompt("my-prompt", "3")
    span.set_attribute.assert_any_call("llm.prompt.name", "my-prompt")
    span.set_attribute.assert_any_call("llm.prompt.version", "3")
