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

from app.common.error_contract import ErrorDescriptor, ErrorSource, UserAction
from app.common.response import error_response


class AppException(HTTPException):
    """Base application exception (recommended for all business code)."""

    code: int | str
    data: Any

    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        message: str = "Internal Server Error",
        *,
        code: int | str | None = None,
        data: Any = None,
        source: ErrorSource = "internal",
        retryable: bool = False,
        detail: str | None = None,
        user_action: UserAction | None = None,
        context: dict[str, Any] | None = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = status_code if code is None else code
        self.data = data
        self.error = ErrorDescriptor(
            code=str(self.code),
            message=message,
            source=source,
            retryable=retryable,
            detail=detail,
            user_action=user_action,
            context=context or {},
        )

    def to_error_descriptor(self, *, http_status: int | None = None) -> dict[str, Any]:
        """Expose structured error metadata for the new contract without changing live HTTP responses yet."""
        return self.error.to_dict(http_status=http_status)


# Common HTTP exceptions (raise directly from business code)


class NotFoundException(AppException):
    """Resource not found (404)."""

    def __init__(self, message: str = "Resource not found", *, code: int | None = None, data: Any = None):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            message=message,
            code=code,
            data=data,
            source="api",
            retryable=False,
        )


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
    BUILD_COPILOT_MODEL_REQUIRED = "BUILD_COPILOT_MODEL_REQUIRED"

    error_code: str
    params: Dict[str, Any]

    def __init__(
        self,
        code: str | None = None,
        message: str = "Model configuration error",
        *,
        error_code: str | None = None,
        params: Dict[str, Any] | None = None,
        detail: str | None = None,
        source: ErrorSource = "node",
        retryable: bool = False,
        user_action: UserAction | None = None,
        context: dict[str, Any] | None = None,
    ):
        resolved_code = error_code if error_code is not None else code
        if resolved_code is None:
            raise TypeError("ModelConfigError requires 'code' or legacy 'error_code'")

        self.error_code = resolved_code
        self.params = params or {}
        merged_context = dict(self.params)
        if context:
            merged_context.update(context)
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=message,
            code=resolved_code,
            data={"error_code": resolved_code, "params": self.params},
            source=source,
            retryable=retryable,
            detail=detail,
            user_action=user_action,
            context=merged_context,
        )


class BadRequestException(AppException):
    """Bad request (400)."""

    def __init__(
        self,
        message: str = "Bad request",
        *,
        code: int | str | None = None,
        data: Any = None,
        source: ErrorSource = "api",
        retryable: bool = False,
        detail: str | None = None,
        user_action: UserAction | None = None,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=message,
            code=code,
            data=data,
            source=source,
            retryable=retryable,
            detail=detail,
            user_action=user_action,
            context=context,
        )


class UnauthorizedException(AppException):
    """Unauthorized (401)."""

    def __init__(self, message: str = "Unauthorized", *, code: int | None = None, data: Any = None):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            code=code,
            data=data,
            source="auth",
            retryable=False,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(AppException):
    """Forbidden (403)."""

    def __init__(self, message: str = "Forbidden", *, code: int | None = None, data: Any = None):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            message=message,
            code=code,
            data=data,
            source="permission",
            retryable=False,
        )


class ValidationException(AppException):
    """Request validation failed (422)."""

    def __init__(self, message: str = "Validation error", *, code: int | None = None, data: Any = None):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=message,
            code=code,
            data=data,
            source="validation",
            retryable=False,
        )


class ConflictException(AppException):
    """Resource conflict (409)."""

    def __init__(self, message: str = "Resource conflict", *, code: int | None = None, data: Any = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            message=message,
            code=code,
            data=data,
            source="api",
            retryable=False,
        )


class TooManyRequestsException(AppException):
    """Too many requests (429)."""

    def __init__(self, message: str = "Too many requests", *, code: int | None = None, data: Any = None):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            message=message,
            code=code,
            data=data,
            source="api",
            retryable=True,
        )


class InternalServerException(AppException):
    """Internal server error (500)."""

    def __init__(
        self,
        message: str = "Internal Server Error",
        *,
        code: int | str | None = 1007,
        data: Any = None,
        source: ErrorSource = "internal",
        retryable: bool = False,
        detail: str | None = None,
        user_action: UserAction | None = None,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=message,
            code=code,
            data=data,
            source=source,
            retryable=retryable,
            detail=detail,
            user_action=user_action,
            context=context,
        )


