"""Command types and dispatch for chat WebSocket frames."""

from __future__ import annotations

import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any, Mapping

from app.websocket.chat_protocol import ParsedChatExtension, ParsedChatStartFrame


@dataclass(frozen=True)
class StandardChatTurnCommand:
    """Command representing a normal user chat message."""

    request_id: str
    message: str
    thread_id: str | None
    graph_id: uuid_lib.UUID | None
    model: str | None
    metadata: dict[str, Any]
    files: list[dict[str, Any]]


@dataclass(frozen=True)
class SkillCreatorTurnCommand(StandardChatTurnCommand):
    """Command for a Skill Creator turn, extending the standard command."""

    run_id: str | None
    edit_skill_id: str | None


@dataclass(frozen=True)
class ChatRunTurnCommand(StandardChatTurnCommand):
    """Command for a Chat run turn, extending the standard command."""

    run_id: str | None = None


ChatTurnCommand = StandardChatTurnCommand | SkillCreatorTurnCommand | ChatRunTurnCommand


def build_command_from_parsed_frame(frame: ParsedChatStartFrame) -> ChatTurnCommand:
    """Convert a validated ParsedChatStartFrame into a ChatTurnCommand."""
    metadata, files = _sanitize_metadata_files(frame.metadata, frame.input.files)
    model = frame.input.model

    extension = frame.extension
    if extension is None:
        return StandardChatTurnCommand(
            request_id=frame.request_id,
            message=frame.input.message,
            thread_id=frame.thread_id,
            graph_id=frame.graph_id,
            model=model,
            metadata=metadata,
            files=files,
        )

    if isinstance(extension, ParsedChatExtension):
        return ChatRunTurnCommand(
            request_id=frame.request_id,
            message=frame.input.message,
            thread_id=frame.thread_id,
            graph_id=frame.graph_id,
            model=model,
            metadata=metadata,
            files=files,
            run_id=extension.run_id,
        )

    # skill_creator path
    if extension.edit_skill_id:
        metadata["edit_skill_id"] = extension.edit_skill_id

    return SkillCreatorTurnCommand(
        request_id=frame.request_id,
        message=frame.input.message,
        thread_id=frame.thread_id,
        graph_id=frame.graph_id,
        model=model,
        metadata=metadata,
        files=files,
        run_id=extension.run_id,
        edit_skill_id=extension.edit_skill_id,
    )


def _normalize_files(files: list[Any]) -> list[dict[str, Any]]:
    return [f for f in files if isinstance(f, dict)]


def _sanitize_metadata_files(
    metadata: Mapping[str, Any], raw_files: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sanitized = dict(metadata)
    sanitized.pop("files", None)

    files = _normalize_files(raw_files if isinstance(raw_files, list) else [])
    if files:
        sanitized["files"] = files

    return sanitized, files
