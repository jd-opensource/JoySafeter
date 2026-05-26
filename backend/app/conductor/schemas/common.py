import uuid
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    after_id: Optional[uuid.UUID] = None


class VersionPaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    before_version: Optional[int] = None


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    has_more: bool
    first_id: Optional[str] = None
    last_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
