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

TaskStatusLiteral = Literal["backlog", "in_progress", "done", "needs_review", "cancelled"]
TaskPriorityLiteral = Literal["none", "low", "medium", "high", "urgent"]


class CreateTaskRequest(BaseModel):
    workspace_id: uuid.UUID
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    goal: Optional[str] = None
    priority: TaskPriorityLiteral = "none"
    agent_id: Optional[uuid.UUID] = None
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
    agent_id: Optional[uuid.UUID] = None
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
# Execution (Phase 4 - new schema)
# ---------------------------------------------------------------------------


class ExecutionResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    parent_execution_id: Optional[uuid.UUID]
    attempt_index: int
    executor_kind: str
    runtime_session_ref: Optional[str]
    status: str
    error_code: Optional[str]
    error_message: Optional[str]
    metrics: Optional[dict]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecutionEventResponse(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    sequence_no: int
    event_type: str
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Intervention / Approval
# ---------------------------------------------------------------------------


class InjectMessageRequest(BaseModel):
    message: str


class ApproveActionRequest(BaseModel):
    approved: bool
    message: str | None = None
