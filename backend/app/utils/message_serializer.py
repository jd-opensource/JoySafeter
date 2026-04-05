"""
LangChain Message Serializer

Modeled after Langfuse _convert_message_to_dict().
Serialize LangChain BaseMessage objects into storable dict format.
"""

from typing import Any

from loguru import logger


def serialize_message(msg: Any) -> dict:
    """
    Convert a LangChain BaseMessage to a JSON-serializable dict.

    Modeled after Langfuse CallbackHandler._convert_message_to_dict()

    Args:
        msg: LangChain BaseMessage instance or similar object

    Returns:
        Dict in {"role": str, "content": str, ...} format
    """
    # already a dict, return directly
    if isinstance(msg, dict):
        return msg

    # extract content
    content = _extract_content(msg)

    # determine role by type
    class_name = type(msg).__name__

    if class_name == "HumanMessage" or class_name == "HumanMessageChunk":
        result: dict[str, Any] = {"role": "user", "content": content}
    elif class_name == "AIMessage" or class_name == "AIMessageChunk":
        result = {"role": "assistant", "content": content}
        # preserve tool_calls
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            result["tool_calls"] = _serialize_tool_calls(tool_calls)
        # preserve important info from additional_kwargs
        additional = getattr(msg, "additional_kwargs", None)
        if additional and isinstance(additional, dict):
            if "function_call" in additional:
                result["function_call"] = additional["function_call"]
            if "tool_calls" in additional and "tool_calls" not in result:
                result["tool_calls"] = additional["tool_calls"]
    elif class_name == "SystemMessage" or class_name == "SystemMessageChunk":
        result = {"role": "system", "content": content}
    elif class_name == "ToolMessage" or class_name == "ToolMessageChunk":
        result = {"role": "tool", "content": content}
        tool_call_id = getattr(msg, "tool_call_id", None)
        if tool_call_id:
            result["tool_call_id"] = tool_call_id
    elif class_name == "FunctionMessage" or class_name == "FunctionMessageChunk":
        result = {"role": "function", "content": content}
        name = getattr(msg, "name", None)
        if name:
            result["name"] = name
    elif class_name == "ChatMessage" or class_name == "ChatMessageChunk":
        role = getattr(msg, "role", "unknown")
        result = {"role": role, "content": content}
    else:
        # fallback: try generic extraction
        role = getattr(msg, "type", "unknown")
        result = {"role": role, "content": content}

    # preserve name (if present)
    name = getattr(msg, "name", None)
    if name and "name" not in result:
        result["name"] = name

    return result


def serialize_messages(messages: Any) -> list[dict]:
    """
    Serialize a message list. Support nested lists (LangChain sometimes passes list[list[BaseMessage]]).

    Args:
        messages: BaseMessage list or nested list

    Returns:
        Flattened list of dicts
    """
    if not messages:
        return []

    result = []
    for msg in messages:
        if isinstance(msg, list):
            # handle nested lists
            for sub_msg in msg:
                result.append(serialize_message(sub_msg))
        else:
            result.append(serialize_message(msg))
    return result


def _extract_content(msg: Any) -> Any:
    """Extract message content, handling multimodal content."""
    content = getattr(msg, "content", None)
    if content is None:
        return str(msg)

    # multimodal content may be a list (e.g. messages containing images)
    if isinstance(content, list):
        # preserve original structure but ensure serializability
        serialized: list[dict[str, Any]] = []
        for part in content:
            if isinstance(part, dict):
                serialized.append(part)
            elif isinstance(part, str):
                serialized.append({"type": "text", "text": part})
            else:
                # fallback: keep element type consistent (dict) to avoid mypy mismatch
                serialized.append({"type": "unknown", "raw": str(part)})
        return serialized

    return content


def _serialize_tool_calls(tool_calls: list) -> list[dict]:
    """Serialize a tool_calls list."""
    result = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            result.append(tc)
        elif hasattr(tc, "model_dump"):
            try:
                result.append(tc.model_dump())
            except Exception:
                result.append({"name": getattr(tc, "name", ""), "args": getattr(tc, "args", {})})
        elif hasattr(tc, "__dict__"):
            result.append({k: v for k, v in tc.__dict__.items() if not k.startswith("_")})
        else:
            # fallback: return dict to keep element type consistent
            result.append({"type": "raw", "raw": str(tc)})
    return result


def truncate_data(data: Any, max_length: int = 10000) -> Any:
    """
    Truncate data to a specified length, logging a warning.

    Args:
        data: the data to truncate
        max_length: maximum character count

    Returns:
        Truncated data
    """
    if data is None:
        return None

    serialized = str(data)
    if len(serialized) <= max_length:
        return data

    logger.warning(f"Data truncated from {len(serialized)} to {max_length} chars (type={type(data).__name__})")

    if isinstance(data, str):
        return data[:max_length] + "... [truncated]"
    elif isinstance(data, dict):
        # truncate values one by one
        result = {}
        current_len = 0
        for k, v in data.items():
            v_str = str(v)
            if current_len + len(v_str) > max_length:
                remaining = max(0, max_length - current_len)
                result[k] = v_str[:remaining] + "... [truncated]"
                break
            result[k] = v
            current_len += len(v_str)
        return result
    else:
        return serialized[:max_length] + "... [truncated]"
