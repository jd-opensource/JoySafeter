"""
Pydantic schemas for AgentRun API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.core.contracts.execution import RunPurposeLiteral, TriggerMediumLiteral


class CreateAgentRunRequest(BaseModel):
    release_id: uuid.UUID
    thread_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    trigger_medium: TriggerMediumLiteral
    run_purpose: RunPurposeLiteral
    goal: Optional[str] = None
    input_payload: Optional[dict] = None


class CreateDraftAgentRunRequest(BaseModel):
    agent_id: uuid.UUID
    version_id: uuid.UUID
    workspace_id: uuid.UUID
    thread_id: Optional[uuid.UUID] = None
    goal: Optional[str] = None
    input_payload: Optional[dict] = None


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    release_id: Optional[uuid.UUID]
    agent_version_id: Optional[uuid.UUID] = None
    workspace_id: uuid.UUID
    thread_id: Optional[uuid.UUID]
    task_id: Optional[uuid.UUID]
    trigger_medium: str
    run_purpose: str
    goal: Optional[str]
    input_payload: Optional[dict]
    status: str
    current_execution_id: Optional[uuid.UUID]
    result_summary: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    created_by: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
