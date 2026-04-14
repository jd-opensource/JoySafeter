"""Chat WebSocket protocol: frame parsing, validation, and message types."""

from __future__ import annotations

import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any, Literal

RESERVED_METADATA_KEYS = {"mode", "run_id", "edit_skill_id", "extension", "kind", "files"}
ALLOWED_CLIENT_FRAME_TYPES = {
    "ping",
    "chat.start",
    "chat.resume",
    "chat.stop",
}


class ChatProtocolError(Exception):
    """Raised when a client frame violates the chat protocol."""

    def __init__(self, message: str, request_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id


@dataclass(frozen=True)
class ParsedChatInput:
    """Validated user input extracted from a chat.start frame."""

    message: str
    files: list[dict[str, Any]]
    provider_name: str | None
    model_name: str | None


@dataclass(frozen=True)
class ParsedSkillCreatorExtension:
    """Extension payload for Skill Creator turns."""

    kind: Literal["skill_creator"]
    run_id: str | None
    edit_skill_id: str | None


@dataclass(frozen=True)
class ParsedChatExtension:
    """Extension payload for Chat run turns."""

    kind: Literal["chat"]
    run_id: str | None


@dataclass(frozen=True)
class ParsedCopilotExtension:
    """Extension payload for Copilot turns."""

    kind: Literal["copilot"]
    run_id: str | None
    graph_context: dict[str, Any]
    conversation_history: list[dict[str, Any]]
    mode: str


@dataclass(frozen=True)
class ParsedChatStartFrame:
    """Fully validated chat.start frame ready for command construction."""

    request_id: str
    thread_id: str | None
    graph_id: uuid_lib.UUID | None
    input: ParsedChatInput
    extension: ParsedSkillCreatorExtension | ParsedChatExtension | ParsedCopilotExtension | None
    metadata: dict[str, Any]


def parse_client_frame(frame: dict[str, Any]) -> ParsedChatStartFrame | dict[str, Any]:
    """Parse and validate a raw client JSON frame.

    Returns:
        A ParsedChatStartFrame for chat.start frames, or the raw dict
        for other recognized frame types (ping, resume, stop).

    Raises:
        ChatProtocolError: If the frame type is unknown or invalid.
    """
    frame_type = str(frame.get("type") or "")
    if frame_type not in ALLOWED_CLIENT_FRAME_TYPES:
        raise ChatProtocolError(f"unknown frame type: {frame_type or '<missing>'}")
    if frame_type == "chat.start":
        return _parse_chat_start_frame(frame)
    return frame


def _parse_chat_start_frame(frame: dict[str, Any]) -> ParsedChatStartFrame:
    request_id = _coerce_request_id(frame.get("request_id"))
    if not request_id:
        raise ChatProtocolError("chat.start frame must include request_id")

    metadata_raw = frame.get("metadata")
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
    reserved = RESERVED_METADATA_KEYS.intersection(metadata.keys())
    if reserved:
        raise ChatProtocolError(
            "reserved metadata keys are not allowed",
            request_id=request_id,
        )

    input_payload = frame.get("input")
    if not isinstance(input_payload, dict):
        raise ChatProtocolError("chat.start frame must include an input object", request_id=request_id)

    message = str(input_payload.get("message") or "")
    files_raw = input_payload.get("files")
    files = [f for f in files_raw if isinstance(f, dict)] if isinstance(files_raw, list) else []
    provider_name_raw = input_payload.get("provider_name")
    provider_name = str(provider_name_raw).strip() if provider_name_raw else None
    model_name_raw = input_payload.get("model_name")
    model_name = str(model_name_raw).strip() if model_name_raw else None

    extension = _parse_extension(frame.get("extension"), request_id)

    thread_id = _coerce_request_id(frame.get("thread_id"))
    graph_id = _coerce_optional_uuid(frame.get("graph_id"), request_id=request_id, field_name="graph_id")

    return ParsedChatStartFrame(
        request_id=request_id,
        thread_id=thread_id,
        graph_id=graph_id,
        input=ParsedChatInput(message=message, files=files, provider_name=provider_name, model_name=model_name),
        extension=extension,
        metadata=metadata,
    )


def _parse_extension(
    raw_extension: Any, request_id: str
) -> ParsedSkillCreatorExtension | ParsedChatExtension | ParsedCopilotExtension | None:
    if raw_extension is None:
        return None
    if not isinstance(raw_extension, dict):
        raise ChatProtocolError("extension must be an object", request_id=request_id)

    kind = raw_extension.get("kind")
    run_id = _coerce_request_id(raw_extension.get("run_id"))

    if kind == "skill_creator":
        edit_skill_id = _coerce_request_id(raw_extension.get("edit_skill_id"))
        return ParsedSkillCreatorExtension(kind="skill_creator", run_id=run_id, edit_skill_id=edit_skill_id)

    if kind == "chat":
        return ParsedChatExtension(kind="chat", run_id=run_id)

    if kind == "copilot":
        graph_context = raw_extension.get("graph_context")
        if not isinstance(graph_context, dict):
            raise ChatProtocolError("copilot extension requires graph_context object", request_id=request_id)
        conversation_history_raw = raw_extension.get("conversation_history")
        conversation_history = (
            [item for item in conversation_history_raw if isinstance(item, dict)]
            if isinstance(conversation_history_raw, list)
            else []
        )
        mode = str(raw_extension.get("mode") or "deepagents")
        return ParsedCopilotExtension(
            kind="copilot",
            run_id=run_id,
            graph_context=graph_context,
            conversation_history=conversation_history,
            mode=mode,
        )

    raise ChatProtocolError(
        f"unsupported extension kind: {kind or '<missing>'}",
        request_id=request_id,
    )


def _coerce_request_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_optional_uuid(value: Any, *, request_id: str, field_name: str) -> uuid_lib.UUID | None:
    text = _coerce_request_id(value)
    if text is None:
        return None

    try:
        return uuid_lib.UUID(text)
    except (ValueError, TypeError) as exc:
        raise ChatProtocolError(
            f"chat.start frame {field_name} must be a valid UUID",
            request_id=request_id,
        ) from exc
