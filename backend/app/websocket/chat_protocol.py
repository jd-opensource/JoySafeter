from __future__ import annotations

import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any, Literal

RESERVED_METADATA_KEYS = {"mode", "run_id", "edit_skill_id", "extension", "kind", "files"}
ALLOWED_CLIENT_FRAME_TYPES = {
    "ping",
    "chat",
    "chat.start",
    "chat.resume",
    "chat.stop",
    "resume",
    "stop",
}


class ChatProtocolError(Exception):
    def __init__(self, message: str, request_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id


@dataclass(frozen=True)
class ParsedChatInput:
    message: str
    files: list[dict[str, Any]]
    model: str | None


@dataclass(frozen=True)
class ParsedSkillCreatorExtension:
    kind: Literal["skill_creator"]
    run_id: str | None
    edit_skill_id: str | None


@dataclass(frozen=True)
class ParsedChatStartFrame:
    request_id: str
    thread_id: str | None
    graph_id: uuid_lib.UUID | None
    input: ParsedChatInput
    extension: ParsedSkillCreatorExtension | None
    metadata: dict[str, Any]


def parse_client_frame(frame: dict[str, Any]) -> ParsedChatStartFrame | dict[str, Any]:
    frame_type = str(frame.get("type") or "")
    if frame_type not in ALLOWED_CLIENT_FRAME_TYPES:
        raise ChatProtocolError(f"unknown frame type: {frame_type or '<missing>'}")
    if frame_type == "chat":
        raise ChatProtocolError(
            "legacy metadata control fields are no longer supported",
            request_id=_coerce_request_id(frame.get("request_id")),
        )
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
    model_raw = input_payload.get("model")
    model = str(model_raw).strip() if model_raw else None

    extension = _parse_extension(frame.get("extension"), request_id)

    thread_id = _coerce_request_id(frame.get("thread_id"))
    graph_id = _coerce_optional_uuid(frame.get("graph_id"), request_id=request_id, field_name="graph_id")

    return ParsedChatStartFrame(
        request_id=request_id,
        thread_id=thread_id,
        graph_id=graph_id,
        input=ParsedChatInput(message=message, files=files, model=model),
        extension=extension,
        metadata=metadata,
    )


def _parse_extension(raw_extension: Any, request_id: str) -> ParsedSkillCreatorExtension | None:
    if raw_extension is None:
        return None
    if not isinstance(raw_extension, dict):
        raise ChatProtocolError("extension must be an object", request_id=request_id)

    kind = raw_extension.get("kind")
    if kind != "skill_creator":
        raise ChatProtocolError(
            f"unsupported extension kind: {kind or '<missing>'}",
            request_id=request_id,
        )

    run_id = _coerce_request_id(raw_extension.get("run_id"))
    edit_skill_id = _coerce_request_id(raw_extension.get("edit_skill_id"))
    return ParsedSkillCreatorExtension(kind="skill_creator", run_id=run_id, edit_skill_id=edit_skill_id)


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
