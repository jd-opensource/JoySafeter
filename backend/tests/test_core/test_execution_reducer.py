from __future__ import annotations

import pytest

execution_reducer = pytest.importorskip("app.services.execution_reducer")

apply_execution_event = execution_reducer.apply_execution_event
make_initial_projection = execution_reducer.make_initial_projection


def test_make_initial_projection():
    proj = make_initial_projection(
        {"source": "task", "task_id": "m1", "agent_profile_id": "a1"},
        "queued",
    )
    assert proj["status"] == "queued"
    assert proj["source"] == "task"
    assert proj["task_id"] == "m1"  
    assert proj["agent_profile_id"] == "a1"
    assert proj["messages"] == []
    assert proj["tool_calls"] == []
    assert proj["artifacts"] == []


def test_execution_started():
    proj = make_initial_projection({"source": "chat"}, "running")
    proj = apply_execution_event(
        proj,
        event_type="execution_started",
        payload={"container_id": "ctr-1", "session_id": "sess-1"},
        status="running",
    )
    assert proj["container_id"] == "ctr-1"
    assert proj["session_id"] == "sess-1"
    assert proj["status"] == "running"


def test_prompt_sent():
    proj = make_initial_projection({}, "running")
    msg = {"role": "user", "content": "Fix the bug"}
    proj = apply_execution_event(
        proj,
        event_type="prompt_sent",
        payload={"message": msg},
        status="running",
    )
    assert len(proj["messages"]) == 1
    assert proj["messages"][0]["content"] == "Fix the bug"


def test_assistant_text_with_message_dict():
    proj = make_initial_projection({}, "running")
    msg = {"role": "assistant", "content": "On it"}
    proj = apply_execution_event(
        proj,
        event_type="assistant_text",
        payload={"message": msg},
        status="running",
    )
    assert len(proj["messages"]) == 1
    assert proj["messages"][0]["content"] == "On it"


def test_assistant_text_with_content_string():
    proj = make_initial_projection({}, "running")
    proj = apply_execution_event(
        proj,
        event_type="assistant_text",
        payload={"content": "Hello"},
        status="running",
    )
    assert len(proj["messages"]) == 1
    assert proj["messages"][0]["role"] == "assistant"
    assert proj["messages"][0]["content"] == "Hello"


def test_content_delta_appends():
    proj = make_initial_projection({}, "running")
    proj["messages"].append({"role": "assistant", "content": "Hel", "id": "m1"})
    proj = apply_execution_event(
        proj,
        event_type="content_delta",
        payload={"delta": "lo", "message_id": "m1"},
        status="running",
    )
    assert proj["messages"][-1]["content"] == "Hello"


def test_content_delta_no_messages_is_noop():
    proj = make_initial_projection({}, "running")
    proj = apply_execution_event(
        proj,
        event_type="content_delta",
        payload={"delta": "x"},
        status="running",
    )
    assert proj["messages"] == []


def test_tool_use_start_with_dict():
    proj = make_initial_projection({}, "running")
    tool = {"name": "Bash", "call_id": "c1", "input": {"command": "ls"}, "status": "running"}
    proj = apply_execution_event(
        proj,
        event_type="tool_use_start",
        payload={"tool": tool},
        status="running",
    )
    assert len(proj["tool_calls"]) == 1
    assert proj["tool_calls"][0]["name"] == "Bash"


def test_tool_use_start_with_flat_fields():
    proj = make_initial_projection({}, "running")
    proj = apply_execution_event(
        proj,
        event_type="tool_use_start",
        payload={"tool_name": "Read", "call_id": "c2", "input": {"path": "/tmp"}},
        status="running",
    )
    assert len(proj["tool_calls"]) == 1
    assert proj["tool_calls"][0]["name"] == "Read"
    assert proj["tool_calls"][0]["status"] == "running"


def test_tool_use_end():
    proj = make_initial_projection({}, "running")
    proj["tool_calls"].append({"name": "Bash", "call_id": "c1", "status": "running"})
    proj = apply_execution_event(
        proj,
        event_type="tool_use_end",
        payload={"call_id": "c1", "output": "file.txt"},
        status="running",
    )
    assert proj["tool_calls"][0]["status"] == "completed"
    assert proj["tool_calls"][0]["output"] == "file.txt"


def test_tool_use_end_no_match():
    proj = make_initial_projection({}, "running")
    proj["tool_calls"].append({"name": "Bash", "call_id": "c1", "status": "completed"})
    proj = apply_execution_event(
        proj,
        event_type="tool_use_end",
        payload={"call_id": "c99", "output": "nope"},
        status="running",
    )
    # No match — original stays unchanged
    assert proj["tool_calls"][0]["status"] == "completed"
    assert "output" not in proj["tool_calls"][0] or proj["tool_calls"][0].get("output") != "nope"


