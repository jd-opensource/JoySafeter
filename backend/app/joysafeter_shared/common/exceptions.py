from __future__ import annotations

from typing import Any, Iterable, Mapping

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError as PydanticValidationError

from app.joysafeter_shared.common.app_errors import (
    AppError,
    AuthError,
    ClientClosedError,
    ConflictError,
    DomainError,
    InfraError,
    InternalError,
    InternalServiceError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RequestValidationAppError,
    ValidationError,
    normalize_app_error,
)
from app.joysafeter_shared.common.response import error_response


def create_error_response(
    *,
    status_code: int,
    error: AppError,
    headers: Mapping[str, str] | None = None,
) -> Response:
    return JSONResponse(
        status_code=status_code,
        content=error_response(error.to_payload()),
        headers=dict(headers) if headers else None,
    )


def _status_code_for_error(error: AppError) -> int:
    if isinstance(error, ClientClosedError):
        return 499
    if isinstance(error, NotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(error, AuthError):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(error, PermissionDeniedError):
        return status.HTTP_403_FORBIDDEN
    if isinstance(error, RequestValidationAppError):
        return status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(error, ValidationError):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(error, ConflictError):
        return status.HTTP_409_CONFLICT
    if isinstance(error, RateLimitError):
        return status.HTTP_429_TOO_MANY_REQUESTS
    if isinstance(error, InternalError | InfraError):
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    if isinstance(error, DomainError):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _headers_for_error(error: AppError) -> dict[str, str] | None:
    if isinstance(error, AuthError):
        return {"WWW-Authenticate": "Bearer"}
    return None


async def app_error_handler(request: Request, exc: AppError) -> Response:
    return create_error_response(
        status_code=_status_code_for_error(exc),
        error=exc,
        headers=_headers_for_error(exc),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    error = AppError(
        code=str(exc.status_code),
        message=str(exc.detail),
        data=None,
    )
    return create_error_response(
        status_code=exc.status_code,
        error=error,
        headers=exc.headers,
    )


def _format_validation_errors(errors: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for err in errors:
        formatted.append(
            {
                "field": ".".join(str(part) for part in err.get("loc", ())),
                "message": err.get("msg"),
                "type": err.get("type"),
            }
        )
    return formatted


async def request_validation_exception_handler(request: Request, exc: Exception) -> Response:
    errors: list[dict[str, Any]] = []
    if isinstance(exc, (RequestValidationError, PydanticValidationError)):
        errors = _format_validation_errors(exc.errors())

    error = RequestValidationAppError(data={"errors": errors})
    return await app_error_handler(request, error)


async def general_exception_handler(request: Request, exc: Exception) -> Response:
    if isinstance(exc, AppError):
        return await app_error_handler(request, exc)

    try:
        from loguru import logger

        logger.exception("Unhandled exception: {}", exc)
    except Exception:
        pass

    return await app_error_handler(request, InternalServiceError())


def register_exception_handlers(app: Any) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(PydanticValidationError, request_validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)


def normalize_exception(exc: Exception) -> AppError:
    return normalize_app_error(exc)
