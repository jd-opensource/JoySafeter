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
    metadata, files = _sanitize_metadata_files(frame.metadata, frame.input.files)

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


def _normalize_files(files: list[Any]) -> list[dict[str, Any]]:
    return [f for f in files if isinstance(f, dict)]


def _sanitize_metadata_files(metadata: Mapping[str, Any], raw_files: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sanitized = dict(metadata)
    sanitized.pop("files", None)

    files = _normalize_files(raw_files if isinstance(raw_files, list) else [])
    if files:
        sanitized["files"] = files

    return sanitized, files
