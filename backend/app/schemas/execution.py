"""
Pydantic schemas for Mission and Execution APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Mission
# ---------------------------------------------------------------------------

MissionStatusLiteral = Literal["backlog", "todo", "in_progress", "in_review", "done", "cancelled"]
MissionPriorityLiteral = Literal["none", "low", "medium", "high", "urgent"]


class CreateMissionRequest(BaseModel):
    workspace_id: uuid.UUID
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    objective: Optional[str] = None
    priority: MissionPriorityLiteral = "none"
    parent_mission_id: Optional[uuid.UUID] = None
    tags: Optional[list[str]] = None
    position: float = 0.0
    auto_approve: bool = False


class UpdateMissionRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    objective: Optional[str] = None
    priority: Optional[MissionPriorityLiteral] = None
    status: Optional[MissionStatusLiteral] = None
    assignee_type: Optional[str] = None
    assignee_id: Optional[uuid.UUID] = None
    parent_mission_id: Optional[uuid.UUID] = None
    due_date: Optional[datetime] = None
    position: Optional[float] = None
    tags: Optional[list[str]] = None
    auto_approve: Optional[bool] = None


class AssignMissionRequest(BaseModel):
    agent_profile_id: uuid.UUID


class DispatchMissionRequest(BaseModel):
    runtime_config: Optional[dict[str, Any]] = None


class MissionSummary(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    description: Optional[str] = None
    objective: Optional[str] = None
    status: str
    priority: str
    assignee_type: Optional[str] = None
    assignee_id: Optional[uuid.UUID] = None
    creator_id: str
    current_execution_id: Optional[uuid.UUID] = None
    parent_mission_id: Optional[uuid.UUID] = None
    tags: Optional[list[str]] = None
    position: float
    auto_approve: bool = False
    due_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MissionListResponse(BaseModel):
    items: list[MissionSummary]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class ExecutionSummary(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: str
    source: str
    status: str
    title: Optional[str] = None
    mission_id: Optional[uuid.UUID] = None
    agent_profile_id: Optional[uuid.UUID] = None
    runtime_type: str
    container_id: Optional[str] = None
    session_id: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_seq: int
    result_summary: Optional[dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ExecutionListResponse(BaseModel):
    items: list[ExecutionSummary]


class ExecutionSnapshotResponse(BaseModel):
    execution_id: uuid.UUID
    status: str
    last_seq: int
    projection: dict[str, Any]


class ExecutionEventResponse(BaseModel):
    seq: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class ExecutionEventsPageResponse(BaseModel):
    execution_id: uuid.UUID
    events: list[ExecutionEventResponse]
    next_after_seq: int


# ---------------------------------------------------------------------------
# Intervention / Approval
# ---------------------------------------------------------------------------


class InjectMessageRequest(BaseModel):
    message: str


class ApproveActionRequest(BaseModel):
    approved: bool
    message: str | None = None
