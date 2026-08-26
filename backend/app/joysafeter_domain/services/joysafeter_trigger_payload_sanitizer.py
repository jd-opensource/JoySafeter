from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from app.joysafeter_shared.ids import EntityId
from app.joysafeter_shared.json_boundary import JsonBoundaryTypeError

_MAX_STRING_CHARS = 1024
_MAX_COLLECTION_ITEMS = 50
_MAX_DEPTH = 8
_MAX_LAST_PAYLOAD_JSON_CHARS = 16_384
_REDACTED = "[REDACTED]"
_TRUNCATED_DEPTH = "[TRUNCATED_DEPTH]"

_SENSITIVE_KEY_FRAGMENTS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "id_token",
        "password",
        "passwd",
        "private_key",
        "refresh_token",
        "secret",
        "set_cookie",
        "signature",
        "token",
    }
)


def sanitize_trigger_last_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, redacted payload snapshot safe to persist on triggers.

    The full delivery payload is still used for prompt rendering and filter
    evaluation. This function only controls the observational ``last_payload``
    JSONB snapshot exposed back through trigger APIs.
    """
    sanitized = _sanitize_value(payload, depth=0)
    if not isinstance(sanitized, dict):
        return {"_value": sanitized}
    serialized = _safe_json_dump(sanitized)
    if len(serialized) <= _MAX_LAST_PAYLOAD_JSON_CHARS:
        return sanitized
    return _summarize_oversized_payload(sanitized, original_json_chars=len(serialized))


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if depth >= _MAX_DEPTH:
        return _TRUNCATED_DEPTH
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        items = list(value.items())
        for raw_key, raw_value in items[:_MAX_COLLECTION_ITEMS]:
            key = str(raw_key)
            out[key] = _REDACTED if _is_sensitive_key(key) else _sanitize_value(raw_value, depth=depth + 1)
        if len(items) > _MAX_COLLECTION_ITEMS:
            out["_truncated_keys"] = len(items) - _MAX_COLLECTION_ITEMS
        return out
    if isinstance(value, list):
        list_out: list[Any] = [_sanitize_value(item, depth=depth + 1) for item in value[:_MAX_COLLECTION_ITEMS]]
        if len(value) > _MAX_COLLECTION_ITEMS:
            list_out.append({"_truncated_items": len(value) - _MAX_COLLECTION_ITEMS})
        return list_out
    if isinstance(value, tuple):
        return _sanitize_value(list(value), depth=depth)
    if isinstance(value, str):
        return _truncate_string(value)
    if isinstance(value, bytes):
        return _truncate_string(value.decode("utf-8", errors="replace"))
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, EntityId):
        return str(value)
    raise JsonBoundaryTypeError(f"Unsupported trigger payload value: {type(value).__name__}")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_").replace(" ", "_")
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _truncate_string(value: str) -> str:
    if len(value) <= _MAX_STRING_CHARS:
        return value
    omitted = len(value) - _MAX_STRING_CHARS
    return f"{value[:_MAX_STRING_CHARS]}...[truncated {omitted} chars]"


def _safe_json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _summarize_oversized_payload(payload: dict[str, Any], *, original_json_chars: int) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "_truncated": True,
        "_original_json_chars": original_json_chars,
    }
    trigger = payload.get("trigger")
    if isinstance(trigger, dict):
        summary["trigger"] = trigger
    headers = payload.get("headers")
    if isinstance(headers, dict):
        summary["headers"] = headers
    body = payload.get("body")
    if isinstance(body, dict):
        summary["body"] = {"_truncated": True, "_keys": len(body)}
    elif body is not None:
        summary["body"] = {"_truncated": True, "_type": type(body).__name__}
    return summary
