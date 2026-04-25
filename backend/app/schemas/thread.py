"""
Pydantic schemas for Thread API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Literal, Optional

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
    mime_type: str = Field(..., min_length=1, max_length=127)
    url: str = Field(..., min_length=1, max_length=2048, description="Pre-signed or public URL")
    size_bytes: Optional[int] = Field(None, ge=0, description="File size in bytes")


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