def test_thinking():
    proj = make_initial_projection({}, "running")
    proj = apply_execution_event(
        proj,
        event_type="thinking",
        payload={"content": "analyzing..."},
        status="running",
    )
    assert proj["meta"]["last_thinking"] == "analyzing..."


def test_artifact_created():
    proj = make_initial_projection({}, "running")
    artifact = {"type": "file", "path": "/app/main.py"}
    proj = apply_execution_event(
        proj,
        event_type="artifact_created",
        payload={"artifact": artifact},
        status="running",
    )
    assert len(proj["artifacts"]) == 1
    assert proj["artifacts"][0]["path"] == "/app/main.py"


def test_approval_requested_and_resolved():
    proj = make_initial_projection({}, "approval_wait")
    proj = apply_execution_event(
        proj,
        event_type="approval_requested",
        payload={"tool": "Bash", "command": "rm -rf /"},
        status="approval_wait",
    )
    assert proj["meta"]["pending_approval"]["tool"] == "Bash"

    proj = apply_execution_event(
        proj,
        event_type="approval_resolved",
        payload={"approved": True},
        status="running",
    )
    assert "pending_approval" not in proj["meta"]


def test_error_event():
    proj = make_initial_projection({}, "failed")
    proj = apply_execution_event(
        proj,
        event_type="error",
        payload={"message": "OOM"},
        status="failed",
    )
    assert proj["meta"]["error"] == "OOM"
    assert proj["status"] == "failed"


def test_execution_completed():
    proj = make_initial_projection({}, "completed")
    proj = apply_execution_event(
        proj,
        event_type="execution_completed",
        payload={
            "result_summary": {"files_changed": 3},
            "error": {
                "code": "NODE_MODEL_NOT_CONFIGURED",
                "message": "Node model is missing.",
                "data": {"node_id": "node-1"},
            },
        },
        status="completed",
    )
    assert proj["meta"]["completed"] is True
    assert proj["meta"]["result_summary"]["files_changed"] == 3
    assert proj["meta"]["error"] == {
        "code": "NODE_MODEL_NOT_CONFIGURED",
        "message": "Node model is missing.",
        "data": {"node_id": "node-1"},
    }


def test_heartbeat_is_noop():
    proj = make_initial_projection({}, "running")
    original_messages = list(proj["messages"])
    proj = apply_execution_event(
        proj,
        event_type="heartbeat",
        payload={},
        status="running",
    )
    assert proj["messages"] == original_messages


def test_unknown_event_preserves_projection():
    proj = make_initial_projection({}, "running")
    proj["messages"].append({"role": "user", "content": "hi"})
    proj = apply_execution_event(
        proj,
        event_type="some_future_event",
        payload={"data": 1},
        status="running",
    )
    assert len(proj["messages"]) == 1
    assert proj["status"] == "running"


def test_immutability():
    """Verify that apply_execution_event does not mutate the input projection."""
    proj = make_initial_projection({}, "running")
    proj["messages"].append({"role": "assistant", "content": "hi", "id": "m1"})
    original_content = proj["messages"][0]["content"]

    _ = apply_execution_event(
        proj,
        event_type="content_delta",
        payload={"delta": " world", "message_id": "m1"},
        status="running",
    )
    # Original should be untouched
    assert proj["messages"][0]["content"] == original_content


def test_full_lifecycle():
    """Walk through a realistic sequence of events."""
    proj = make_initial_projection(
        {"source": "task", "task_id": "m1"},
        "queued",
    )
    assert proj["status"] == "queued"

    proj = apply_execution_event(
        proj,
        event_type="execution_started",
        payload={"container_id": "ctr-abc", "session_id": "s1"},
        status="running",
    )
    assert proj["container_id"] == "ctr-abc"

    proj = apply_execution_event(
        proj,
        event_type="prompt_sent",
        payload={"message": {"role": "user", "content": "Fix login bug"}},
        status="running",
    )

    proj = apply_execution_event(
        proj,
        event_type="assistant_text",
        payload={"message": {"role": "assistant", "content": "Looking into it", "id": "a1"}},
        status="running",
    )

    proj = apply_execution_event(
        proj,
        event_type="tool_use_start",
        payload={"tool": {"name": "Bash", "call_id": "t1", "input": {"command": "grep"}, "status": "running"}},
        status="running",
    )

    proj = apply_execution_event(
        proj,
        event_type="tool_use_end",
        payload={"call_id": "t1", "output": "found match"},
        status="running",
    )

    proj = apply_execution_event(
        proj,
        event_type="execution_completed",
        payload={"result_summary": {"fixed": True}},
        status="completed",
    )

    assert proj["status"] == "completed"
    assert len(proj["messages"]) == 2
    assert len(proj["tool_calls"]) == 1
    assert proj["tool_calls"][0]["status"] == "completed"
    assert proj["meta"]["completed"] is True
