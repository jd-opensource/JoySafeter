"""
Pydantic schemas for Mission, AgentProfile, and Execution APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Mission
# ---------------------------------------------------------------------------

class CreateMissionRequest(BaseModel):
    workspace_id: uuid.UUID
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    objective: Optional[str] = None
    priority: str = "none"
    parent_mission_id: Optional[uuid.UUID] = None
    tags: Optional[list[str]] = None
    position: float = 0.0


class UpdateMissionRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    objective: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assignee_type: Optional[str] = None
    assignee_id: Optional[uuid.UUID] = None
    parent_mission_id: Optional[uuid.UUID] = None
    due_date: Optional[datetime] = None
    position: Optional[float] = None
    tags: Optional[list[str]] = None


class AssignMissionRequest(BaseModel):
    agent_profile_id: uuid.UUID


class DispatchMissionRequest(BaseModel):
    runtime_config: Optional[dict[str, Any]] = None


class MissionSummary(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    status: str
    priority: str
    assignee_type: Optional[str] = None
    assignee_id: Optional[uuid.UUID] = None
    creator_id: str
    current_execution_id: Optional[uuid.UUID] = None
    parent_mission_id: Optional[uuid.UUID] = None
    tags: Optional[list[str]] = None
    position: float
    created_at: datetime
    updated_at: datetime


class MissionListResponse(BaseModel):
    items: list[MissionSummary]


# ---------------------------------------------------------------------------
# AgentProfile
# ---------------------------------------------------------------------------

class CreateAgentProfileRequest(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(..., max_length=255)
    runtime_type: str = Field(..., max_length=50)
    description: Optional[str] = None
    avatar: Optional[str] = None
    instructions: Optional[str] = None
    skill_ids: Optional[list[str]] = None
    custom_env: Optional[dict[str, Any]] = None
    runtime_config: Optional[dict[str, Any]] = None
    max_concurrent_tasks: int = 1


class UpdateAgentProfileRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    avatar: Optional[str] = None
    instructions: Optional[str] = None
    skill_ids: Optional[list[str]] = None
    custom_env: Optional[dict[str, Any]] = None
    runtime_config: Optional[dict[str, Any]] = None
    max_concurrent_tasks: Optional[int] = None
    runtime_type: Optional[str] = None
    visibility: Optional[str] = None


class AgentProfileSummary(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    runtime_type: str
    status: str
    description: Optional[str] = None
    avatar: Optional[str] = None
    max_concurrent_tasks: int
    created_at: datetime
    updated_at: datetime


class AgentProfileListResponse(BaseModel):
    items: list[AgentProfileSummary]


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
