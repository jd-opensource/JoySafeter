# backend/tests/test_core/test_observation/test_broadcaster.py
from __future__ import annotations

import uuid

import pytest
from unittest.mock import AsyncMock

from app.core.observation.broadcaster import ObservationBroadcaster


@pytest.fixture
def broadcaster():
    ws = AsyncMock()
    execution_id = uuid.uuid4()
    return ObservationBroadcaster(execution_id, broadcast_fn=ws), ws, execution_id


@pytest.mark.asyncio
async def test_emit_sends_observation_channel(broadcaster) -> None:
    bc, ws, exec_id = broadcaster
    await bc.emit("span_open", {"id": "obs-1", "type": "GENERATION"})

    ws.assert_called_once()
    msg = ws.call_args[0][1]
    assert msg["channel"] == "observation"
    assert msg["trace_id"] == str(exec_id)
    assert msg["event"] == "span_open"
    assert msg["observation"]["id"] == "obs-1"


@pytest.mark.asyncio
async def test_seq_monotonically_increases(broadcaster) -> None:
    bc, ws, _ = broadcaster
    await bc.emit("span_open", {"id": "a"})
    await bc.emit("span_close", {"id": "a"})
    await bc.emit("record", {"id": "b"})

    seqs = [call[0][1]["seq"] for call in ws.call_args_list]
    assert seqs == [1, 2, 3]


@pytest.mark.asyncio
async def test_trace_complete_event(broadcaster) -> None:
    bc, ws, _ = broadcaster
    await bc.emit("trace_complete", {"total_tokens": 1540, "total_cost": 0.016})

    msg = ws.call_args[0][1]
    assert msg["event"] == "trace_complete"
