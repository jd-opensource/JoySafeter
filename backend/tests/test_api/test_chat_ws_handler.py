"""Tests for ChatWsHandler — focuses on critical frame-output paths."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.websocket.chat_ws_handler import ChatWsHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockWebSocket:
    """Minimal WebSocket stub that records sent frames."""

    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        self.closed = True

    def frames_of_type(self, type_: str) -> list[dict]:
        return [f for f in self.sent if f.get("type") == type_]


def make_handler(ws: MockWebSocket | None = None) -> tuple[ChatWsHandler, MockWebSocket]:
    if ws is None:
        ws = MockWebSocket()
    handler = ChatWsHandler(user_id="user-123", websocket=ws)
    return handler, ws


# ---------------------------------------------------------------------------
# Ping/pong
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_returns_pong() -> None:
    handler, ws = make_handler()
    await handler._handle_frame(json.dumps({"type": "ping"}))
    assert ws.frames_of_type("pong"), "expected a pong frame"


# ---------------------------------------------------------------------------
# Duplicate request guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_request_id_sends_ws_error() -> None:
    handler, ws = make_handler()
    # Pre-populate _tasks with a fake entry for the same request_id
    fake_task = MagicMock(spec=asyncio.Task)
    handler._tasks["req-1"] = (None, fake_task)

    frame = json.dumps({"type": "chat", "request_id": "req-1", "message": "hello"})
    await handler._handle_frame(frame)

    errors = ws.frames_of_type("ws_error")
    assert errors, "expected ws_error for duplicate request_id"
    assert "duplicate" in errors[0].get("message", "")


# ---------------------------------------------------------------------------
# _handle_stop: no-op for unknown request, cancels for known request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_stop_noop_for_unknown_request() -> None:
    handler, ws = make_handler()
    # Should not raise
    await handler._handle_frame(json.dumps({"type": "stop", "request_id": "unknown-req"}))
    assert ws.sent == [], "stop for unknown request should send nothing"


@pytest.mark.asyncio
async def test_handle_stop_cancels_known_task() -> None:
    handler, ws = make_handler()
    cancelled = False

    async def slow():
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled = True
            raise

    task = asyncio.create_task(slow())
    handler._tasks["req-stop"] = ("thread-1", task)

    with patch("app.websocket.chat_ws_handler.task_manager") as mock_tm:
        mock_tm.stop_task = AsyncMock()
        await handler._handle_frame(json.dumps({"type": "stop", "request_id": "req-stop"}))
        mock_tm.stop_task.assert_awaited_once_with("thread-1")

    # Give event loop a tick to propagate cancellation
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled


# ---------------------------------------------------------------------------
# _cancel_all_tasks: called on disconnect, cancels everything
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_all_tasks_on_disconnect() -> None:
    """run() must call _cancel_all_tasks when WebSocketDisconnect is raised."""
    from fastapi import WebSocketDisconnect

    handler, ws = make_handler()

    done_flag = asyncio.Event()

    async def long_running():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            done_flag.set()
            raise

    task = asyncio.create_task(long_running())
    handler._tasks["req-dc"] = (None, task)

    # Simulate disconnect: receive_text raises WebSocketDisconnect
    ws_mock = MagicMock()
    ws_mock.receive_text = AsyncMock(side_effect=WebSocketDisconnect(code=1001))
    handler.websocket = ws_mock

    with patch("app.websocket.chat_ws_handler.task_manager") as mock_tm:
        mock_tm.stop_task = AsyncMock()
        await handler.run()

    # Wait briefly for the task to be cancelled
    await asyncio.sleep(0.05)
    assert done_flag.is_set(), "long-running task should have been cancelled on disconnect"


# ---------------------------------------------------------------------------
# _run_chat_turn: done frame sent even when thread_id is None (early failure)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_done_frame_sent_on_early_error_no_thread_id() -> None:
    """
    If get_or_create_conversation raises before thread_id is assigned,
    the handler must still send a done frame (not just an error frame).
    """
    handler, ws = make_handler()

    from app.schemas.chat import ChatRequest

    payload = ChatRequest(message="hello", thread_id=None, graph_id=None, metadata={})

    with (
        patch("app.websocket.chat_ws_handler.AsyncSessionLocal") as mock_session_cls,
        patch("app.websocket.chat_ws_handler.get_or_create_conversation", side_effect=RuntimeError("db down")),
        patch("app.websocket.chat_ws_handler._finalize_task_noop", create=True),
        patch("app.websocket.chat_ws_handler.task_manager"),
    ):
        # Make AsyncSessionLocal return an async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_cm

        await handler._run_chat_turn(request_id="req-early", payload=payload)

    sent_types = [f["type"] for f in ws.sent]
    assert "error" in sent_types, "error frame must be sent"
    assert "done" in sent_types, "done frame must be sent even when thread_id is None"

    # done must come after error
    assert sent_types.index("done") > sent_types.index("error")


# ---------------------------------------------------------------------------
# CancelledError: done frame sent before re-raising
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_error_sends_done_frame() -> None:
    """
    When the turn task is cancelled mid-stream, a done frame must be sent
    before asyncio.CancelledError propagates.
    """
    handler, ws = make_handler()

    from app.schemas.chat import ChatRequest

    payload = ChatRequest(message="hello", thread_id=None, graph_id=None, metadata={})

    async def raise_cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    with (
        patch("app.websocket.chat_ws_handler.AsyncSessionLocal") as mock_session_cls,
        patch("app.websocket.chat_ws_handler.get_or_create_conversation", side_effect=raise_cancelled),
        patch("app.websocket.chat_ws_handler.task_manager"),
    ):
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_cm

        with pytest.raises(asyncio.CancelledError):
            await handler._run_chat_turn(request_id="req-cancel", payload=payload)

    sent_types = [f["type"] for f in ws.sent]
    assert "done" in sent_types, "done frame must be sent on CancelledError"
