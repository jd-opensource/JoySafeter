from __future__ import annotations

from app.core.agent.cli_backends.base import CLIMessage
from app.core.agent.cli_backends.execution_runner import ExecutionRunner


def test_msg_to_event_type_text():
    msg = CLIMessage(type="text", content="hello")
    assert ExecutionRunner._msg_to_event_type(msg) == "assistant_text"


def test_msg_to_event_type_thinking():
    msg = CLIMessage(type="thinking", content="hmm")
    assert ExecutionRunner._msg_to_event_type(msg) == "thinking"


def test_msg_to_event_type_tool_use():
    msg = CLIMessage(type="tool_use", tool="Bash", call_id="c1")
    assert ExecutionRunner._msg_to_event_type(msg) == "tool_use_start"


def test_msg_to_event_type_tool_result():
    msg = CLIMessage(type="tool_result", tool="Bash", call_id="c1", output="ok")
    assert ExecutionRunner._msg_to_event_type(msg) == "tool_use_end"


def test_msg_to_event_type_error():
    msg = CLIMessage(type="error", content="boom")
    assert ExecutionRunner._msg_to_event_type(msg) == "error"


def test_msg_to_event_type_artifact():
    msg = CLIMessage(type="artifact", content="file data")
    assert ExecutionRunner._msg_to_event_type(msg) == "artifact_created"


def test_msg_to_event_type_unknown():
    msg = CLIMessage(type="custom_type", content="data")
    assert ExecutionRunner._msg_to_event_type(msg) == "custom_type"


def test_msg_to_payload_text():
    msg = CLIMessage(type="text", content="hello world")
    payload = ExecutionRunner._msg_to_payload(msg)
    assert payload == {"content": "hello world"}


def test_msg_to_payload_thinking():
    msg = CLIMessage(type="thinking", content="analyzing")
    payload = ExecutionRunner._msg_to_payload(msg)
    assert payload == {"content": "analyzing"}


def test_msg_to_payload_tool_use():
    msg = CLIMessage(type="tool_use", tool="Bash", call_id="c1", input={"command": "ls"})
    payload = ExecutionRunner._msg_to_payload(msg)
    assert payload["tool"]["name"] == "Bash"
    assert payload["tool"]["call_id"] == "c1"
    assert payload["tool"]["input"] == {"command": "ls"}
    assert payload["tool"]["status"] == "running"


def test_msg_to_payload_tool_result():
    msg = CLIMessage(type="tool_result", tool="Bash", call_id="c1", output="file.txt")
    payload = ExecutionRunner._msg_to_payload(msg)
    assert payload["call_id"] == "c1"
    assert payload["tool_name"] == "Bash"
    assert payload["output"] == "file.txt"


def test_msg_to_payload_error():
    msg = CLIMessage(type="error", content="OOM killed")
    payload = ExecutionRunner._msg_to_payload(msg)
    assert payload == {"message": "OOM killed"}


def test_msg_to_payload_artifact():
    msg = CLIMessage(type="artifact", content="binary data")
    payload = ExecutionRunner._msg_to_payload(msg)
    assert payload == {"artifact": {"content": "binary data"}}


def test_msg_to_payload_unknown():
    msg = CLIMessage(type="custom", content="stuff")
    payload = ExecutionRunner._msg_to_payload(msg)
    assert payload == {"content": "stuff"}


def test_runner_accepts_none_callbacks():
    """Standalone executions pass callbacks=None."""
    from unittest.mock import MagicMock

    db = MagicMock()
    runner = ExecutionRunner(db, callbacks=None)
    assert runner.callbacks is None


def test_runner_accepts_callbacks():
    """Mission executions pass a callbacks implementation."""
    from unittest.mock import MagicMock

    db = MagicMock()

    class StubCallbacks:
        async def on_execution_finalized(self, execution_id, status, result): ...
        async def on_execution_failed(self, execution_id, error): ...

    runner = ExecutionRunner(db, callbacks=StubCallbacks())
    assert runner.callbacks is not None
