"""
Pydantic schemas for AgentRun API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

TriggerSourceLiteral = Literal[
    "task",
    "chat",
    "api",
    "scheduler",
    "comment",
    "mention",
    "copilot",
    "draft_test",
]


class CreateAgentRunRequest(BaseModel):
    release_id: uuid.UUID
    thread_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    trigger_source: TriggerSourceLiteral
    goal: Optional[str] = None
    input_payload: Optional[dict] = None


class CreateDraftAgentRunRequest(BaseModel):
    agent_id: uuid.UUID
    version_id: uuid.UUID
    workspace_id: uuid.UUID
    goal: Optional[str] = None
    input_payload: Optional[dict] = None


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    release_id: Optional[uuid.UUID]
    agent_version_id: Optional[uuid.UUID] = None
    workspace_id: uuid.UUID
    thread_id: Optional[uuid.UUID]
    task_id: Optional[uuid.UUID]
    trigger_source: str
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
