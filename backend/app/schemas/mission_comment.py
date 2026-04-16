"""
Pydantic schemas for Mission Comments.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateMissionCommentRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    parent_comment_id: Optional[uuid.UUID] = None


class UpdateMissionCommentRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class MissionCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mission_id: uuid.UUID
    workspace_id: uuid.UUID
    author_type: str
    author_id: str
    content: str
    type: str
    parent_comment_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class MissionCommentListResponse(BaseModel):
    items: list[MissionCommentResponse]
    has_more: bool = False
    next_cursor: Optional[str] = None
