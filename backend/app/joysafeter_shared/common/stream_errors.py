from __future__ import annotations

import json
from typing import Any, Mapping

from app.joysafeter_shared.common.app_errors import AppError, normalize_app_error


def error_payload(
    exc: Exception,
    *,
    default_code: str = "INTERNAL_ERROR",
    default_message: str = "内部错误",
    data: Mapping[str, Any] | None = None,
    source: str = "internal",
    retryable: bool = False,
    status: int | None = None,
) -> dict[str, Any]:
    return normalize_app_error(
        exc,
        default_code=default_code,
        default_message=default_message,
        default_data=data,
        source=source,
        retryable=retryable,
    ).to_stream_event(status=status)


def error_event(
    exc: Exception,
    *,
    default_code: str = "INTERNAL_ERROR",
    default_message: str = "内部错误",
    data: Mapping[str, Any] | None = None,
    source: str = "internal",
    retryable: bool = False,
    status: int | None = None,
) -> str:
    payload = error_payload(
        exc,
        default_code=default_code,
        default_message=default_message,
        data=data,
        source=source,
        retryable=retryable,
        status=status,
    )
    return f"event: error\ndata: {json.dumps(payload)}\n\n"


def async_error_payload(
    *,
    code: str,
    message: str,
    data: Mapping[str, Any] | None = None,
    source: str = "internal",
    retryable: bool = False,
    user_action: str | None = None,
    detail: str | None = None,
    status: int | None = None,
) -> dict[str, Any]:
    return AppError(
        code=code,
        message=message,
        data=data,
        source=source,
        retryable=retryable,
        user_action=user_action,
        detail=detail,
    ).to_stream_event(status=status)


def stream_error_event(
    *,
    code: str,
    message: str,
    data: Mapping[str, Any] | None = None,
    source: str = "internal",
    retryable: bool = False,
    user_action: str | None = None,
    detail: str | None = None,
    status: int | None = None,
) -> str:
    payload = AppError(
        code=code,
        message=message,
        data=data,
        source=source,
        retryable=retryable,
        user_action=user_action,
        detail=detail,
    ).to_stream_event(status=status)
    return f"event: error\ndata: {json.dumps(payload)}\n\n"
