from enum import Enum
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class AppErrorPayloadSchema(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "BAD_REQUEST",
                "message": "请求错误",
                "data": {"detail": "Bad request"},
            }
        }
    )

    code: str = Field(..., description="Stable application error code")
    message: str = Field(..., description="User-facing error summary")
    data: Optional[dict] = Field(None, description="Structured error metadata")


class ErrorEnvelopeResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error": {
                    "code": "NOT_FOUND",
                    "message": "资源不存在",
                    "data": None,
                },
            }
        }
    )

    success: bool = Field(False, description="Always false for error envelopes")
    error: AppErrorPayloadSchema = Field(..., description="Canonical application error payload")


BadRequestResponse = ErrorEnvelopeResponse
NotFoundResponse = ErrorEnvelopeResponse
UnauthorizedResponse = ErrorEnvelopeResponse
UnauthenticatedResponse = ErrorEnvelopeResponse
ValidationErrorResponse = ErrorEnvelopeResponse
InternalServerErrorResponse = ErrorEnvelopeResponse



class HealthResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok", "instantiated_at": "1760169236.778903"}})

    status: str = Field(..., description="Health status of the service")
    instantiated_at: str = Field(..., description="Unix timestamp when service was instantiated")


T = TypeVar("T")


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PaginationInfo(BaseModel):
    page: int = Field(0, description="Current page number (0-indexed)", ge=0)
    limit: int = Field(20, description="Number of items per page", ge=1, le=100)
    total_pages: int = Field(0, description="Total number of pages", ge=0)
    total_count: int = Field(0, description="Total count of items", ge=0)
    search_time_ms: float = Field(0, description="Search execution time in milliseconds", ge=0)


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper to add pagination info to classes used as response models"""

    data: List[T] = Field(..., description="List of items for the current page")
    meta: PaginationInfo = Field(..., description="Pagination metadata")
