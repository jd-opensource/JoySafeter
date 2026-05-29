"""
Common schemas
"""

import uuid
from datetime import datetime
from typing import Generic, List, TypeVar

from pydantic import BaseModel, ConfigDict

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


# ---------------------------------------------------------------------------
# Conductor Common Schemas
# ---------------------------------------------------------------------------

from typing import Optional

from pydantic import Field


class PaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    after_id: Optional[uuid.UUID] = None


class VersionPaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    before_version: Optional[int] = None


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """Cursor-based paginated response (used by Conductor APIs)."""
    data: list[T]
    has_more: bool
    first_id: Optional[str] = None
    last_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
