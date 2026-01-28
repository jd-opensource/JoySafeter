from enum import Enum
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class BadRequestResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Bad request", "error_code": "BAD_REQUEST"}})

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class NotFoundResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Not found", "error_code": "NOT_FOUND"}})

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class UnauthorizedResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Unauthorized access", "error_code": "UNAUTHORIZED"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class UnauthenticatedResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Unauthenticated access", "error_code": "UNAUTHENTICATED"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class ValidationErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Validation error", "error_code": "VALIDATION_ERROR"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class InternalServerErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Internal server error", "error_code": "INTERNAL_SERVER_ERROR"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


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
