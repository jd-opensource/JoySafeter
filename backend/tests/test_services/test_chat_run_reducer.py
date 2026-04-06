"""Tests for the Chat run reducer and agent registration."""

from app.services.agent_registry import agent_registry


def test_chat_definition_registered() -> None:
    definition = agent_registry.get("chat")
    assert definition.agent_name == "chat"
    assert definition.display_name == "Chat"
    assert definition.run_type == "chat_turn"


def test_chat_initial_projection() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection(
        {"graph_id": "graph-1", "thread_id": "thread-1"},
        status="queued",
    )
    assert projection["run_type"] == "chat_turn"
    assert projection["status"] == "queued"
    assert projection["graph_id"] == "graph-1"
    assert projection["thread_id"] == "thread-1"
    assert projection["user_message"] is None
    assert projection["assistant_message"] is None
    assert projection["file_tree"] == {}
    assert projection["preview_data"] is None
    assert projection["node_execution_log"] == []
    assert projection["interrupt"] is None


def test_chat_reducer_user_message_added() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    next_projection = definition.reducer(
        projection,
        event_type="user_message_added",
        payload={"message": {"id": "msg-user-1", "role": "user", "content": "Hello"}},
        status="running",
    )

    assert next_projection["user_message"] == {
        "id": "msg-user-1",
        "role": "user",
        "content": "Hello",
    }


def test_chat_reducer_assistant_message_started() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    next_projection = definition.reducer(
        projection,
        event_type="assistant_message_started",
        payload={"message": {"id": "msg-ai-1", "role": "assistant", "content": ""}},
        status="running",
    )

    assert next_projection["assistant_message"] == {
        "id": "msg-ai-1",
        "role": "assistant",
        "content": "",
    }


def test_chat_reducer_content_delta() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    projection = definition.reducer(
        projection,
        event_type="assistant_message_started",
        payload={"message": {"id": "msg-ai-1", "role": "assistant", "content": ""}},
        status="running",
    )
    projection = definition.reducer(
        projection,
        event_type="content_delta",
        payload={"message_id": "msg-ai-1", "delta": "Hello"},
        status="running",
    )
    next_projection = definition.reducer(
        projection,
        event_type="content_delta",
        payload={"message_id": "msg-ai-1", "delta": " world"},
        status="running",
    )

    assert next_projection["assistant_message"]["content"] == "Hello world"


def test_chat_reducer_tool_start() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    projection = definition.reducer(
        projection,
        event_type="assistant_message_started",
        payload={"message": {"id": "msg-ai-1", "role": "assistant", "content": ""}},
        status="running",
    )
    next_projection = definition.reducer(
        projection,
        event_type="tool_start",
        payload={
            "message_id": "msg-ai-1",
            "tool": {"id": "tool-1", "name": "some_tool", "status": "running"},
        },
        status="running",
    )

    assert next_projection["assistant_message"]["tool_calls"] == [
        {"id": "tool-1", "name": "some_tool", "status": "running"}
    ]


def test_chat_reducer_tool_end_updates_tool_and_captures_preview() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    projection = definition.reducer(
        projection,
        event_type="assistant_message_started",
        payload={"message": {"id": "msg-ai-1", "role": "assistant", "content": ""}},
        status="running",
    )
    projection = definition.reducer(
        projection,
        event_type="tool_start",
        payload={
            "message_id": "msg-ai-1",
            "tool": {"id": "tool-1", "name": "preview_skill", "status": "running"},
        },
        status="running",
    )
    next_projection = definition.reducer(
        projection,
        event_type="tool_end",
        payload={
            "message_id": "msg-ai-1",
            "tool_id": "tool-1",
            "tool_name": "preview_skill",
            "tool_output": {"name": "my-skill"},
        },
        status="running",
    )

    tool = next_projection["assistant_message"]["tool_calls"][0]
    assert tool["status"] == "completed"
    assert tool["result"] == {"name": "my-skill"}
    assert next_projection["preview_data"] == {"name": "my-skill"}


def test_chat_reducer_file_event_create_and_delete() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    projection = definition.reducer(
        projection,
        event_type="file_event",
        payload={"path": "/foo/bar.py", "action": "create", "size": 42, "timestamp": 1000},
        status="running",
    )
    assert "/foo/bar.py" in projection["file_tree"]
    assert projection["file_tree"]["/foo/bar.py"]["action"] == "create"

    next_projection = definition.reducer(
        projection,
        event_type="file_event",
        payload={"path": "/foo/bar.py", "action": "delete"},
        status="running",
    )
    assert "/foo/bar.py" not in next_projection["file_tree"]


def test_chat_reducer_node_start_and_end() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    projection = definition.reducer(
        projection,
        event_type="node_start",
        payload={"node_id": "node-1", "node_name": "my_node", "start_time": 100},
        status="running",
    )
    assert len(projection["node_execution_log"]) == 1
    assert projection["node_execution_log"][0]["node_id"] == "node-1"
    assert projection["node_execution_log"][0]["status"] == "running"

    next_projection = definition.reducer(
        projection,
        event_type="node_end",
        payload={"node_id": "node-1", "end_time": 200},
        status="running",
    )
    assert len(next_projection["node_execution_log"]) == 1
    assert next_projection["node_execution_log"][0]["status"] == "completed"
    assert next_projection["node_execution_log"][0]["end_time"] == 200


def test_chat_reducer_interrupt() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    next_projection = definition.reducer(
        projection,
        event_type="interrupt",
        payload={"interrupt": {"type": "human_approval", "message": "Approve?"}},
        status="interrupted",
    )

    assert next_projection["interrupt"] == {"type": "human_approval", "message": "Approve?"}
    assert next_projection["status"] == "interrupted"


def test_chat_reducer_error() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    next_projection = definition.reducer(
        projection,
        event_type="error",
        payload={"message": "Something went wrong"},
        status="failed",
    )

    assert next_projection["meta"]["error"] == "Something went wrong"
    assert next_projection["status"] == "failed"


def test_chat_reducer_done() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    next_projection = definition.reducer(
        projection,
        event_type="done",
        payload={},
        status="completed",
    )

    assert next_projection["meta"]["completed"] is True
    assert next_projection["status"] == "completed"


def test_chat_reducer_status_message() -> None:
    definition = agent_registry.get("chat")
    projection = definition.make_initial_projection({}, status="running")

    next_projection = definition.reducer(
        projection,
        event_type="status",
        payload={"message": "Processing your request..."},
        status="running",
    )

    assert next_projection["meta"]["status_message"] == "Processing your request..."


def test_chat_reducer_run_initialized() -> None:
    definition = agent_registry.get("chat")

    next_projection = definition.reducer(
        None,
        event_type="run_initialized",
        payload={"graph_id": "graph-99", "thread_id": "thread-77"},
        status="queued",
    )

    assert next_projection["run_type"] == "chat_turn"
    assert next_projection["status"] == "queued"
    assert next_projection["graph_id"] == "graph-99"
    assert next_projection["thread_id"] == "thread-77"
    assert next_projection["user_message"] is None
    assert next_projection["assistant_message"] is None
