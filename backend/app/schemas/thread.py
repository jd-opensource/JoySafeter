"""
Pydantic schemas for Thread API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

ThreadStatusLiteral = Literal["active", "archived"]

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateThreadRequest(BaseModel):
    agent_id: uuid.UUID
    title: Optional[str] = Field(None, max_length=500)


class UpdateThreadRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    status: Optional[ThreadStatusLiteral] = None


class ChatAttachment(BaseModel):
    """A file attachment sent alongside a chat message."""
    filename: str = Field(..., min_length=1, max_length=255)
    storage_ref: str = Field(..., min_length=1, max_length=500, description="Sandbox path from /v1/files/upload response")
    mime_type: str = Field(..., min_length=1, max_length=100)
    size_bytes: int = Field(..., gt=0)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    attachments: Optional[List[ChatAttachment]] = Field(
        None, max_length=10, description="Up to 10 file attachments"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ThreadSummary(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    title: Optional[str] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ThreadResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    workspace_id: uuid.UUID
    title: Optional[str] = None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    run_id: uuid.UUID
    execution_id: uuid.UUID


class ThreadEventResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    execution_id: uuid.UUID
    sequence_no: int
    event_type: str
    payload: Dict[str, Any]
    execution_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ThreadEventsListResponse(BaseModel):
    events: list[ThreadEventResponse]
    total: int
