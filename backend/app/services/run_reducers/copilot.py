"""
Copilot run projection reducer.

Each copilot turn is tracked as a single run projection containing
streaming content, thought steps, tool calls/results, and final
result message + graph actions.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_INITIAL: dict[str, Any] = {
    "version": 1,
    "run_type": "copilot_turn",
    "status": "queued",
    "stage": None,
    "content": "",
    "thought_steps": [],
    "tool_calls": [],
    "tool_results": [],
    "result_message": None,
    "result_actions": [],
    "error": None,
    "graph_id": None,
    "mode": None,
}


def _deepcopy_projection(projection: dict[str, Any] | None) -> dict[str, Any]:
    if projection is not None:
        return deepcopy(projection)
    return deepcopy(_INITIAL)


def make_initial_projection(payload: dict[str, Any], status: str) -> dict[str, Any]:
    projection = _deepcopy_projection(None)
    projection["status"] = status
    projection["graph_id"] = payload.get("graph_id")
    projection["mode"] = payload.get("mode")
    return projection


def apply_copilot_event(
    projection: dict[str, Any] | None,
    *,
    event_type: str,
    payload: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    next_p = _deepcopy_projection(projection)
    next_p["status"] = status

    if event_type == "run_initialized":
        return make_initial_projection(
            {"graph_id": payload.get("graph_id"), "mode": payload.get("mode")},
            status,
        )

    if event_type == "status":
        next_p["stage"] = payload.get("stage")
        return next_p

    if event_type == "content_delta":
        next_p["content"] += payload.get("delta", "")
        return next_p

    if event_type == "thought_step":
        step = payload.get("step")
        if step:
            next_p["thought_steps"].append(step)
        return next_p

    if event_type == "tool_call":
        next_p["tool_calls"].append(
            {
                "tool": payload.get("tool", ""),
                "input": payload.get("input", {}),
            }
        )
        return next_p

    if event_type == "tool_result":
        action = payload.get("action")
        if action:
            next_p["tool_results"].append(action)
        return next_p

    if event_type == "result":
        next_p["result_message"] = payload.get("message", "")
        next_p["result_actions"] = payload.get("actions", [])
        return next_p

    if event_type == "error":
        next_p["status"] = "failed"
        next_p["error"] = payload.get("message")
        return next_p

    if event_type == "done":
        if next_p["status"] != "failed":
            next_p["status"] = "completed"
        return next_p

    return next_p
