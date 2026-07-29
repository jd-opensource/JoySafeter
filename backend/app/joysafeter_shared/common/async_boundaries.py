from __future__ import annotations

from typing import Any, Mapping, Type

from app.joysafeter_shared.common.app_errors import AppError, ServiceUnavailableError


def async_boundary_error_payload(
    *,
    code: str,
    message: str,
    boundary: str,
    operation: str,
    data: Mapping[str, Any] | None = None,
    source: str = "runtime",
    retryable: bool | None = None,
    user_action: str | None = "retry",
    detail: str | None = None,
    error_class: Type[AppError] = ServiceUnavailableError,
) -> dict[str, Any]:
    payload_data: dict[str, Any] = {
        "boundary": boundary,
        "operation": operation,
    }
    if data:
        payload_data.update(dict(data))
    kwargs: dict[str, Any] = {
        "message": message,
        "code": code,
        "data": payload_data,
        "source": source,
        "user_action": user_action,
        "detail": detail,
    }
    # retryable=None means "inherit the semantic class default" (e.g. NotFoundError
    # is not retryable, ServiceUnavailableError is), instead of flattening every
    # boundary failure to retryable.
    if retryable is not None:
        kwargs["retryable"] = retryable
    return error_class(**kwargs).to_stream_event()
