from __future__ import annotations

import logging
from typing import Any, Mapping

from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload


def _payload(
    *,
    boundary: str,
    code: str,
    message: str,
    operation: str,
    error: Exception | None = None,
    data: Mapping[str, Any] | None = None,
    source: str = "runtime",
    retryable: bool = True,
    user_action: str | None = "retry",
) -> dict[str, Any]:
    return async_boundary_error_payload(
        code=code,
        message=message,
        boundary=boundary,
        operation=operation,
        data=data,
        source=source,
        detail=error.__class__.__name__ if error is not None else None,
        retryable=retryable,
        user_action=user_action,
    )


def log_boundary_failure(
    logger: logging.Logger,
    *,
    boundary: str,
    code: str,
    message: str,
    operation: str,
    error: Exception | None = None,
    data: Mapping[str, Any] | None = None,
    source: str = "runtime",
    retryable: bool = True,
    user_action: str | None = "retry",
) -> None:
    logger.warning(
        message,
        extra={
            "error": _payload(
                boundary=boundary,
                code=code,
                message=message,
                operation=operation,
                error=error,
                data=data,
                source=source,
                retryable=retryable,
                user_action=user_action,
            )
        },
        exc_info=error is not None,
    )


def log_boundary_failure_loguru(
    logger: Any,
    *,
    boundary: str,
    code: str,
    message: str,
    operation: str,
    error: Exception | None = None,
    data: Mapping[str, Any] | None = None,
    source: str = "runtime",
    retryable: bool = True,
    user_action: str | None = "retry",
) -> None:
    logger.bind(
        error=_payload(
            boundary=boundary,
            code=code,
            message=message,
            operation=operation,
            error=error,
            data=data,
            source=source,
            retryable=retryable,
            user_action=user_action,
        )
    ).opt(exception=error).warning(message)
