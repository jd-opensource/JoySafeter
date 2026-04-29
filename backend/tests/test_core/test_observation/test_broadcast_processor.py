"""BroadcastProcessor: fire-and-forget WS relay via LiveSpanProcessor."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock

import pytest

from app.core.observation.otel.broadcast_processor import BroadcastProcessor
from app.core.observation.otel.processor_base import LiveSpanProcessor


def test_broadcast_processor_is_live_span_processor():
    assert issubclass(BroadcastProcessor, LiveSpanProcessor)


@pytest.mark.asyncio
async def test_span_open_envelope_shape():
    captured: list[dict] = []
    exec_id = uuid.uuid4()
    trace_id = uuid.uuid4()

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(exec_id, trace_id, fake_broadcast, loop)

    span = MagicMock()
    span.attributes = {
        "observation.id": "obs-1",
        "observation.type": "GENERATION",
        "observation.level": "DEFAULT",
    }
    span.name = "test-span"
    span.start_time = 1_700_000_000_000_000_000
    span.parent = None
    span.context = MagicMock()
    span.context.span_id = 12345

    proc.on_start(span)
    await asyncio.sleep(0.05)

    assert len(captured) == 1
    msg = captured[0]
    assert msg["type"] == "observation"
    assert msg["execution_id"] == str(exec_id)
    assert msg["event"] == "span_open"
    assert "timestamp" in msg

    obs = msg["observation"]
    assert obs["id"] == "obs-1"
    assert obs["trace_id"] == str(trace_id)
    assert obs["parent_observation_id"] is None
    assert obs["type"] == "GENERATION"
    assert obs["name"] == "test-span"
    assert obs["level"] == "DEFAULT"
    assert obs["start_time"] is not None
    assert obs["end_time"] is None
    assert obs["output"] is None
    assert obs["usage_details"] is None
    assert obs["cost_details"] is None


@pytest.mark.asyncio
async def test_span_close_includes_usage_and_cost():
    captured: list[dict] = []

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), uuid.uuid4(), fake_broadcast, loop)

    span = MagicMock()
    span.attributes = {
        "observation.id": "obs-2",
        "observation.type": "GENERATION",
        "observation.level": "DEFAULT",
        "observation.output": '{"text": "hello"}',
        "llm.model": "gpt-4o",
        "llm.usage.input": 10,
        "llm.usage.output": 5,
        "llm.usage.total": 15,
        "llm.cost.input": 0.01,
        "llm.cost.output": 0.02,
        "llm.cost.total": 0.03,
    }
    span.name = "gen"
    span.start_time = 1_700_000_000_000_000_000
    span.end_time = 1_700_000_001_000_000_000
    span.parent = None
    span.context = MagicMock()
    span.context.span_id = 999

    proc.on_end(span)
    await asyncio.sleep(0.05)

    obs = captured[0]["observation"]
    assert obs["model"] == "gpt-4o"
    assert obs["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert obs["cost_details"] == {"input": 0.01, "output": 0.02, "total": 0.03}
    assert obs["end_time"] is not None
    assert obs["output"] == {"text": "hello"}


@pytest.mark.asyncio
async def test_span_update_has_observation_and_data():
    captured: list[dict] = []

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    trace_id = uuid.uuid4()
    proc = BroadcastProcessor(uuid.uuid4(), trace_id, fake_broadcast, loop)

    span = MagicMock()
    span.observation_id = uuid.uuid4()
    span.get_parent_span_id.return_value = None
    proc.on_event(span, "span_update", {"type": "AGENT", "action_log": "thinking"})
    await asyncio.sleep(0.05)

    assert len(captured) == 1
    msg = captured[0]
    assert msg["event"] == "span_update"
    assert msg["observation"]["id"] == str(span.observation_id)
    assert msg["observation"]["trace_id"] == str(trace_id)
    assert msg["data"]["type"] == "AGENT"
    assert msg["data"]["action_log"] == "thinking"


@pytest.mark.asyncio
async def test_trace_complete_observation_is_null():
    captured: list[dict] = []

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    trace_id = uuid.uuid4()
    proc = BroadcastProcessor(uuid.uuid4(), trace_id, fake_broadcast, loop)
    proc._emit("trace_complete", observation=None, data={
        "status": "complete", "trace_id": str(trace_id),
    })
    await asyncio.sleep(0.05)

    msg = captured[0]
    assert msg["event"] == "trace_complete"
    assert msg["observation"] is None
    assert msg["data"]["status"] == "complete"
    assert msg["data"]["trace_id"] == str(trace_id)


@pytest.mark.asyncio
async def test_parent_resolution():
    captured: list[dict] = []

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), uuid.uuid4(), fake_broadcast, loop)

    parent_span = MagicMock()
    parent_span.attributes = {"observation.id": "parent-obs"}
    parent_span.name = "parent"
    parent_span.start_time = 1_700_000_000_000_000_000
    parent_span.parent = None
    parent_span.context = MagicMock()
    parent_span.context.span_id = 100

    proc.on_start(parent_span)

    child_span = MagicMock()
    child_span.attributes = {"observation.id": "child-obs"}
    child_span.name = "child"
    child_span.start_time = 1_700_000_000_500_000_000
    child_span.parent = MagicMock()
    child_span.parent.span_id = 100
    child_span.context = MagicMock()
    child_span.context.span_id = 200

    proc.on_start(child_span)
    await asyncio.sleep(0.05)

    child_msg = captured[1]
    assert child_msg["observation"]["parent_observation_id"] == "parent-obs"


@pytest.mark.asyncio
async def test_no_broadcast_fn_is_noop():
    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), uuid.uuid4(), None, loop)
    proc._emit("span_open", {"id": "1"})
