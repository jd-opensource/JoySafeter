from __future__ import annotations

import json
from typing import Any, Mapping


def stream_error_event(
    *,
    code: str,
    message: str,
    data: Mapping[str, Any] | None = None,
    source: str = "internal",
    retryable: bool = False,
    user_action: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "data": dict(data) if data is not None else None,
        "source": source,
        "retryable": retryable,
    }
    if user_action is not None:
        payload["user_action"] = user_action
    return f"event: error\ndata: {json.dumps(payload)}\n\n"
