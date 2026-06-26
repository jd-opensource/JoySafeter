"""Map Claude CLI NDJSON events to joysafeter session event types.

Ported from joysafeter-kernel/src/grpc.rs `harness_event_to_session_event`.
"""
from typing import Any, Optional


def map_harness_event(
    event: dict[str, Any],
    custom_tool_names: set[str],
    mcp_server_names: set[str],
    event_is_control_request: bool = False,
) -> list[tuple[str, dict[str, Any]]]:
    """Map a single Claude CLI NDJSON event to zero or more session events.

    Returns a list of (event_type, payload) tuples. Empty list means the event
    is suppressed (e.g. log events).
    """
    event_type = event.get("type", "")
    results: list[tuple[str, dict]] = []

    if event_type == "assistant":
        message = event.get("message", {})
        content_blocks = message.get("content", [])
        for block in content_blocks:
            mapped = _map_content_block(
                block, custom_tool_names, mcp_server_names,
                is_control_request=event_is_control_request,
            )
            if mapped is not None:
                results.append(mapped)

    elif event_type == "control_request":
        request = event.get("request", {})
        subtype = request.get("subtype", "")
        if subtype == "can_use_tool":
            block = {
                "type": "tool_use",
                "name": request.get("tool_name", ""),
                "input": request.get("tool_input", {}),
                "request_id": event.get("request_id", ""),
                "is_control_request": True,
            }
            mapped = _map_content_block(
                block, custom_tool_names, mcp_server_names,
                is_control_request=True,
            )
            if mapped:
                results.append(mapped)
        else:
            results.append(("control_request", event))

    elif event_type == "error":
        error_msg = event.get("error", {})
        if isinstance(error_msg, str):
            error_msg = {"type": "unknown_error", "message": error_msg}
        # Ensure retry_status is always present (matches Rust behaviour)
        if "retry_status" not in error_msg:
            error_msg["retry_status"] = {"type": "terminal"}
        results.append(("session.error", {"error": error_msg}))

    elif event_type == "system":
        subtype = event.get("subtype", event.get("status", ""))
        if subtype in ("running",):
            results.append(("session.status_running", {}))
        elif subtype in ("idle", "completed"):
            results.append(("session.status_idle", {"stop_reason": {"type": "end_turn"}}))
        elif subtype in ("rescheduling", "rescheduled"):
            results.append(("session.status_rescheduling", {}))
        elif subtype in ("terminated", "failed"):
            results.append(("session.status_terminated", {}))
        else:
            results.append(("session.status_idle", {"stop_reason": {"type": "end_turn"}}))

    elif event_type == "model_request_start":
        results.append((
            "span.model_request_start",
            {"model": event.get("model", "")},
        ))

    elif event_type == "model_request_end":
        results.append((
            "span.model_request_end",
            {
                "model": event.get("model", ""),
                "usage": {
                    "input_tokens": event.get("input_tokens", 0),
                    "output_tokens": event.get("output_tokens", 0),
                    "cache_read_input_tokens": event.get("cache_read_tokens", 0),
                    "cache_creation_input_tokens": event.get("cache_write_tokens", 0),
                },
            },
        ))

    elif event_type == "log":
        pass

    elif event_type == "task_notification":
        # Background sub-agent lifecycle (claude-code Task tool, run_in_background=true).
        # phase = "started" | "progress" | "completed" | "failed" | "stopped"
        phase = event.get("phase", "")
        if phase == "started":
            event_name = "agent.bg_task_started"
        elif phase == "progress":
            event_name = "agent.bg_task_progress"
        else:
            # completed / failed / stopped
            event_name = "agent.bg_task_finished"
        payload = {k: v for k, v in event.items() if k != "type"}
        results.append((event_name, payload))

    else:
        results.append((event_type, event))

    return results


def _map_content_block(
    block: dict[str, Any],
    custom_tool_names: set[str],
    mcp_server_names: set[str],
    is_control_request: bool = False,
) -> Optional[tuple[str, dict[str, Any]]]:
    block_type = block.get("type", "")

    if block_type == "text":
        return ("agent.message", {"content": [block]})

    if block_type == "thinking":
        return ("agent.thinking", {})

    if block_type == "tool_use":
        tool_name = block.get("name", "")
        call_id = block.get("id", block.get("request_id", ""))

        # Build payload to match Rust: {"name": tool, "input": input, "_call_id": call_id}
        payload: dict[str, Any] = {
            "name": tool_name,
            "input": block.get("input", {}),
            "_call_id": call_id,
        }
        if is_control_request or block.get("is_control_request"):
            payload["is_control_request"] = True

        if tool_name in custom_tool_names:
            return ("agent.custom_tool_use", payload)
        if tool_name in mcp_server_names:
            # Rust: mcp_server_names.contains(tool) — direct name match
            payload["mcp_server_name"] = tool_name
            return ("agent.mcp_tool_use", payload)
        return ("agent.tool_use", payload)

    if block_type == "tool_result":
        tool_name = block.get("tool_name", block.get("name", ""))
        if tool_name in custom_tool_names:
            return None
        content = block.get("content", block.get("output", ""))
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        payload = {
            "tool_use_id": block.get("tool_use_id", block.get("call_id", "")),
            "content": content,
            "is_error": False,
        }
        # Rust: mcp_server_names.contains(tool) — direct name match
        if tool_name in mcp_server_names:
            return ("agent.mcp_tool_result", payload)
        return ("agent.tool_result", payload)

    return None


def _is_mcp_tool(tool_name: str, mcp_server_names: set[str]) -> bool:
    """Legacy helper kept for backwards-compat callers outside this module.

    The canonical check (matching Rust) is a direct ``tool_name in mcp_server_names``
    membership test.  This prefix-based heuristic is retained only for external
    consumers that may rely on it.
    """
    if not tool_name.startswith("mcp__"):
        return False
    parts = tool_name.split("__", 2)
    if len(parts) >= 2:
        return parts[1] in mcp_server_names
    return True


def is_control_request(block: dict[str, Any]) -> bool:
    return block.get("is_control_request", False)
