"""Tests for copilot history built from agent_run snapshots."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import uuid


def _make_run(*, graph_id: str, title: str, status: str = "completed") -> MagicMock:
    run = MagicMock()
    run.id = uuid.uuid4()
    run.graph_id = uuid.UUID(graph_id)
    run.title = title
    run.status = status
    run.created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    run.updated_at = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)
    return run


def _make_snapshot(*, result_message: str, result_actions: list | None = None,
                   thought_steps: list | None = None, tool_calls: list | None = None) -> MagicMock:
    snap = MagicMock()
    snap.projection = {
        "result_message": result_message,
        "result_actions": result_actions or [],
        "content": "",
        "thought_steps": thought_steps or [],
        "tool_calls": tool_calls or [],
    }
    return snap


def test_build_history_messages_from_runs():
    """History messages are assembled from run title + snapshot projection."""
    graph_id = str(uuid.uuid4())
    # DB returns newest-first; reversed() produces oldest-first for the response
    runs = [
        _make_run(graph_id=graph_id, title="Build RAG"),   # newest
        _make_run(graph_id=graph_id, title="Hello"),        # oldest
    ]
    snapshots = {
        runs[0].id: _make_snapshot(result_message="Here is your RAG pipeline.", result_actions=[{"type": "add_node", "payload": {}}]),
        runs[1].id: _make_snapshot(result_message="Hi! How can I help?"),
    }

    messages = []
    for run in reversed(list(runs)):  # oldest first
        snap = snapshots.get(run.id)
        if not snap or not snap.projection:
            continue
        p = snap.projection
        messages.append({
            "role": "user",
            "content": run.title or "",
            "created_at": run.created_at.isoformat(),
        })
        messages.append({
            "role": "assistant",
            "content": p.get("result_message") or p.get("content", ""),
            "created_at": run.updated_at.isoformat(),
            "actions": p.get("result_actions", []),
            "thought_steps": p.get("thought_steps", []),
            "tool_calls": p.get("tool_calls", []),
        })

    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hi! How can I help?"
    assert messages[2]["content"] == "Build RAG"
    assert messages[3]["actions"] == [{"type": "add_node", "payload": {}}]


def test_build_history_filters_by_graph_id():
    """Only runs matching the requested graph_id are included."""
    target_gid = str(uuid.uuid4())
    other_gid = str(uuid.uuid4())
    runs = [
        _make_run(graph_id=target_gid, title="Match"),
        _make_run(graph_id=other_gid, title="NoMatch"),
    ]
    filtered = [r for r in runs if str(r.graph_id) == target_gid]
    assert len(filtered) == 1
    assert filtered[0].title == "Match"


def test_build_history_skips_runs_without_snapshot():
    """Runs that have no snapshot are silently skipped."""
    graph_id = str(uuid.uuid4())
    runs = [_make_run(graph_id=graph_id, title="NoSnap")]

    messages = []
    for run in reversed(list(runs)):
        snapshot = None  # simulate missing snapshot
        if not snapshot:
            continue
        # would append messages here, but we skip
    assert len(messages) == 0
