from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.websocket.execution_subscription_manager import ExecutionSubscriptionManager


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_text = AsyncMock()
    return ws


def test_add_and_remove_subscription():
    mgr = ExecutionSubscriptionManager()
    ws = _make_ws()

    asyncio.get_event_loop().run_until_complete(mgr.add_subscription(ws, "exec-1"))
    assert ws in mgr._exec_connections["exec-1"]
    assert "exec-1" in mgr._connection_execs[ws]

    mgr.remove_subscription(ws, "exec-1")
    assert ws not in mgr._exec_connections.get("exec-1", set())
    assert ws not in mgr._connection_execs


def test_disconnect_removes_all():
    mgr = ExecutionSubscriptionManager()
    ws = _make_ws()

    asyncio.get_event_loop().run_until_complete(mgr.add_subscription(ws, "exec-1"))
    asyncio.get_event_loop().run_until_complete(mgr.add_subscription(ws, "exec-2"))

    mgr.disconnect(ws)
    assert ws not in mgr._connection_execs
    assert ws not in mgr._exec_connections.get("exec-1", set())
    assert ws not in mgr._exec_connections.get("exec-2", set())


@pytest.mark.asyncio
async def test_broadcast_event():
    mgr = ExecutionSubscriptionManager()
    ws1 = _make_ws()
    ws2 = _make_ws()

    await mgr.add_subscription(ws1, "exec-1")
    await mgr.add_subscription(ws2, "exec-1")

    count = await mgr.broadcast_event("exec-1", {"type": "event", "seq": 1})
    assert count == 2
    assert ws1.send_text.call_count == 1
    assert ws2.send_text.call_count == 1

    sent = json.loads(ws1.send_text.call_args[0][0])
    assert sent["type"] == "event"
    assert sent["seq"] == 1


@pytest.mark.asyncio
async def test_broadcast_to_empty():
    mgr = ExecutionSubscriptionManager()
    count = await mgr.broadcast_event("nonexistent", {"type": "event"})
    assert count == 0


@pytest.mark.asyncio
async def test_broadcast_disconnects_failed():
    mgr = ExecutionSubscriptionManager()
    ws_good = _make_ws()
    ws_bad = _make_ws()
    ws_bad.send_text.side_effect = Exception("connection closed")

    await mgr.add_subscription(ws_good, "exec-1")
    await mgr.add_subscription(ws_bad, "exec-1")

    count = await mgr.broadcast_event("exec-1", {"type": "event"})
    assert count == 1
    # ws_bad should have been disconnected
    assert ws_bad not in mgr._exec_connections.get("exec-1", set())


@pytest.mark.asyncio
async def test_multiple_executions_per_connection():
    mgr = ExecutionSubscriptionManager()
    ws = _make_ws()

    await mgr.add_subscription(ws, "exec-1")
    await mgr.add_subscription(ws, "exec-2")

    assert "exec-1" in mgr._connection_execs[ws]
    assert "exec-2" in mgr._connection_execs[ws]

    mgr.remove_subscription(ws, "exec-1")
    assert "exec-1" not in mgr._connection_execs[ws]
    assert "exec-2" in mgr._connection_execs[ws]


def test_remove_nonexistent_subscription():
    mgr = ExecutionSubscriptionManager()
    ws = _make_ws()
    # Should not raise
    mgr.remove_subscription(ws, "nonexistent")


def test_disconnect_unsubscribed():
    mgr = ExecutionSubscriptionManager()
    ws = _make_ws()
    # Should not raise
    mgr.disconnect(ws)
