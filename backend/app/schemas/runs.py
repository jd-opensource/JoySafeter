"""
Schemas for run APIs.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateSkillCreatorRunRequest(BaseModel):
    message: str = Field(..., description="Initial user prompt")
    graph_id: uuid.UUID = Field(..., description="Skill Creator graph id")
    thread_id: Optional[str] = Field(None, description="Existing thread id")
    edit_skill_id: Optional[str] = Field(None, description="Existing skill id when editing")


class RunSummary(BaseModel):
    run_id: uuid.UUID
    status: str
    run_type: str
    source: str
    thread_id: Optional[str] = None
    graph_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    last_seq: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    last_heartbeat_at: Optional[datetime] = None
    updated_at: datetime


class CreateRunResponse(BaseModel):
    run_id: uuid.UUID
    thread_id: str
    status: str


class RunSnapshotResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    last_seq: int
    projection: dict[str, Any]


class RunEventResponse(BaseModel):
    seq: int
    event_type: str
    payload: dict[str, Any]
    trace_id: Optional[uuid.UUID] = None
    observation_id: Optional[uuid.UUID] = None
    parent_observation_id: Optional[uuid.UUID] = None
    created_at: datetime


class RunEventsPageResponse(BaseModel):
    run_id: uuid.UUID
    events: list[RunEventResponse]
    next_after_seq: int


class RunListResponse(BaseModel):
    items: list[RunSummary]
