"""Tests for copilot event mirroring logic.

Verifies that copilot-specific event types are correctly translated into
payloads that the copilot reducer can process. This tests the translation
logic used by _mirror_run_stream_event in chat_ws_handler.py.
"""

from __future__ import annotations

from typing import Any

from app.services.run_reducers.copilot import apply_copilot_event, make_initial_projection


def _mirror_event_to_payload(
    event_type: str,
    data: dict[str, Any],
    assistant_message_id: str = "msg-1",
) -> tuple[str, dict[str, Any] | None]:
    """
    Reproduce the event-type → payload translation from _mirror_run_stream_event.

    Returns (stored_event_type, payload) — None payload means event is dropped.
    """
    payload: dict[str, Any] | None = None

    if event_type == "status":
        stage = data.get("stage")
        if stage is not None:
            payload = {"stage": stage, "message": data.get("message", "")}
        else:
            message = str(data.get("status") or "")
            payload = {"message": message, "status": message}
    elif event_type == "content" and assistant_message_id:
        delta = data.get("delta") if "delta" in data else data.get("content")
        if delta:
            payload = {"message_id": assistant_message_id, "delta": str(delta)}
    elif event_type in ("thought_step", "tool_call", "tool_result", "result"):
        payload = data
    elif event_type == "error":
        payload = {"message": data.get("message"), "code": data.get("code")}
    elif event_type == "done":
        payload = {}

    stored_type = "content_delta" if event_type == "content" else event_type
    return stored_type, payload


# --- Mirror translation tests ---


def test_copilot_status_with_stage():
    """Copilot status events preserve the 'stage' field."""
    event_type, payload = _mirror_event_to_payload(
        "status",
        {"type": "status", "stage": "thinking", "message": "Analyzing..."},
    )
    assert event_type == "status"
    assert payload == {"stage": "thinking", "message": "Analyzing..."}


def test_chat_status_without_stage():
    """Chat status events (no stage) still work."""
    event_type, payload = _mirror_event_to_payload(
        "status",
        {"status": "processing"},
    )
    assert event_type == "status"
    assert payload == {"message": "processing", "status": "processing"}


def test_copilot_content_uses_content_key():
    """Copilot content events use 'content' key instead of 'delta'."""
    event_type, payload = _mirror_event_to_payload(
        "content",
        {"type": "content", "content": "Hello"},
    )
    assert event_type == "content_delta"
    assert payload is not None
    assert payload["delta"] == "Hello"


def test_chat_content_uses_delta_key():
    """Chat content events with 'delta' still work."""
    event_type, payload = _mirror_event_to_payload(
        "content",
        {"delta": "chunk"},
    )
    assert event_type == "content_delta"
    assert payload is not None
    assert payload["delta"] == "chunk"


def test_thought_step_passthrough():
    data = {"type": "thought_step", "step": "Considering graph"}
    event_type, payload = _mirror_event_to_payload("thought_step", data)
    assert event_type == "thought_step"
    assert payload is data  # pass-through, not copied


def test_tool_call_passthrough():
    data = {"type": "tool_call", "tool": "search", "input": {"q": "test"}}
    event_type, payload = _mirror_event_to_payload("tool_call", data)
    assert event_type == "tool_call"
    assert payload["tool"] == "search"
    assert payload["input"] == {"q": "test"}


def test_tool_result_passthrough():
    action = {"type": "add_node", "payload": {"name": "n1"}}
    data = {"type": "tool_result", "action": action}
    event_type, payload = _mirror_event_to_payload("tool_result", data)
    assert event_type == "tool_result"
    assert payload["action"] == action


def test_result_passthrough():
    actions = [{"type": "add_node", "payload": {}}]
    data = {"type": "result", "message": "Done!", "actions": actions}
    event_type, payload = _mirror_event_to_payload("result", data)
    assert event_type == "result"
    assert payload["message"] == "Done!"
    assert payload["actions"] == actions


def test_unknown_event_type_dropped():
    """Unknown event types produce None payload and are dropped."""
    _, payload = _mirror_event_to_payload("unknown_copilot_event", {"foo": "bar"})
    assert payload is None


# --- End-to-end: mirror → reducer integration ---


def test_copilot_event_flow_mirror_to_reducer():
    """Full pipeline: copilot events → mirror translation → reducer produces correct projection."""
    events = [
        ("status", {"type": "status", "stage": "thinking", "message": "Thinking..."}),
        ("content", {"type": "content", "content": "Here is "}),
        ("content", {"type": "content", "content": "the answer."}),
        ("thought_step", {"type": "thought_step", "step": "Analyzed requirements"}),
        ("tool_call", {"type": "tool_call", "tool": "add_node", "input": {"name": "n1"}}),
        ("tool_result", {"type": "tool_result", "action": {"type": "add_node", "payload": {"name": "n1"}}}),
        (
            "result",
            {"type": "result", "message": "Built your pipeline.", "actions": [{"type": "add_node", "payload": {}}]},
        ),
        ("done", {}),
    ]

    projection = make_initial_projection({"graph_id": "g1", "mode": "deepagents"}, "running")

    for raw_type, data in events:
        stored_type, payload = _mirror_event_to_payload(raw_type, data)
        if payload is None:
            continue
        projection = apply_copilot_event(
            projection,
            event_type=stored_type,
            payload=payload,
            status="running" if raw_type != "done" else "completed",
        )

    assert projection["stage"] == "thinking"
    assert projection["content"] == "Here is the answer."
    assert len(projection["thought_steps"]) == 1
    assert projection["thought_steps"][0] == "Analyzed requirements"
    assert len(projection["tool_calls"]) == 1
    assert projection["tool_calls"][0]["tool"] == "add_node"
    assert len(projection["tool_results"]) == 1
    assert projection["result_message"] == "Built your pipeline."
    assert len(projection["result_actions"]) == 1
    assert projection["status"] == "completed"
    assert projection["graph_id"] == "g1"
    assert projection["mode"] == "deepagents"
