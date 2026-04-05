"""
Unified exception system (single entry point).

- Exception classes: all inherit from `AppException(HTTPException)`, supporting separate
  `status_code` (HTTP) and `code` (business/error code), with `data` for extra error details.
- Global handlers: provide FastAPI exception handler functions and a one-call registration
  function `register_exception_handlers`, ensuring the unified response format defined by
  `app.common.response.error_response`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError as PydanticValidationError

from app.common.response import error_response


class AppException(HTTPException):
    """Base application exception (recommended for all business code)."""

    code: int
    data: Any

    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        message: str = "Internal Server Error",
        *,
        code: int | None = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = status_code if code is None else code
        self.data = data


# Common HTTP exceptions (raise directly from business code)


class NotFoundException(AppException):
    """Resource not found (404)."""

    def __init__(self, message: str = "Resource not found", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, message=message, code=code, data=data)


class ModelConfigError(AppException):
    """Model configuration error with structured error_code + params for frontend i18n.

    error_code: Frontend i18n key (e.g. MODEL_NOT_FOUND, MODEL_NO_CREDENTIALS)
    params:     Interpolation params (e.g. {model: "gpt-4o", provider: "openai"})
    message:    English fallback (shown when frontend has no i18n key)
    """

    # Error code constants — shared with frontend i18n keys
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_NO_CREDENTIALS = "MODEL_NO_CREDENTIALS"
    PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
    MODEL_NAME_REQUIRED = "MODEL_NAME_REQUIRED"

    error_code: str
    params: Dict[str, Any]

    def __init__(
        self,
        error_code: str,
        message: str = "Model configuration error",
        *,
        params: Dict[str, Any] | None = None,
    ):
        self.error_code = error_code
        self.params = params or {}
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=message,
            data={"error_code": error_code, "params": self.params},
        )


class BadRequestException(AppException):
    """Bad request (400)."""

    def __init__(self, message: str = "Bad request", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, message=message, code=code, data=data)


class UnauthorizedException(AppException):
    """Unauthorized (401)."""

    def __init__(self, message: str = "Unauthorized", *, code: int | None = None, data: Any = None):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            code=code,
            data=data,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(AppException):
    """Forbidden (403)."""

    def __init__(self, message: str = "Forbidden", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, message=message, code=code, data=data)


class ValidationException(AppException):
    """Request validation failed (422)."""

    def __init__(self, message: str = "Validation error", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, message=message, code=code, data=data)


class ConflictException(AppException):
    """Resource conflict (409)."""

    def __init__(self, message: str = "Resource conflict", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_409_CONFLICT, message=message, code=code, data=data)


class TooManyRequestsException(AppException):
    """Too many requests (429)."""

    def __init__(self, message: str = "Too many requests", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_429_TOO_MANY_REQUESTS, message=message, code=code, data=data)


class InternalServerException(AppException):
    """Internal server error (500)."""

    def __init__(self, message: str = "Internal Server Error", *, code: int | None = 1007, data: Any = None):
        super().__init__(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, message=message, code=code, data=data)


class ClientClosedException(AppException):
    """Client disconnected early (499)."""

    def __init__(self, message: str = "Client has closed the connection", *, code: int | None = 1008, data: Any = None):
        # 499 is a non-standard HTTP status code, but some gateways/logging systems use it
        super().__init__(status_code=499, message=message, code=code, data=data)


class BusinessLogicException(BadRequestException):
    """Business logic error (default 400, business code default 1006)."""

    def __init__(self, message: str, *, code: int | None = 1006, data: Any = None):
        super().__init__(message=message, code=code, data=data)


class ParameterValidationException(BadRequestException):
    """Parameter/business validation error (default 400, business code default 1001; legacy compat)."""

    def __init__(self, message: str, *, code: int | None = 1001, data: Any = None):
        super().__init__(message=message, code=code, data=data)


# Compatibility aliases (from legacy app/exceptions.py naming)

# Legacy naming semantics: Authentication -> 401, Authorization -> 403
AuthenticationException = UnauthorizedException
AuthorizationException = ForbiddenException
ResourceNotFoundException = NotFoundException
ResourceConflictException = ConflictException


# Unified error response construction & global exception handlers


def create_error_response(*, status_code: int, code: int, message: str, data: Any = None) -> Response:
    """Build a unified error response (conforming to app.common.response.error_response)."""
    return JSONResponse(
        status_code=status_code,
        content=error_response(message=message, code=code, data=data),
    )


async def app_exception_handler(request: Request, exc: AppException) -> Response:
    """Handle application exceptions (AppException)."""
    code_value = getattr(exc, "code", exc.status_code)
    code = code_value if isinstance(code_value, int) else exc.status_code
    return create_error_response(
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail),
        data=getattr(exc, "data", None),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Handle FastAPI/Starlette HTTPException (non-AppException)."""
    return create_error_response(
        status_code=exc.status_code,
        code=exc.status_code,
        message=str(exc.detail),
        data=getattr(exc, "data", None),
    )


