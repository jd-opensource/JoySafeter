from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch

import pytest

from app.core.events.envelope import ExecutionEventEnvelope
from app.core.events.event_types import ExecutionEventType
from app.core.events.subscribers.websocket import WebSocketSubscriber
from app.websocket.execution_subscription_handler import ExecutionSubscriptionHandler
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


@pytest.mark.asyncio
async def test_handler_subscribe_sends_snapshot_with_status_and_events_contract():
    execution_id = uuid.uuid4()
    ws = _make_ws()

    class Snapshot:
        last_seq = 3
        projection = {"status": "running", "started_at": "2026-04-24T12:00:00+00:00"}

    service = AsyncMock()
    service.get_execution.return_value = object()
    service.get_snapshot.return_value = Snapshot()
    service.list_events_after.return_value = []

    @asynccontextmanager
    async def fake_session_ctx():
        yield object()

    handler = ExecutionSubscriptionHandler()
    with patch("app.websocket.execution_subscription_handler.AsyncSessionLocal", fake_session_ctx), patch(
        "app.websocket.execution_subscription_handler.ExecutionService",
        return_value=service,
    ):
        await handler._handle_frame(
            ws,
            "user-123",
            json.dumps({"type": "subscribe", "execution_id": str(execution_id), "after_seq": 0}),
        )

    snapshot_frame = json.loads(ws.send_text.await_args_list[0].args[0])
    assert snapshot_frame == {
        "type": "snapshot",
        "execution_id": str(execution_id),
        "last_seq": 3,
        "status": "running",
        "events": [],
    }


@pytest.mark.asyncio
async def test_handler_subscribe_replays_events_with_payload_field_and_sequence_no():
    execution_id = uuid.uuid4()
    ws = _make_ws()

    class Snapshot:
        last_seq = 0
        projection = {"status": "running"}

    event = MagicMock()
    event.sequence_no = 4
    event.event_type = "assistant_text"
    event.payload = {"content": "hello"}
    event.created_at = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)

    service = AsyncMock()
    service.get_execution.return_value = object()
    service.get_snapshot.return_value = Snapshot()
    service.list_events_after.return_value = [event]

    @asynccontextmanager
    async def fake_session_ctx():
        yield object()

    handler = ExecutionSubscriptionHandler()
    with patch("app.websocket.execution_subscription_handler.AsyncSessionLocal", fake_session_ctx), patch(
        "app.websocket.execution_subscription_handler.ExecutionService",
        return_value=service,
    ):
        await handler._handle_frame(
            ws,
            "user-123",
            json.dumps({"type": "subscribe", "execution_id": str(execution_id), "after_seq": 0}),
        )

    event_frame = json.loads(ws.send_text.await_args_list[1].args[0])
    assert event_frame == {
        "type": "event",
        "execution_id": str(execution_id),
        "seq": 4,
        "event_type": "assistant_text",
        "payload": {"content": "hello"},
        "created_at": "2026-04-24T12:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_websocket_subscriber_broadcasts_failed_completion_with_error_payload(monkeypatch) -> None:
    broadcast = AsyncMock()
    remove = MagicMock()
    monkeypatch.setattr(
        "app.core.events.subscribers.websocket.execution_subscription_manager.broadcast_event",
        broadcast,
    )
    monkeypatch.setattr(
        "app.core.events.subscribers.websocket.execution_subscription_manager.remove_execution",
        remove,
    )

    envelope = ExecutionEventEnvelope(
        execution_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        event_type=ExecutionEventType.EXECUTION_COMPLETED,
        terminal_status="failed",
        error={
            "code": "NODE_MODEL_NOT_CONFIGURED",
            "message": 'Node "JSON 抽取子智能体" has no model configured.',
            "source": "node",
            "retryable": False,
        },
    )

    await WebSocketSubscriber().handle(envelope)

    broadcast.assert_awaited_once()
    payload = broadcast.await_args.args[1]
    assert payload["type"] == "execution_completed"
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "NODE_MODEL_NOT_CONFIGURED"
