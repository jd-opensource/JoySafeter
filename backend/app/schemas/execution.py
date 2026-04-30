"""
Pydantic schemas for Execution APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AppErrorPayload(BaseModel):
    code: str
    message: str
    data: dict | None = None
    source: str | None = None
    retryable: bool = False
    user_action: str | None = None
    detail: str | None = None


# ---------------------------------------------------------------------------
# Execution (Phase 4 - new schema)
# ---------------------------------------------------------------------------


class ExecutionResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    parent_execution_id: Optional[uuid.UUID]
    attempt_index: int
    engine_kind: str
    runtime_session_ref: Optional[str]
    status: str
    error: Optional[AppErrorPayload]
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


class ExecutionEventItemResponse(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    seq: int
    event_type: str
    payload: dict
    created_at: datetime


class ExecutionEventsPageResponse(BaseModel):
    execution_id: uuid.UUID
    events: list[ExecutionEventItemResponse]
    next_after_seq: int


# ---------------------------------------------------------------------------
# Intervention / Approval
# ---------------------------------------------------------------------------


class ApproveActionRequest(BaseModel):
    approved: bool
    message: str | None = None
