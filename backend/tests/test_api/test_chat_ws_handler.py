"""Tests for ChatWsHandler — focuses on critical frame-output paths."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.websocket.chat_ws_handler import ChatTaskEntry, ChatWsHandler

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


@pytest.mark.asyncio
async def test_typed_resume_routes_to_resume_handler() -> None:
    handler, _ = make_handler()
    with patch.object(handler, "_handle_resume", new_callable=AsyncMock) as mock_resume:
        await handler._handle_frame(
            json.dumps(
                {
                    "type": "chat.resume",
                    "request_id": "req-resume",
                    "thread_id": "thread-typed",
                    "command": {},
                }
            )
        )
    mock_resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_typed_stop_routes_to_stop_handler() -> None:
    handler, _ = make_handler()
    with patch.object(handler, "_handle_stop", new_callable=AsyncMock) as mock_stop:
        await handler._handle_frame(json.dumps({"type": "chat.stop", "request_id": "req-stop"}))
    mock_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_chat_start_returns_protocol_error() -> None:
    handler, ws = make_handler()
    await handler._handle_frame(json.dumps({"type": "chat.start", "request_id": "req-bad"}))

    errors = ws.frames_of_type("ws_error")
    assert errors, "malformed chat.start should send ws_error"
    error = errors[0]
    assert "input" in error.get("message", "").lower()
    assert error.get("request_id") == "req-bad"


# ---------------------------------------------------------------------------
# Duplicate request guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_request_id_sends_ws_error() -> None:
    handler, ws = make_handler()
    # Pre-populate _tasks with a fake entry for the same request_id
    fake_task = MagicMock(spec=asyncio.Task)
    handler._tasks["req-1"] = ChatTaskEntry(thread_id=None, task=fake_task)

    frame = json.dumps({"type": "chat", "request_id": "req-1", "message": "hello"})
    await handler._handle_frame(frame)

    errors = ws.frames_of_type("ws_error")
    assert errors, "expected ws_error for duplicate request_id"
    assert "duplicate" in errors[0].get("message", "")


@pytest.mark.asyncio
async def test_legacy_skill_creator_metadata_maps_to_command() -> None:
    handler, ws = make_handler()

    captured_payload = None

    async def fake_run_chat_turn(*, request_id: str, payload) -> None:
        nonlocal captured_payload
        assert request_id == "req-legacy"
        captured_payload = payload

    legacy_frame = json.dumps(
        {
            "type": "chat",
            "request_id": "req-legacy",
            "message": "build me a skill",
            "metadata": {
                "mode": "skill_creator",
                "run_id": str(uuid.uuid4()),
                "edit_skill_id": "legacy-skill",
            },
        }
    )

    with patch.object(handler, "_run_chat_turn", side_effect=fake_run_chat_turn) as mock_run_chat_turn:
        await handler._handle_frame(legacy_frame)
        task = handler._tasks["req-legacy"].task
        await task

    mock_run_chat_turn.assert_awaited_once()
    assert captured_payload is not None
    assert captured_payload.metadata["edit_skill_id"] == "legacy-skill"
    assert ws.sent == []


@pytest.mark.asyncio
async def test_legacy_non_skill_creator_mode_is_preserved_in_metadata() -> None:
    handler, ws = make_handler()

    captured_payload = None

    async def fake_run_chat_turn(*, request_id: str, payload) -> None:
        nonlocal captured_payload
        assert request_id == "req-mode"
        captured_payload = payload

    frame = json.dumps(
        {
            "type": "chat",
            "request_id": "req-mode",
            "message": "hello",
            "metadata": {"mode": "apk-vulnerability"},
        }
    )

    with patch.object(handler, "_run_chat_turn", side_effect=fake_run_chat_turn) as mock_run_chat_turn:
        await handler._handle_frame(frame)
        task = handler._tasks["req-mode"].task
        await task

    mock_run_chat_turn.assert_awaited_once()
    assert captured_payload is not None
    assert captured_payload.metadata["mode"] == "apk-vulnerability"
    assert ws.sent == []


# ---------------------------------------------------------------------------
# Command parsing edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_object_json_frame_returns_ws_error() -> None:
    handler, ws = make_handler()

    await handler._handle_frame(json.dumps(["unexpected", "array"]))

    errors = ws.frames_of_type("ws_error")
    assert errors, "non-object JSON should emit ws_error instead of crashing"
    assert "object" in errors[0].get("message", "").lower()


@pytest.mark.asyncio
async def test_chat_start_with_invalid_extension_data_is_rejected() -> None:
    handler, ws = make_handler()

    await handler._handle_frame(
        json.dumps(
            {
                "type": "chat.start",
                "request_id": "req-invalid",
                "input": {"message": "hello"},
                "extension": {"kind": "unknown"},
                "metadata": {},
            }
        )
    )

    assert ws.frames_of_type("ws_error") == [
        {
            "type": "ws_error",
            "request_id": "req-invalid",
            "message": "unsupported extension kind: unknown",
        }
    ]
    assert "req-invalid" not in handler._tasks


@pytest.mark.asyncio
async def test_typed_skill_creator_extension_propagates_run_metadata() -> None:
    handler, ws = make_handler()
    captured_payload = None
    run_id = uuid.uuid4()

    async def fake_run_chat_turn(*, request_id: str, payload) -> None:
        nonlocal captured_payload
        assert request_id == "req-skill"
        captured_payload = payload

    frame = json.dumps(
        {
            "type": "chat.start",
            "request_id": "req-skill",
            "thread_id": None,
            "input": {"message": "build a skill", "files": []},
            "extension": {
                "kind": "skill_creator",
                "run_id": str(run_id),
                "edit_skill_id": "skill-42",
            },
            "metadata": {},
        }
    )

    with patch.object(handler, "_run_chat_turn", side_effect=fake_run_chat_turn) as mock_run_chat_turn:
        await handler._handle_frame(frame)
        entry = handler._tasks["req-skill"]
        await entry.task

    mock_run_chat_turn.assert_awaited_once()
    assert captured_payload is not None
    assert captured_payload.metadata["edit_skill_id"] == "skill-42"
    assert handler._tasks["req-skill"].run_id == run_id
    assert ws.sent == []


@pytest.mark.asyncio
async def test_input_files_are_forwarded_into_metadata() -> None:
    handler, ws = make_handler()
    captured_payload = None

    async def fake_run_chat_turn(*, request_id: str, payload) -> None:
        nonlocal captured_payload
        assert request_id == "req-files"
        captured_payload = payload

    files = [
        {"filename": "notes.md", "path": "/tmp/notes.md", "size": 10},
        {"filename": "plan.txt", "path": "/data/plan.txt", "size": 42},
    ]
    frame = json.dumps(
        {
            "type": "chat.start",
            "request_id": "req-files",
            "thread_id": None,
            "input": {"message": "see attached", "files": files},
            "extension": None,
            "metadata": {"foo": "bar"},
        }
    )

    with patch.object(handler, "_run_chat_turn", side_effect=fake_run_chat_turn) as mock_run_chat_turn:
        await handler._handle_frame(frame)
        entry = handler._tasks["req-files"]
        await entry.task

    mock_run_chat_turn.assert_awaited_once()
    assert captured_payload is not None
    assert captured_payload.metadata["files"] == files
    assert captured_payload.metadata["foo"] == "bar"
    assert ws.sent == []


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
    await asyncio.sleep(0)
    handler._tasks["req-stop"] = ChatTaskEntry(thread_id="thread-1", task=task)

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
    await asyncio.sleep(0)
    handler._tasks["req-dc"] = ChatTaskEntry(thread_id=None, task=task)

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


# ---------------------------------------------------------------------------
# Accepted ack: emitted after task registration and before first status frame
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_chat_turn_emits_accepted_before_status() -> None:
    handler, ws = make_handler()

    from app.schemas.chat import ChatRequest

    payload = ChatRequest(message="hello", thread_id=None, graph_id=None, metadata={})

    class FakeGraph:
        async def astream_events(self, *_args, **_kwargs):
            if False:
                yield None

    class FakeGraphService:
        def __init__(self, _db):
            pass

        async def create_default_deep_agents_graph(self, **_kwargs):
            return FakeGraph()

    async def fake_safe_get_state(*_args, **_kwargs):
        return MagicMock(tasks=[], values={})

    with (
        patch("app.websocket.chat_ws_handler.AsyncSessionLocal") as mock_session_cls,
        patch("app.websocket.chat_ws_handler.get_or_create_conversation", AsyncMock(return_value=("thread-ack", True))),
        patch("app.websocket.chat_ws_handler.save_user_message", AsyncMock()),
        patch(
            "app.websocket.chat_ws_handler.get_user_config",
            AsyncMock(
                return_value=(
                    {"configurable": {"thread_id": "thread-ack"}},
                    {},
                    {
                        "llm_model": "gpt-test",
                        "api_key": "test",
                        "base_url": "http://example.invalid",
                        "max_tokens": 1024,
                    },
                )
            ),
        ),
        patch("app.websocket.chat_ws_handler.GraphService", FakeGraphService),
        patch("app.websocket.chat_ws_handler.safe_get_state", side_effect=fake_safe_get_state),
        patch("app.websocket.chat_ws_handler.task_manager") as mock_tm,
        patch.object(handler, "_finalize_task", AsyncMock()),
        patch("app.websocket.chat_ws_handler.ArtifactCollector") as mock_artifacts,
    ):
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_cm
        mock_tm.register_task = AsyncMock()
        mock_tm.is_stopped = AsyncMock(return_value=False)
        mock_artifacts.return_value.ensure_run_dir = MagicMock()

        await handler._run_chat_turn(request_id="req-accepted", payload=payload)

    sent_types = [f["type"] for f in ws.sent]
    assert "accepted" in sent_types, "accepted ack must be emitted once the turn is registered"
    assert "status" in sent_types, "connected status must still be emitted"
    assert sent_types.index("accepted") < sent_types.index("status")

    accepted_frame = ws.frames_of_type("accepted")[0]
    assert accepted_frame["request_id"] == "req-accepted"
    assert accepted_frame["thread_id"] == "thread-ack"
