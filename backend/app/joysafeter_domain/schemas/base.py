"""
Common schemas
"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """Cursor-based paginated response (used by JoySafeter APIs)."""

    data: list[T]
    has_more: bool
    first_id: Optional[str] = None
    last_id: Optional[str] = None
