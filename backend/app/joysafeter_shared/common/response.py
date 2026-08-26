"""Unified response format."""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

from app.joysafeter_shared.utils.datetime import utc_now

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
