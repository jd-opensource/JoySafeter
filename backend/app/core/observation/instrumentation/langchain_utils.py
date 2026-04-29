"""LangChain callback helper utilities — message conversion, usage normalization, model extraction."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage

from app.core.observation.types import ObservationType

MESSAGE_ROLE_MAP: dict[str, str | None] = {
    "HumanMessage": "user",
    "AIMessage": "assistant",
    "SystemMessage": "system",
    "ToolMessage": "tool",
    "FunctionMessage": "function",
    "ChatMessage": None,
}

USAGE_KEY_MAP: list[tuple[str, str, str | None]] = [
    ("prompt_tokens", "completion_tokens", "total_tokens"),
    ("input_tokens", "output_tokens", None),
    ("promptTokenCount", "candidatesTokenCount", "totalTokenCount"),
    ("inputTokens", "outputTokens", "totalTokens"),
]


def convert_message_to_dict(message: BaseMessage) -> dict:
    """Convert a LangChain BaseMessage to a plain dict with role/content/tool_calls."""
    role = MESSAGE_ROLE_MAP.get(type(message).__name__, "unknown")
    if role is None:
        role = getattr(message, "role", "unknown")
    result: dict[str, Any] = {"role": role, "content": message.content}
    if hasattr(message, "tool_calls") and message.tool_calls:
        result["tool_calls"] = message.tool_calls
    if hasattr(message, "tool_call_id") and message.tool_call_id:
        result["tool_call_id"] = message.tool_call_id
    if message.additional_kwargs:
        result.update(message.additional_kwargs)
    return result


def normalize_usage(raw: dict | None) -> dict[str, int]:
    """Normalize token usage across provider formats to {input, output, total}."""
    if not raw:
        return {}
    for input_key, output_key, total_key in USAGE_KEY_MAP:
        if input_key in raw:
            inp = int(raw[input_key])
            out = int(raw.get(output_key, 0))
            total = (
                int(raw[total_key]) if total_key and total_key in raw else inp + out
            )
            return {"input": inp, "output": out, "total": total}
    return {}


def extract_model_name(
    *,
    metadata: dict | None,
    serialized: dict | None,
    kwargs: dict,
    response: Any | None,
) -> str | None:
    """Multi-source model name extraction: metadata -> serialized -> invocation_params -> response."""
    if metadata and metadata.get("ls_model_name"):
        return str(metadata["ls_model_name"])

    ser_kwargs = (serialized or {}).get("kwargs", {})
    if ser_kwargs.get("model_name"):
        return str(ser_kwargs["model_name"])
    if ser_kwargs.get("model"):
        return str(ser_kwargs["model"])

    inv_params = kwargs.get("invocation_params", {})
    if inv_params.get("model_name"):
        return str(inv_params["model_name"])
    if inv_params.get("model"):
        return str(inv_params["model"])

    if response and hasattr(response, "llm_output") and response.llm_output:
        if response.llm_output.get("model_name"):
            return str(response.llm_output["model_name"])

    return None


def _classify_chain(name: str, serialized: dict) -> ObservationType:
    """Determine if a chain is actually an AGENT based on name patterns and serialized id path."""
    if name and (
        name.startswith("worker:")
        or "SubAgent" in name
        or "CompiledSubAgent" in name
    ):
        return ObservationType.AGENT
    if serialized:
        path = serialized.get("id", [])
        if any("agent" in seg.lower() for seg in path if isinstance(seg, str)):
            return ObservationType.AGENT
    return ObservationType.CHAIN
