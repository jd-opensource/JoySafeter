"""
Pydantic schemas for Execution APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

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
