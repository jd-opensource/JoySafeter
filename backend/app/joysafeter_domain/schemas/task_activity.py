"""
Pydantic schemas for Task Activities.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateTaskActivityRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    parent_activity_id: Optional[uuid.UUID] = None


class UpdateTaskActivityRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class TaskActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    project_id: Optional[str] = None
    author_type: str
    author_id: str
    content: str
    type: str
    parent_activity_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class TaskActivityListResponse(BaseModel):
    items: list[TaskActivityResponse]
    has_more: bool = False
    next_cursor: Optional[str] = None
