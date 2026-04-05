import uuid
from datetime import datetime
from typing import Annotated, Generic, Optional, TypeVar

from pydantic import BaseModel as PydanticBaseModel
from pydantic import BeforeValidator

T = TypeVar("T")

UUIDStr = Annotated[
    str,
    BeforeValidator(lambda v: str(v) if isinstance(v, uuid.UUID) else v),
]

ISODatetime = Annotated[
    Optional[str],
    BeforeValidator(lambda v: v.isoformat() if isinstance(v, datetime) else v),
]


class BaseResponse(PydanticBaseModel, Generic[T]):
    """Base class for all API responses."""

    success: bool
    code: int  # status code (200=success, other=error code)
    msg: str  # user-friendly message
    data: Optional[T] = None
    err: Optional[T] = None
