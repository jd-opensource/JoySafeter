"""
Unified response format.
"""

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel

from app.utils.datetime import utc_now

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Unified API response format."""

    success: bool = True
    code: int = 200
    message: str = "Success"
    data: Optional[T] = None
    timestamp: str = ""

    def __init__(self, **data):
        if "timestamp" not in data or not data["timestamp"]:
            data["timestamp"] = utc_now().isoformat() + "Z"
        super().__init__(**data)


class PaginatedData(BaseModel, Generic[T]):
    """Paginated data."""

    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int


def success_response(
    data: Any = None,
    message: str = "Success",
    code: int = 200,
) -> dict:
    """Build a success response."""
    return {
        "success": True,
        "code": code,
        "message": message,
        "data": data,
        "timestamp": utc_now().isoformat() + "Z",
    }


def error_response(
    message: str = "Error",
    code: int = 400,
    data: Any = None,
) -> dict:
    """Build an error response."""
    return {
        "success": False,
        "code": code,
        "message": message,
        "data": data,
        "timestamp": utc_now().isoformat() + "Z",
    }


def paginated_response(
    items: List[Any],
    total: int,
    page: int = 1,
    page_size: int = 20,
    message: str = "Success",
) -> dict:
    """Build a paginated response."""
    pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    return success_response(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        },
        message=message,
    )
