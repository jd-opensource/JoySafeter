from __future__ import annotations

from typing import Any, Iterable, Mapping

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError as PydanticValidationError

from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    AppError,
    AuthError,
    ClientClosedError,
    ConflictError,
    DomainError,
    InfraError,
    InternalError,
    InternalServiceError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RequestValidationAppError,
    ResourceConflictError,
    ServiceUnavailableError,
    ValidationError,
    normalize_app_error,
)
from app.joysafeter_shared.common.logging import _get_otel_trace_id
from app.joysafeter_shared.common.response import error_response


def create_error_response(
    *,
    status_code: int,
    error: AppError,
    headers: Mapping[str, str] | None = None,
) -> Response:
    payload = error.to_payload()
    trace_id = _get_otel_trace_id()
    if trace_id:
        payload["trace_id"] = trace_id
    return JSONResponse(
        status_code=status_code,
        content=error_response(payload),
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
    error = _app_error_from_http_exception(exc)
    return create_error_response(
        status_code=exc.status_code,
        error=error,
        headers=exc.headers,
    )


def _detail_to_message_and_data(detail: Any) -> tuple[str, dict[str, Any] | None]:
    if isinstance(detail, Mapping):
        message = detail.get("message") or detail.get("detail") or "Request failed"
        data = detail.get("data")
        if data is not None and isinstance(data, Mapping):
            return str(message), dict(data)
        extra = {k: v for k, v in detail.items() if k not in {"code", "message", "detail", "data"}}
        return str(message), extra or None
    if isinstance(detail, list):
        return "Request failed", {"detail": detail}
    return str(detail), None


def _app_error_from_http_exception(exc: HTTPException) -> AppError:
    detail = exc.detail
    if isinstance(detail, Mapping) and "code" in detail and "message" in detail:
        return AppError(
            code=str(detail["code"]),
            message=str(detail["message"]),
            data=detail.get("data") if isinstance(detail.get("data"), Mapping) else None,
            source=str(detail.get("source") or "api"),
            retryable=bool(detail.get("retryable", False)),
            user_action=detail.get("user_action") if isinstance(detail.get("user_action"), str) else None,
            detail=detail.get("detail") if isinstance(detail.get("detail"), str) else None,
        )

    message, data = _detail_to_message_and_data(detail)
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return AuthError(
            code="UNAUTHORIZED",
            message=message,
            data=data,
            source="auth",
            user_action="relogin",
        )
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        return AccessDeniedError(message, data=data)
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return NotFoundError(message, data=data)
    if exc.status_code == status.HTTP_409_CONFLICT:
        return ResourceConflictError(message, data=data)
    if exc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
        return RequestValidationAppError(message, data=data)
    if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return RateLimitError(
            code="RATE_LIMITED",
            message=message,
            data=data,
            source="api",
            retryable=True,
            user_action="retry",
        )
    if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        return ServiceUnavailableError(message, data=data)
    if 400 <= exc.status_code < 500:
        return InvalidRequestError(
            message,
            code=f"HTTP_{exc.status_code}",
            data=data,
        )
    return InternalServiceError(
        message if message else "内部错误",
        code=f"HTTP_{exc.status_code}",
        data=data,
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
