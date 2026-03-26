"""
Skill Creator run projection reducer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _deepcopy_projection(projection: dict[str, Any] | None) -> dict[str, Any]:
    if projection is not None:
        return deepcopy(projection)
    return {
        "version": 1,
        "run_type": "skill_creator",
        "status": "queued",
        "graph_id": None,
        "thread_id": None,
        "edit_skill_id": None,
        "messages": [],
        "current_assistant_message_id": None,
        "preview_data": None,
        "file_tree": {},
        "interrupt": None,
        "meta": {},
    }


def make_initial_projection(payload: dict[str, Any], status: str) -> dict[str, Any]:
    projection = _deepcopy_projection(None)
    projection["status"] = status
    projection["graph_id"] = payload.get("graph_id")
    projection["thread_id"] = payload.get("thread_id")
    projection["edit_skill_id"] = payload.get("edit_skill_id")
    return projection


def apply_skill_creator_event(
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
                "edit_skill_id": payload.get("edit_skill_id"),
            },
            status,
        )

    if event_type == "user_message_added":
        message = payload.get("message")
        if isinstance(message, dict):
            next_projection["messages"].append(message)
        return next_projection

    if event_type == "assistant_message_started":
        message = payload.get("message")
        if isinstance(message, dict):
            next_projection["messages"].append(message)
            next_projection["current_assistant_message_id"] = message.get("id")
        return next_projection

    if event_type == "content_delta":
        message_id = payload.get("message_id")
        delta = payload.get("delta") or ""
        if not message_id or not delta:
            return next_projection
        for message in next_projection["messages"]:
            if message.get("id") == message_id:
                message["content"] = f"{message.get('content', '')}{delta}"
                break
        return next_projection

    if event_type == "tool_start":
        message_id = payload.get("message_id")
        tool = payload.get("tool")
        if not message_id or not isinstance(tool, dict):
            return next_projection
        for message in next_projection["messages"]:
            if message.get("id") == message_id:
                tools = message.setdefault("tool_calls", [])
                tools.append(tool)
                break
        return next_projection

    if event_type == "tool_end":
        message_id = payload.get("message_id")
        tool_id = payload.get("tool_id")
        tool_output = payload.get("tool_output")
        tool_name = payload.get("tool_name")
        end_time = payload.get("end_time")
        for message in next_projection["messages"]:
            if message.get("id") != message_id:
                continue
            for tool in message.get("tool_calls", []):
                if tool_id and tool.get("id") != tool_id:
                    continue
                if not tool_id and tool.get("status") != "running":
                    continue
                tool["status"] = "completed"
                tool["result"] = tool_output
                if end_time is not None:
                    tool["endTime"] = end_time
                break
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

    if event_type == "interrupt":
        next_projection["interrupt"] = payload.get("interrupt")
        next_projection["current_assistant_message_id"] = None
        return next_projection

    if event_type == "error":
        next_projection["meta"]["error"] = payload.get("message")
        return next_projection

    if event_type == "done":
        next_projection["meta"]["completed"] = True
        next_projection["current_assistant_message_id"] = None
        return next_projection

    if event_type == "status":
        next_projection["meta"]["status_message"] = payload.get("message")
        return next_projection

    return next_projection
