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
                "source": "api",
                "retryable": False,
            }
        }
    )

    code: str = Field(..., description="Stable application error code")
    message: str = Field(..., description="User-facing error summary")
    data: Optional[dict] = Field(None, description="Structured error metadata")
    source: str = Field("internal", description="Error origin: api, engine, runtime, auth, validation, etc.")
    retryable: bool = Field(False, description="Whether the client should retry the request")
    user_action: Optional[str] = Field(None, description="Suggested user action: retry, configure_model, relogin, fix_input, contact_support")
    detail: Optional[str] = Field(None, description="Detailed diagnostic message")


BadRequestResponse = AppErrorPayloadSchema
NotFoundResponse = AppErrorPayloadSchema
UnauthorizedResponse = AppErrorPayloadSchema
UnauthenticatedResponse = AppErrorPayloadSchema
ValidationErrorResponse = AppErrorPayloadSchema
InternalServerErrorResponse = AppErrorPayloadSchema


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
