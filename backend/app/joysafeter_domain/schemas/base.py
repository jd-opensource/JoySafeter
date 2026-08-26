"""
Common schemas
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

ItemT = TypeVar("ItemT")
CursorIdT = TypeVar("CursorIdT")


class CursorPaginatedResponse(BaseModel, Generic[ItemT, CursorIdT]):
    """Cursor-based paginated response (used by JoySafeter APIs)."""

    data: list[ItemT]
    has_more: bool
    first_id: CursorIdT | None = None
    last_id: CursorIdT | None = None
