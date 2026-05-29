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
