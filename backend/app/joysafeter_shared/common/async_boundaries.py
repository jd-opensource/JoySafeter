from __future__ import annotations

from typing import Any, Mapping

from app.joysafeter_shared.common.app_errors import ServiceUnavailableError


def async_boundary_error_payload(
    *,
    code: str,
    message: str,
    boundary: str,
    operation: str,
    data: Mapping[str, Any] | None = None,
    source: str = "runtime",
    retryable: bool = True,
    user_action: str | None = "retry",
    detail: str | None = None,
) -> dict[str, Any]:
    payload_data: dict[str, Any] = {
        "boundary": boundary,
        "operation": operation,
    }
    if data:
        payload_data.update(dict(data))
    return ServiceUnavailableError(
        message=message,
        code=code,
        data=payload_data,
        source=source,
        retryable=retryable,
        user_action=user_action,
        detail=detail,
    ).to_stream_event()
