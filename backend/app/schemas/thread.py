"""
Pydantic schemas for Thread and ThreadMessage API.
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
MessageRoleLiteral = Literal["user", "assistant", "system", "tool"]

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateThreadRequest(BaseModel):
    agent_id: uuid.UUID
    title: Optional[str] = Field(None, max_length=500)


class UpdateThreadRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    status: Optional[ThreadStatusLiteral] = None


class CreateMessageRequest(BaseModel):
    role: MessageRoleLiteral
    content: Dict[str, Any]


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


class MessageResponse(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    run_id: Optional[uuid.UUID] = None
    execution_id: Optional[uuid.UUID] = None
    role: str
    content: Dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class ThreadDetailResponse(ThreadResponse):
    messages: List[MessageResponse] = []

    model_config = {"from_attributes": True}
