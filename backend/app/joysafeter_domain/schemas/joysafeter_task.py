"""
Pydantic schemas for the JoySafeter Task API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.joysafeter_shared.ids import AgentId
from app.joysafeter_shared.utils.id_utils import (
    format_sandbox_id,
    format_session_id,
    format_task_id,
)

# Coarse per-field safety bound for free-text prompt content. Sits far below the
# request body-size cap (64 MiB) so a single field cannot bloat a DB row or the
# Redis SSE fan-out, yet generous enough (~250k tokens) never to hit a
# legitimate prompt. Tunable if real workloads need more.
MAX_PROMPT_CHARS = 1_000_000


class JoySafeterCreateTaskRequest(BaseModel):
    agent_id: Optional[AgentId] = None
    agent_name: Optional[str] = None
    prompt: str = Field(max_length=MAX_PROMPT_CHARS)
    system: Optional[str] = Field(default=None, max_length=MAX_PROMPT_CHARS)
    chat_session_id: Optional[uuid.UUID] = None
    environment_ref: Optional[str] = None
    timeout_sec: int = Field(default=7200, ge=1)
    max_retries: int = Field(default=2, ge=0)

    model_config = ConfigDict(extra="forbid")


class JoySafeterCreateTaskResponse(BaseModel):
    id: uuid.UUID
    status: str

    @field_serializer("id")
    def serialize_id(self, value: uuid.UUID) -> str:
        return format_task_id(value)


class JoySafeterTaskResponse(BaseModel):
    id: uuid.UUID
    agent_id: AgentId
    chat_session_id: Optional[uuid.UUID] = None
    status: str
    prompt: str
    system: Optional[str] = Field(default=None, validation_alias="system_prompt")
    sandbox_id: Optional[uuid.UUID] = None
    output: str = ""
    error: Optional[str] = None
    usage: Optional[dict] = None
    timeout_sec: int
    retry_count: int
    max_retries: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, value: uuid.UUID) -> str:
        return format_task_id(value)

    @field_serializer("chat_session_id")
    def serialize_session_id(self, value: Optional[uuid.UUID]) -> Optional[str]:
        return format_session_id(value) if value is not None else None

    @field_serializer("sandbox_id")
    def serialize_sandbox_id(self, value: Optional[uuid.UUID]) -> Optional[str]:
        return format_sandbox_id(value) if value is not None else None
