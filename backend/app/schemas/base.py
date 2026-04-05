from typing import Generic, Optional, TypeVar

from pydantic import BaseModel as PydanticBaseModel

T = TypeVar("T")


class BaseResponse(PydanticBaseModel, Generic[T]):
    """Base class for all API responses."""

    success: bool
    code: int  # status code (200=success, other=error code)
    msg: str  # user-friendly message
    data: Optional[T] = None
    err: Optional[T] = None
