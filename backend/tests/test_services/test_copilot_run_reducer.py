"""Tests for copilot run projection reducer."""

from app.services.run_reducers.copilot import apply_copilot_event, make_initial_projection


def _base():
    return make_initial_projection({"graph_id": "g1", "mode": "deepagents"}, "queued")


def test_copilot_definition_registered():
    from app.services.agent_registry import agent_registry

    defn = agent_registry.get("copilot")
    assert defn.agent_name == "copilot"
    assert defn.run_type == "copilot_turn"


def test_copilot_initial_projection():
    p = _base()
    assert p["run_type"] == "copilot_turn"
    assert p["status"] == "queued"
    assert p["graph_id"] == "g1"
    assert p["mode"] == "deepagents"
    assert p["content"] == ""
    assert p["thought_steps"] == []


def test_copilot_reducer_run_initialized():
    p = apply_copilot_event(
        None, event_type="run_initialized", payload={"graph_id": "g2", "mode": "standard"}, status="running"
    )
    assert p["graph_id"] == "g2"
    assert p["mode"] == "standard"


def test_copilot_reducer_status():
    p = apply_copilot_event(
        _base(), event_type="status", payload={"stage": "thinking", "message": "Thinking..."}, status="running"
    )
    assert p["stage"] == "thinking"


def test_copilot_reducer_content_delta():
    p = apply_copilot_event(_base(), event_type="content_delta", payload={"delta": "Hello "}, status="running")
    p = apply_copilot_event(p, event_type="content_delta", payload={"delta": "world"}, status="running")
    assert p["content"] == "Hello world"


def test_copilot_reducer_thought_step():
    p = apply_copilot_event(
        _base(), event_type="thought_step", payload={"step": {"index": 1, "content": "Analyzing"}}, status="running"
    )
    assert len(p["thought_steps"]) == 1
    assert p["thought_steps"][0]["content"] == "Analyzing"


def test_copilot_reducer_tool_call():
    p = apply_copilot_event(
        _base(), event_type="tool_call", payload={"tool": "create_node", "input": {"type": "agent"}}, status="running"
    )
    assert len(p["tool_calls"]) == 1
    assert p["tool_calls"][0]["tool"] == "create_node"


def test_copilot_reducer_tool_result():
    action = {"type": "CREATE_NODE", "payload": {"id": "n1"}, "reasoning": "Need agent"}
    p = apply_copilot_event(_base(), event_type="tool_result", payload={"action": action}, status="running")
    assert len(p["tool_results"]) == 1
    assert p["tool_results"][0]["type"] == "CREATE_NODE"


def test_copilot_reducer_result():
    actions = [{"type": "CREATE_NODE", "payload": {"id": "n1"}, "reasoning": "test"}]
    p = apply_copilot_event(
        _base(), event_type="result", payload={"message": "Done!", "actions": actions}, status="running"
    )
    assert p["result_message"] == "Done!"
    assert len(p["result_actions"]) == 1


def test_copilot_reducer_error():
    p = apply_copilot_event(
        _base(), event_type="error", payload={"message": "LLM failed", "code": "AGENT_ERROR"}, status="failed"
    )
    assert p["status"] == "failed"
    assert p["error"] == "LLM failed"


def test_copilot_reducer_done():
    p = apply_copilot_event(_base(), event_type="done", payload={}, status="completed")
    assert p["status"] == "completed"


def test_copilot_reducer_done_preserves_failed():
    p = apply_copilot_event(_base(), event_type="error", payload={"message": "err"}, status="failed")
    p = apply_copilot_event(p, event_type="done", payload={}, status="failed")
    assert p["status"] == "failed"
