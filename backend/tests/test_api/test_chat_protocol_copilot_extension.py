"""Tests for copilot extension parsing in chat protocol."""
from app.websocket.chat_protocol import parse_client_frame, ChatProtocolError
import pytest


def _make_copilot_frame(*, graph_context=None, mode=None, run_id=None, conversation_history=None):
    return {
        "type": "chat.start",
        "request_id": "req-1",
        "graph_id": "00000000-0000-0000-0000-000000000001",
        "input": {"message": "Build a RAG pipeline"},
        "extension": {
            "kind": "copilot",
            "run_id": run_id,
            "graph_context": graph_context if graph_context is not None else {"nodes": [], "edges": []},
            "conversation_history": conversation_history or [],
            "mode": mode or "deepagents",
        },
    }


def test_parse_copilot_extension_frame():
    result = parse_client_frame(_make_copilot_frame(run_id="run-abc"))
    assert result.extension.kind == "copilot"
    assert result.extension.run_id == "run-abc"
    assert result.extension.graph_context == {"nodes": [], "edges": []}
    assert result.extension.mode == "deepagents"
    assert result.extension.conversation_history == []


def test_parse_copilot_extension_defaults():
    """mode defaults to deepagents, conversation_history defaults to []."""
    frame = {
        "type": "chat.start",
        "request_id": "req-2",
        "input": {"message": "test"},
        "extension": {"kind": "copilot", "graph_context": {"nodes": []}},
    }
    result = parse_client_frame(frame)
    assert result.extension.kind == "copilot"
    assert result.extension.mode == "deepagents"
    assert result.extension.conversation_history == []
    assert result.extension.run_id is None


def test_parse_copilot_extension_missing_graph_context():
    """graph_context is required — missing it should raise."""
    frame = {
        "type": "chat.start",
        "request_id": "req-3",
        "input": {"message": "test"},
        "extension": {"kind": "copilot"},
    }
    with pytest.raises(ChatProtocolError, match="graph_context"):
        parse_client_frame(frame)


def test_existing_extensions_still_work():
    """Regression: skill_creator and chat extensions unchanged."""
    sc_frame = {
        "type": "chat.start",
        "request_id": "req-4",
        "input": {"message": "test"},
        "extension": {"kind": "skill_creator", "run_id": "r1", "edit_skill_id": "s1"},
    }
    result = parse_client_frame(sc_frame)
    assert result.extension.kind == "skill_creator"

    chat_frame = {
        "type": "chat.start",
        "request_id": "req-5",
        "input": {"message": "test"},
        "extension": {"kind": "chat", "run_id": "r2"},
    }
    result = parse_client_frame(chat_frame)
    assert result.extension.kind == "chat"
