from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.websocket.chat_protocol import ParsedChatStartFrame


@dataclass(frozen=True)
class StandardChatTurnCommand:
    request_id: str
    message: str
    thread_id: str | None
    graph_id: str | None
    metadata: dict[str, Any]
    files: list[dict[str, Any]]


@dataclass(frozen=True)
class SkillCreatorTurnCommand(StandardChatTurnCommand):
    run_id: str | None
    edit_skill_id: str | None


ChatTurnCommand = StandardChatTurnCommand | SkillCreatorTurnCommand


def build_command_from_parsed_frame(frame: ParsedChatStartFrame) -> ChatTurnCommand:
    metadata = dict(frame.metadata)
    files = _normalize_files(frame.input.files)
    if files:
        metadata["files"] = files

    extension = frame.extension
    if extension is None:
        return StandardChatTurnCommand(
            request_id=frame.request_id,
            message=frame.input.message,
            thread_id=frame.thread_id,
            graph_id=frame.graph_id,
            metadata=metadata,
            files=files,
        )

    if extension.edit_skill_id:
        metadata["edit_skill_id"] = extension.edit_skill_id

    return SkillCreatorTurnCommand(
        request_id=frame.request_id,
        message=frame.input.message,
        thread_id=frame.thread_id,
        graph_id=frame.graph_id,
        metadata=metadata,
        files=files,
        run_id=extension.run_id,
        edit_skill_id=extension.edit_skill_id,
    )


def build_command_from_legacy_frame(frame: Mapping[str, Any]) -> ChatTurnCommand:
    request_id = str(frame.get("request_id") or "")
    message = str(frame.get("message") or "")
    thread_id = _coerce_str(frame.get("thread_id"))
    graph_id = _coerce_str(frame.get("graph_id"))
    raw_metadata = frame.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}

    mode = _coerce_str(metadata.get("mode"))
    run_id = _coerce_str(metadata.get("run_id"))
    edit_skill_id = _coerce_str(metadata.get("edit_skill_id"))

    files_value = metadata.get("files")
    files = _normalize_files(files_value if isinstance(files_value, list) else [])
    if files:
        metadata["files"] = files

    if mode == "skill_creator":
        return SkillCreatorTurnCommand(
            request_id=request_id,
            message=message,
            thread_id=thread_id,
            graph_id=graph_id,
            metadata=metadata,
            files=files,
            run_id=run_id,
            edit_skill_id=edit_skill_id,
        )

    return StandardChatTurnCommand(
        request_id=request_id,
        message=message,
        thread_id=thread_id,
        graph_id=graph_id,
        metadata=metadata,
        files=files,
    )


def _normalize_files(files: list[Any]) -> list[dict[str, Any]]:
    return [f for f in files if isinstance(f, dict)]


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
