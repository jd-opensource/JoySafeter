"""
Common schemas
"""

import uuid
from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import BaseResponse

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response."""

    items: List[T]
    total: int
    page: int = 1
    page_size: int = 20
    pages: int = 1


class BaseSchema(BaseModel):
    """Base schema."""

    model_config = ConfigDict(from_attributes=True)


class TimestampSchema(BaseSchema):
    """Schema with timestamps."""

    created_at: datetime
    updated_at: datetime


class IDSchema(TimestampSchema):
    """Schema with ID."""

    id: uuid.UUID


# Session schemas
class SessionCreate(BaseModel):
    """Create session request."""

    title: Optional[str] = "New Session"
    workspace_path: Optional[str] = None


class SessionResponse(BaseResponse):
    """Session response."""

    session_id: str
    title: str
    workspace_path: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SessionMessageResponse(BaseModel):
    """Session message item (legacy sessions API)."""

    id: uuid.UUID
    session_id: str
    content: str
    role: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
