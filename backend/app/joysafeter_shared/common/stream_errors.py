from __future__ import annotations

import json
from typing import Any, Mapping

from app.joysafeter_shared.common.app_errors import AppError, normalize_app_error
from app.joysafeter_shared.common.error_catalog import entry_for


def _build_error(
    *,
    code: str,
    message: str,
    data: Mapping[str, Any] | None,
    source: str,
    retryable: bool,
    user_action: str | None,
    detail: str | None,
) -> AppError:
    """Construct the catalog-registered semantic subclass for ``code`` (so HTTP
    source/semantics are derived centrally), falling back to a bare AppError for
    codes not in the catalog (e.g. stream/boundary-only codes)."""
    entry = entry_for(code)
    if entry is not None:
        return entry.error_class(
            code=code,
            message=message,
            data=data,
            retryable=retryable,
            user_action=user_action,
            detail=detail,
        )
    return AppError(
        code=code,
        message=message,
        data=data,
        source=source,
        retryable=retryable,
        user_action=user_action,
        detail=detail,
    )


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
    return _build_error(
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
    payload = _build_error(
        code=code,
        message=message,
        data=data,
        source=source,
        retryable=retryable,
        user_action=user_action,
        detail=detail,
    ).to_stream_event(status=status)
    return f"event: error\ndata: {json.dumps(payload)}\n\n"
