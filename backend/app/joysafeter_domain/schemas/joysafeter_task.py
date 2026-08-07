"""
Pydantic schemas for the JoySafeter Task API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.joysafeter_shared.ids import AgentId, SandboxId, SessionId, TaskId

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
    chat_session_id: Optional[SessionId] = None
    environment_ref: Optional[str] = None
    timeout_sec: int = Field(default=7200, ge=1)
    max_retries: int = Field(default=2, ge=0)

    model_config = ConfigDict(extra="forbid")


class JoySafeterCreateTaskResponse(BaseModel):
    id: TaskId
    status: str


class JoySafeterTaskResponse(BaseModel):
    id: TaskId
    agent_id: AgentId
    chat_session_id: Optional[SessionId] = None
    status: str
    prompt: str
    system: Optional[str] = Field(default=None, validation_alias="system_prompt")
    sandbox_id: Optional[SandboxId] = None
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
