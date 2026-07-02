"""API response wrapper middleware.

Wraps all /api/v1 JSON responses in the standard envelope:

List:   {"success": true, "code": 200, "message": "OK", "data": [...], "has_more": true, ...}
Single: {"success": true, "code": 200, "message": "OK", "data": {...}}
"""

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse


def _carry_over_headers(new_response: Response, original: Response) -> Response:
    """Copy the original response's raw headers (minus content-length) onto a
    rebuilt response.

    Critically this preserves *every* ``Set-Cookie`` header. ``dict(headers)``
    / ``headers.items()`` collapse repeated headers into one, which silently
    dropped the ``refresh_token`` and ``csrf_token`` cookies on /auth/refresh
    and /auth/login — leaving the browser with a stale refresh token and
    causing spurious logouts. ``raw_headers`` keeps the multi-valued header
    list intact.
    """
    preserved: list[tuple[bytes, bytes]] = [(k, v) for (k, v) in original.raw_headers if k.lower() != b"content-length"]
    # Drop any content-type the rebuilt response already set to avoid dupes.
    has_content_type = any(k.lower() == b"content-type" for k, _ in preserved)
    new_response.raw_headers = [
        (k, v) for (k, v) in new_response.raw_headers if not (has_content_type and k.lower() == b"content-type")
    ] + preserved
    return new_response


class ApiV1ResponseWrapperMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if not request.url.path.startswith("/api/v1"):
            return response

        # Skip SSE / streaming endpoints — BaseHTTPMiddleware breaks long-lived streams
        if "/stream" in request.url.path or "/chat" in request.url.path:
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        if isinstance(response, StreamingResponse):
            return response

        if response.status_code >= 400:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk if isinstance(chunk, bytes) else chunk.encode()

        if not body:
            return response

        try:
            original = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _carry_over_headers(Response(content=body, status_code=response.status_code), response)

        if isinstance(original, dict) and "success" in original:
            return _carry_over_headers(Response(content=body, status_code=response.status_code), response)

        wrapped = {
            "success": True,
            "code": response.status_code,
            "message": "OK",
        }

        # Flatten paginated responses: {data: [...], has_more, first_id, last_id}
        if isinstance(original, dict) and "data" in original and "has_more" in original:
            wrapped["data"] = original["data"]
            wrapped["has_more"] = original["has_more"]
            if "first_id" in original:
                wrapped["first_id"] = original["first_id"]
            if "last_id" in original:
                wrapped["last_id"] = original["last_id"]
        else:
            wrapped["data"] = original

        wrapped_body = json.dumps(wrapped, ensure_ascii=False, default=str)
        return _carry_over_headers(
            Response(
                content=wrapped_body,
                status_code=response.status_code,
                media_type="application/json",
            ),
            response,
        )
