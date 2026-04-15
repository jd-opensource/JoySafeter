"""
Execution snapshot reducer.

Applies execution events to build a projection of the current execution state.
Each event type updates the projection dict immutably (via deepcopy).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _deepcopy_projection(projection: dict[str, Any] | None) -> dict[str, Any]:
    if projection is not None:
        return deepcopy(projection)
    return {
        "version": 1,
        "status": "queued",
        "source": None,
        "mission_id": None,
        "agent_profile_id": None,
        "container_id": None,
        "session_id": None,
        "messages": [],
        "tool_calls": [],
        "artifacts": [],
        "meta": {},
    }


def make_initial_projection(payload: dict[str, Any], status: str) -> dict[str, Any]:
    projection = _deepcopy_projection(None)
    projection["status"] = status
    projection["source"] = payload.get("source")
    projection["mission_id"] = payload.get("mission_id")
    projection["agent_profile_id"] = payload.get("agent_profile_id")
    return projection


def apply_execution_event(
    projection: dict[str, Any] | None,
    *,
    event_type: str,
    payload: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    next_proj = _deepcopy_projection(projection)
    next_proj["status"] = status

    if event_type == "execution_started":
        next_proj["container_id"] = payload.get("container_id")
        next_proj["session_id"] = payload.get("session_id")
        return next_proj

    if event_type == "prompt_sent":
        msg = payload.get("message")
        if isinstance(msg, dict):
            next_proj["messages"].append(msg)
        return next_proj

    if event_type == "assistant_text":
        msg = payload.get("message")
        if isinstance(msg, dict):
            next_proj["messages"].append(msg)
        elif isinstance(payload.get("content"), str):
            next_proj["messages"].append({
                "role": "assistant",
                "content": payload["content"],
            })
        return next_proj

    if event_type == "content_delta":
        delta = payload.get("delta", "")
        message_id = payload.get("message_id")
        if delta and next_proj["messages"]:
            last = next_proj["messages"][-1]
            if last.get("role") == "assistant" and (
                not message_id or last.get("id") == message_id
            ):
                last["content"] = f"{last.get('content', '')}{delta}"
        return next_proj

    if event_type == "tool_use_start":
        tool = payload.get("tool")
        if isinstance(tool, dict):
            next_proj["tool_calls"].append(tool)
        else:
            next_proj["tool_calls"].append({
                "name": payload.get("tool_name", ""),
                "call_id": payload.get("call_id", ""),
                "input": payload.get("input"),
                "status": "running",
            })
        return next_proj

    if event_type == "tool_use_end":
        call_id = payload.get("call_id")
        for tc in reversed(next_proj["tool_calls"]):
            if call_id and tc.get("call_id") != call_id:
                continue
            if not call_id and tc.get("status") != "running":
                continue
            tc["status"] = "completed"
            tc["output"] = payload.get("output", "")
            break
        return next_proj

    if event_type == "thinking":
        meta = next_proj["meta"]
        meta["last_thinking"] = payload.get("content", "")
        return next_proj

    if event_type == "artifact_created":
        artifact = payload.get("artifact")
        if isinstance(artifact, dict):
            next_proj["artifacts"].append(artifact)
        return next_proj

    if event_type == "approval_requested":
        next_proj["meta"]["pending_approval"] = payload
        return next_proj

    if event_type == "approval_resolved":
        next_proj["meta"].pop("pending_approval", None)
        return next_proj

    if event_type == "error":
        next_proj["meta"]["error"] = payload.get("message", "")
        return next_proj

    if event_type == "execution_completed":
        next_proj["meta"]["completed"] = True
        if "result_summary" in payload:
            next_proj["meta"]["result_summary"] = payload["result_summary"]
        return next_proj

    if event_type == "heartbeat":
        return next_proj

    return next_proj
