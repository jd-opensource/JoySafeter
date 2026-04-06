"""
Chat run projection reducer.

Each chat turn is tracked as a single run projection containing one
user_message and one assistant_message (with optional tool_calls),
rather than a messages array as in skill_creator.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _deepcopy_projection(projection: dict[str, Any] | None) -> dict[str, Any]:
    if projection is not None:
        return deepcopy(projection)
    return {
        "version": 1,
        "run_type": "chat_turn",
        "status": "queued",
        "graph_id": None,
        "thread_id": None,
        "user_message": None,
        "assistant_message": None,
        "file_tree": {},
        "preview_data": None,
        "node_execution_log": [],
        "interrupt": None,
        "meta": {},
    }


def make_initial_projection(payload: dict[str, Any], status: str) -> dict[str, Any]:
    projection = _deepcopy_projection(None)
    projection["status"] = status
    projection["graph_id"] = payload.get("graph_id")
    projection["thread_id"] = payload.get("thread_id")
    return projection


def apply_chat_event(
    projection: dict[str, Any] | None,
    *,
    event_type: str,
    payload: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    next_projection = _deepcopy_projection(projection)
    next_projection["status"] = status

    if event_type == "run_initialized":
        return make_initial_projection(
            {
                "graph_id": payload.get("graph_id"),
                "thread_id": payload.get("thread_id"),
            },
            status,
        )

    if event_type == "user_message_added":
        message = payload.get("message")
        if isinstance(message, dict):
            next_projection["user_message"] = message
        return next_projection

    if event_type == "assistant_message_started":
        message = payload.get("message")
        if isinstance(message, dict):
            next_projection["assistant_message"] = message
        return next_projection

    if event_type == "content_delta":
        message_id = payload.get("message_id")
        delta = payload.get("delta") or ""
        if not message_id or not delta:
            return next_projection
        msg = next_projection["assistant_message"]
        if isinstance(msg, dict) and msg.get("id") == message_id:
            msg["content"] = f"{msg.get('content', '')}{delta}"
        return next_projection

    if event_type == "tool_start":
        message_id = payload.get("message_id")
        tool = payload.get("tool")
        if not message_id or not isinstance(tool, dict):
            return next_projection
        msg = next_projection["assistant_message"]
        if isinstance(msg, dict) and msg.get("id") == message_id:
            tools = msg.setdefault("tool_calls", [])
            tools.append(tool)
        return next_projection

    if event_type == "tool_end":
        tool_id = payload.get("tool_id")
        tool_output = payload.get("tool_output")
        tool_name = payload.get("tool_name")
        end_time = payload.get("end_time")
        if isinstance(next_projection["assistant_message"], dict):
            msg = next_projection["assistant_message"]
            for tool in msg.get("tool_calls", []):
                if tool_id and tool.get("id") != tool_id:
                    continue
                if not tool_id and tool.get("status") != "running":
                    continue
                tool["status"] = "completed"
                tool["result"] = tool_output
                if end_time is not None:
                    tool["endTime"] = end_time
                break
        if tool_name == "preview_skill" and tool_output is not None:
            next_projection["preview_data"] = tool_output
        return next_projection

    if event_type == "file_event":
        path = payload.get("path")
        action = payload.get("action")
        if not path or not action:
            return next_projection
        if action == "delete":
            next_projection["file_tree"].pop(path, None)
        else:
            next_projection["file_tree"][path] = {
                "action": action,
                "size": payload.get("size"),
                "timestamp": payload.get("timestamp"),
            }
        return next_projection

    if event_type == "node_start":
        node_id = payload.get("node_id")
        node_name = payload.get("node_name")
        start_time = payload.get("start_time")
        next_projection["node_execution_log"].append(
            {
                "node_id": node_id,
                "node_name": node_name,
                "status": "running",
                "start_time": start_time,
                "end_time": None,
            }
        )
        return next_projection

    if event_type == "node_end":
        node_name = payload.get("node_name")
        end_time = payload.get("end_time")
        for entry in reversed(next_projection["node_execution_log"]):
            if entry.get("node_name") == node_name and entry.get("status") == "running":
                entry["status"] = "completed"
                entry["end_time"] = end_time
                break
        return next_projection

    if event_type == "interrupt":
        next_projection["interrupt"] = payload.get("interrupt")
        return next_projection

    if event_type == "error":
        next_projection["meta"]["error"] = payload.get("message")
        return next_projection

    if event_type == "done":
        next_projection["meta"]["completed"] = True
        return next_projection

    if event_type == "status":
        next_projection["meta"]["status_message"] = payload.get("message")
        return next_projection

    return next_projection
