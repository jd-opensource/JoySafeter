"""
Pydantic schemas for Task and Execution APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

TaskStatusLiteral = Literal["backlog", "todo", "in_progress", "done", "in_review", "cancelled"]
TaskPriorityLiteral = Literal["none", "low", "medium", "high", "urgent"]


class CreateTaskRequest(BaseModel):
    workspace_id: uuid.UUID
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    goal: Optional[str] = None
    priority: TaskPriorityLiteral = "none"
    agent_id: uuid.UUID
    parent_task_id: Optional[uuid.UUID] = None
    tags: Optional[list[str]] = None
    position: float = 0.0
    auto_approve: bool = False


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    goal: Optional[str] = None
    priority: Optional[TaskPriorityLiteral] = None
    status: Optional[TaskStatusLiteral] = None
    agent_id: Optional[uuid.UUID] = None
    parent_task_id: Optional[uuid.UUID] = None
    due_date: Optional[datetime] = None
    position: Optional[float] = None
    tags: Optional[list[str]] = None
    auto_approve: Optional[bool] = None


class AssignTaskRequest(BaseModel):
    agent_id: uuid.UUID


class DispatchTaskRequest(BaseModel):
    runtime_config: Optional[dict[str, Any]] = None


class TaskSummary(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    description: Optional[str] = None
    goal: Optional[str] = None
    status: str
    priority: str
    agent_id: uuid.UUID
    thread_id: uuid.UUID
    creator_id: str
    latest_run_id: Optional[uuid.UUID] = None
    parent_task_id: Optional[uuid.UUID] = None
    tags: Optional[list[str]] = None
    position: float
    auto_approve: bool = False
    due_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskSummary]


# ---------------------------------------------------------------------------
# Intervention / Approval
# ---------------------------------------------------------------------------


class InjectMessageRequest(BaseModel):
    message: str


class ApproveActionRequest(BaseModel):
    approved: bool
    message: str | None = None


# ---------------------------------------------------------------------------
# Conductor Task Schemas
# ---------------------------------------------------------------------------

from pydantic import ConfigDict, field_serializer


class ConductorCreateTaskRequest(BaseModel):
    agent_id: Optional[uuid.UUID] = None
    agent_name: Optional[str] = None
    prompt: str
    system_prompt: Optional[str] = None
    chat_session_id: Optional[uuid.UUID] = None
    environment_ref: Optional[str] = None
    timeout_sec: int = Field(default=7200, ge=1)
    max_retries: int = Field(default=2, ge=0)


class ConductorCreateTaskResponse(BaseModel):
    id: uuid.UUID
    status: str


class ConductorTaskResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    chat_session_id: Optional[uuid.UUID] = None
    status: str
    prompt: str
    system_prompt: Optional[str] = None
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
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"task_{v}"


