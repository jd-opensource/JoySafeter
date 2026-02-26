"""Request/response conversion helpers for OpenAI <-> Anthropic compatibility."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from .config import ProxySettings


class ConversionError(ValueError):
    """Raised when payload conversion fails."""


@dataclass(frozen=True)
class RequestConversionResult:
    """Converted OpenAI payload plus request metadata."""

    openai_payload: dict[str, Any]
    original_model: str
    mapped_model: str
    stream: bool


def convert_anthropic_request_to_openai(
    payload: dict[str, Any],
    settings: ProxySettings,
) -> RequestConversionResult:
    """Convert Anthropic /v1/messages request payload into OpenAI chat/completions payload."""
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ConversionError("model is required and must be a non-empty string")
    original_model = model.strip()
    mapped_model = settings.model_map.get(original_model, original_model)

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ConversionError("messages is required and must be a non-empty array")

    openai_messages: list[dict[str, Any]] = []

    system_text = _extract_system_text(payload.get("system"))
    if system_text:
        openai_messages.append({"role": "system", "content": system_text})

    for msg in messages:
        if not isinstance(msg, dict):
            raise ConversionError("each message must be an object")

        role = msg.get("role")
        if role == "user":
            openai_messages.extend(_convert_user_message(msg.get("content")))
        elif role == "assistant":
            openai_messages.append(_convert_assistant_message(msg.get("content")))
        elif role == "system":
            # Tolerate system role inside messages by converting to system message.
            system_inline = _content_to_text(msg.get("content"))
            if system_inline:
                openai_messages.append({"role": "system", "content": system_inline})
        else:
            raise ConversionError(f"unsupported message role: {role!r}")

    max_tokens = payload.get("max_tokens", settings.default_max_tokens)
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ConversionError("max_tokens must be a positive integer")

    stream = bool(payload.get("stream", False))

    openai_payload: dict[str, Any] = {
        "model": mapped_model,
        "messages": openai_messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }

    if "temperature" in payload:
        openai_payload["temperature"] = payload["temperature"]
    if "top_p" in payload:
        openai_payload["top_p"] = payload["top_p"]
    if "stop_sequences" in payload:
        stop_sequences = payload["stop_sequences"]
        if isinstance(stop_sequences, list):
            openai_payload["stop"] = stop_sequences
        elif isinstance(stop_sequences, str):
            openai_payload["stop"] = [stop_sequences]
        else:
            raise ConversionError("stop_sequences must be a string or an array of strings")

    if "tools" in payload:
        openai_payload["tools"] = _convert_tools(payload["tools"])

    if "tool_choice" in payload:
        openai_payload["tool_choice"] = _convert_tool_choice(payload["tool_choice"])

    return RequestConversionResult(
        openai_payload=openai_payload,
        original_model=original_model,
        mapped_model=mapped_model,
        stream=stream,
    )


def convert_openai_response_to_anthropic(
    response_data: dict[str, Any],
    model_name: str,
) -> dict[str, Any]:
    """Convert non-streaming OpenAI chat/completions response to Anthropic message format."""
    choice = _first_choice(response_data)
    message = choice.get("message", {}) if isinstance(choice, dict) else {}

    content_blocks: list[dict[str, Any]] = []

    content = message.get("content")
    text = _openai_content_to_text(content)
    if text:
        content_blocks.append({"type": "text", "text": text})

    for tool_call in message.get("tool_calls", []) or []:
        if not isinstance(tool_call, dict):
            continue
        function_obj = tool_call.get("function", {})
        if not isinstance(function_obj, dict):
            continue
        tool_name = function_obj.get("name") or "unknown_tool"
        arguments = _parse_json_arguments(function_obj.get("arguments"))
        content_blocks.append(
            {
                "type": "tool_use",
                "id": tool_call.get("id") or f"call_{uuid.uuid4().hex[:10]}",
                "name": tool_name,
                "input": arguments,
            }
        )

    if not content_blocks:
        content_blocks = [{"type": "text", "text": ""}]

    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None

    usage = response_data.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    return {
        "id": response_data.get("id") or f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model_name,
        "stop_reason": map_openai_finish_reason_to_anthropic(finish_reason),
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


def convert_openai_models_to_anthropic(response_data: dict[str, Any]) -> dict[str, Any]:
    """Convert OpenAI /v1/models payload to Anthropic-like model list."""
    models = response_data.get("data") if isinstance(response_data, dict) else None
    if not isinstance(models, list):
        models = []

    converted: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = model.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        item: dict[str, Any] = {
            "id": model_id,
            "type": "model",
            "display_name": model_id,
        }
        created = model.get("created")
        if created is not None:
            item["created_at"] = created
        converted.append(item)

    return {"data": converted, "has_more": False}


def map_openai_finish_reason_to_anthropic(finish_reason: Any) -> str:
    """Map OpenAI finish_reason to Anthropic stop_reason."""
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "function_call": "tool_use",
    }
    if isinstance(finish_reason, str):
        return mapping.get(finish_reason, "end_turn")
    return "end_turn"


def anthropic_error_payload(message: str, error_type: str = "api_error") -> dict[str, Any]:
    """Build Anthropic-style error payload."""
    return {
        "type": "error",
        "error": {
            "type": error_type,
            "message": message,
        },
    }


def extract_upstream_error_message(body_text: str) -> str:
    """Extract a useful error message from upstream payload text."""
    if not body_text:
        return "Upstream request failed"

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return body_text.strip() or "Upstream request failed"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    return body_text.strip() or "Upstream request failed"


def _extract_system_text(system_field: Any) -> str | None:
    if system_field is None:
        return None

    if isinstance(system_field, str):
        return system_field.strip() or None

    if isinstance(system_field, list):
        parts: list[str] = []
        for block in system_field:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"].strip()
                if text:
                    parts.append(text)
        if parts:
            return "\n\n".join(parts)

    return None


def _convert_user_message(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"role": "user", "content": content}]

    if not isinstance(content, list):
        raise ConversionError("user message content must be a string or array")

    converted: list[dict[str, Any]] = []
    pending_parts: list[dict[str, Any]] = []

    def flush_user_parts() -> None:
        if not pending_parts:
            return
        converted.append({"role": "user", "content": _normalize_openai_user_content(pending_parts.copy())})
        pending_parts.clear()

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                pending_parts.append({"type": "text", "text": text})
        elif block_type == "image":
            image_url = _anthropic_image_to_openai_url(block)
            pending_parts.append({"type": "image_url", "image_url": {"url": image_url}})
        elif block_type == "tool_result":
            tool_use_id = block.get("tool_use_id") or block.get("id")
            if not isinstance(tool_use_id, str) or not tool_use_id:
                raise ConversionError("tool_result block requires tool_use_id")
            flush_user_parts()
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_use_id,
                    "content": _tool_result_to_text(block.get("content")),
                }
            )
        else:
            # Graceful fallback for unknown blocks.
            fallback = block.get("text")
            if isinstance(fallback, str) and fallback:
                pending_parts.append({"type": "text", "text": fallback})

    flush_user_parts()
    if not converted:
        converted.append({"role": "user", "content": ""})
    return converted


def _convert_assistant_message(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"role": "assistant", "content": content}

    if not isinstance(content, list):
        raise ConversionError("assistant message content must be a string or array")

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        elif block_type == "tool_use":
            name = block.get("name")
            if not isinstance(name, str) or not name:
                raise ConversionError("tool_use block requires name")
            tool_id = block.get("id")
            if not isinstance(tool_id, str) or not tool_id:
                tool_id = f"call_{uuid.uuid4().hex[:10]}"
            input_payload = block.get("input")
            if input_payload is None:
                input_payload = {}
            arguments = json.dumps(input_payload, ensure_ascii=False)
            tool_calls.append(
                {
                    "id": tool_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": arguments,
                    },
                }
            )

    message: dict[str, Any] = {"role": "assistant"}
    if text_parts:
        message["content"] = "\n".join(text_parts)
    elif tool_calls:
        message["content"] = None
    else:
        message["content"] = ""

    if tool_calls:
        message["tool_calls"] = tool_calls

    return message


def _normalize_openai_user_content(parts: list[dict[str, Any]]) -> Any:
    if not parts:
        return ""

    if all(part.get("type") == "text" for part in parts):
        return "\n".join(str(part.get("text", "")) for part in parts)

    return parts


def _anthropic_image_to_openai_url(block: dict[str, Any]) -> str:
    source = block.get("source")
    if not isinstance(source, dict):
        raise ConversionError("image block requires source object")

    source_type = source.get("type")
    if source_type == "url":
        url = source.get("url")
        if not isinstance(url, str) or not url:
            raise ConversionError("image source url must be a non-empty string")
        return url

    if source_type == "base64":
        media_type = source.get("media_type")
        data = source.get("data")
        if not isinstance(media_type, str) or not media_type:
            raise ConversionError("base64 image source requires media_type")
        if not isinstance(data, str) or not data:
            raise ConversionError("base64 image source requires data")
        return f"data:{media_type};base64,{data}"

    raise ConversionError(f"unsupported image source type: {source_type!r}")


def _tool_result_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        segments: list[str] = []
        for item in content:
            if isinstance(item, str):
                segments.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    segments.append(text)
            else:
                segments.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(segments)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _convert_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        raise ConversionError("tools must be an array")

    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise ConversionError("each tool must be an object")
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError("tool.name is required")
        description = tool.get("description", "")
        if not isinstance(description, str):
            description = str(description)
        input_schema = tool.get("input_schema", {})
        if not isinstance(input_schema, dict):
            raise ConversionError("tool.input_schema must be an object")

        converted.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": input_schema,
                },
            }
        )

    return converted


def _convert_tool_choice(tool_choice: Any) -> Any:
    if isinstance(tool_choice, str):
        return _map_tool_choice_type(tool_choice)

    if isinstance(tool_choice, dict):
        choice_type = tool_choice.get("type")
        if choice_type == "tool":
            name = tool_choice.get("name")
            if not isinstance(name, str) or not name:
                raise ConversionError("tool_choice.type='tool' requires name")
            return {
                "type": "function",
                "function": {"name": name},
            }
        if isinstance(choice_type, str):
            return _map_tool_choice_type(choice_type)

    raise ConversionError("unsupported tool_choice format")


def _map_tool_choice_type(choice_type: str) -> str:
    normalized = choice_type.strip().lower()
    mapping = {
        "auto": "auto",
        "none": "none",
        "any": "required",
        "required": "required",
    }
    if normalized in mapping:
        return mapping[normalized]
    raise ConversionError(f"unsupported tool_choice type: {choice_type}")


def _openai_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
                elif isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            elif isinstance(part, str):
                text_parts.append(part)
        return "\n".join(text_parts)
    return ""


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "\n".join(chunks)
    return ""


def _parse_json_arguments(arguments: Any) -> Any:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, list):
        return arguments
    if isinstance(arguments, str):
        stripped = arguments.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return {"raw": stripped}
    if arguments is None:
        return {}
    return {"raw": str(arguments)}


def _first_choice(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}
