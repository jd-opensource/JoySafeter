from __future__ import annotations

import json
from typing import Any, Mapping


def stream_error_event(
    *,
    code: str,
    message: str,
    data: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "code": code,
        "message": message,
        "data": dict(data) if data is not None else None,
    }
    return f"event: error\ndata: {json.dumps(payload)}\n\n"