class ClientClosedException(AppException):
    """Client disconnected early (499)."""

    def __init__(self, message: str = "Client has closed the connection", *, code: int | None = 1008, data: Any = None):
        # 499 is a non-standard HTTP status code, but some gateways/logging systems use it
        super().__init__(status_code=499, message=message, code=code, data=data, source="api", retryable=True)


class BusinessLogicException(BadRequestException):
    """Business logic error (default 400, business code default 1006)."""

    def __init__(self, message: str, *, code: int | None = 1006, data: Any = None):
        super().__init__(message=message, code=code, data=data)


class ParameterValidationException(BadRequestException):
    """Parameter/business validation error (default 400, business code default 1001)."""

    def __init__(self, message: str, *, code: int | None = 1001, data: Any = None):
        super().__init__(message=message, code=code, data=data)


# Aliases

# Authentication -> 401, Authorization -> 403
AuthenticationException = UnauthorizedException
AuthorizationException = ForbiddenException
ResourceNotFoundException = NotFoundException
ResourceConflictException = ConflictException


# Unified error response construction & global exception handlers


def create_error_response(*, status_code: int, error: ErrorDescriptor | dict[str, Any]) -> Response:
    """Build an HTTP error response using the canonical error envelope."""
    return JSONResponse(
        status_code=status_code,
        content=error_response(error=error),
    )


async def app_exception_handler(request: Request, exc: AppException) -> Response:
    """Handle application exceptions (AppException)."""
    return create_error_response(
        status_code=exc.status_code,
        error=exc.to_error_descriptor(http_status=exc.status_code),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Handle FastAPI/Starlette HTTPException (non-AppException)."""
    normalized = BadRequestException(
        message=str(exc.detail),
        code=str(exc.status_code),
        source="api",
        retryable=False,
    )
    normalized.status_code = exc.status_code
    return create_error_response(
        status_code=exc.status_code,
        error=normalized.to_error_descriptor(http_status=exc.status_code),
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

    error = ErrorDescriptor(
        code=str(status.HTTP_422_UNPROCESSABLE_ENTITY),
        message="Request parameter validation failed",
        detail="Request parameter validation failed.",
        source="validation",
        retryable=False,
        user_action="fix_input",
        context={"validation_errors": errors} if errors else {},
    )
    return create_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error=error.to_dict(http_status=status.HTTP_422_UNPROCESSABLE_ENTITY),
    )


async def general_exception_handler(request: Request, exc: Exception) -> Response:
    """Handle uncaught exceptions through the legacy HTTP error response path until Task 2."""

    # ValueError → 400 (or 404 if message says "not found")
    if isinstance(exc, ValueError):
        msg = str(exc)
        if "not found" in msg.lower():
            return await app_exception_handler(request, NotFoundException(msg))
        return await app_exception_handler(request, BadRequestException(msg))

    # PermissionError → 403
    if isinstance(exc, PermissionError):
        return await app_exception_handler(request, ForbiddenException(str(exc)))

    # RuntimeError → 400 (service-layer operational errors)
    if isinstance(exc, RuntimeError):
        return await app_exception_handler(request, BadRequestException(str(exc)))

    # Truly unexpected — 500
    try:
        from loguru import logger

        logger.exception("Unhandled exception: {}", exc)
    except Exception:
        pass

    debug = False
    try:
        from app.core.settings import settings

        debug = bool(getattr(settings, "debug", False))
    except Exception:
        debug = False

    detail = str(exc) if debug else "An unexpected internal error occurred."
    context = {"error_type": type(exc).__name__} if debug else {}
    normalized = InternalServerException(
        message="Internal Server Error",
        code="INTERNAL_UNEXPECTED_ERROR",
        detail=detail,
        source="internal",
        retryable=False,
        user_action="contact_support",
        context=context,
    )
    return create_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error=normalized.to_error_descriptor(http_status=status.HTTP_500_INTERNAL_SERVER_ERROR),
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
    app.add_exception_handler(ValueError, general_exception_handler)
    app.add_exception_handler(PermissionError, general_exception_handler)
    app.add_exception_handler(RuntimeError, general_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)


def normalize_exception(exc: Exception) -> AppException:
    """Foundation helper for the new contract; runtime handlers do not use this path yet."""
    if isinstance(exc, AppException):
        return exc
    return InternalServerException(
        message="Unexpected internal error.",
        code="INTERNAL_UNEXPECTED_ERROR",
        detail=str(exc),
        source="internal",
        retryable=False,
        user_action="contact_support",
    )


# Convenience raise_* helpers


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
