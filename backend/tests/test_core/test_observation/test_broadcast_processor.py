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
async def test_emit_sends_envelope_with_seq():
    captured: list[dict] = []
    exec_id = uuid.uuid4()

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(exec_id, fake_broadcast, loop)
    proc._emit("span_open", {
        "observation_id": "obs-1",
        "parent_observation_id": None,
        "data": {"name": "test"},
    })
    # Let the scheduled coroutine run
    await asyncio.sleep(0.05)
    assert len(captured) == 1
    msg = captured[0]
    assert msg["channel"] == "observation"
    assert msg["trace_id"] == str(exec_id)
    assert msg["seq"] == 1
    assert msg["event"] == "span_open"
    assert msg["observation_id"] == "obs-1"


@pytest.mark.asyncio
async def test_seq_increments_monotonically():
    captured: list[dict] = []

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), fake_broadcast, loop)
    proc._emit("a", {"observation_id": "1", "data": {}})
    proc._emit("b", {"observation_id": "2", "data": {}})
    proc._emit("c", {"observation_id": "3", "data": {}})
    await asyncio.sleep(0.05)
    seqs = [m["seq"] for m in captured]
    assert seqs == [1, 2, 3]


@pytest.mark.asyncio
async def test_no_broadcast_fn_is_noop():
    """When broadcast_fn is None, _emit must not crash."""
    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), None, loop)
    proc._emit("span_open", {"observation_id": "1", "data": {}})
    # Should not raise


@pytest.mark.asyncio
async def test_on_event_routes_through_emit():
    captured: list[dict] = []

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), fake_broadcast, loop)
    span = MagicMock()
    span.observation_id = uuid.uuid4()
    span._span = MagicMock()
    span._span.parent = None
    proc.on_event(span, "llm_token", {"token": "Hi", "index": 0})
    await asyncio.sleep(0.05)
    assert len(captured) == 1
    assert captured[0]["event"] == "llm_token"
    assert captured[0]["data"]["token"] == "Hi"