def _format_validation_errors(errors: Iterable[Mapping[str, Any]]) -> List[dict[str, Any]]:
    formatted: List[dict[str, Any]] = []
    for err in errors:
        loc = err.get("loc", ())
        field_path = ".".join(str(x) for x in loc)
        formatted.append(
            {
                "field": field_path,
                "message": err.get("msg"),
                "type": err.get("type"),
            }
        )
    return formatted


async def request_validation_exception_handler(request: Request, exc: Exception) -> Response:
    """Handle request validation exceptions (RequestValidationError / PydanticValidationError)."""
    errors: List[dict[str, Any]] = []
    if isinstance(exc, (RequestValidationError, PydanticValidationError)):
        errors = _format_validation_errors(exc.errors())

    return create_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message="Request parameter validation failed",
        data={"validation_errors": errors} if errors else None,
    )


async def general_exception_handler(request: Request, exc: Exception) -> Response:
    """Handle uncaught exceptions (500)."""
    try:
        from loguru import logger

        logger.exception("Unhandled exception: {}", exc)
    except Exception:
        # fallback when logger is unavailable
        pass

    debug = False
    try:
        from app.core.settings import settings

        debug = bool(getattr(settings, "debug", False))
    except Exception:
        debug = False

    return create_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message=str(exc) if debug else "Internal Server Error",
        data={"error_type": type(exc).__name__} if debug else None,
    )


def register_exception_handlers(app: Any) -> None:
    """
    Register all exception handlers on the FastAPI app in one call.

    Note: keep this function free of hard FastAPI type dependencies to avoid circular imports.
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(PydanticValidationError, request_validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)


# Convenience raise_* helpers (from legacy app/exceptions.py)


def raise_validation_error(message: str, data: Any = None) -> None:
    raise ParameterValidationException(message, code=1001, data=data)


def raise_auth_error(message: str = "Authentication failed, please sign in again", data: Any = None) -> None:
    raise UnauthorizedException(message, code=1002, data=data)


def raise_permission_error(message: str = "Insufficient permissions", data: Any = None) -> None:
    raise ForbiddenException(message, code=1003, data=data)


def raise_not_found_error(resource: str, data: Any = None) -> None:
    raise NotFoundException(f"{resource} not found", code=1004, data=data)


def raise_conflict_error(message: str, data: Any = None) -> None:
    raise ConflictException(message, code=1005, data=data)


def raise_client_closed_error(message: str = "Client has closed the connection", data: Any = None) -> None:
    raise ClientClosedException(message, code=1008, data=data)


def raise_business_error(message: str, data: Any = None) -> None:
    raise BusinessLogicException(message, code=1006, data=data)


def raise_internal_error(message: str = "Internal server error", data: Any = None) -> None:
    raise InternalServerException(message, code=1007, data=data)
