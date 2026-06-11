"""V2 API response wrapper middleware.

Wraps all /api/v2 JSON responses in the standard envelope:

List:   {"success": true, "code": 200, "message": "OK", "data": [...], "has_more": true, ...}
Single: {"success": true, "code": 200, "message": "OK", "data": {...}}
"""

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse


class V2ResponseWrapperMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if not request.url.path.startswith("/api/v2"):
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
            return Response(content=body, status_code=response.status_code, headers=dict(response.headers))

        if isinstance(original, dict) and "success" in original:
            return Response(content=body, status_code=response.status_code, headers=dict(response.headers))

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
        return Response(
            content=wrapped_body,
            status_code=response.status_code,
            media_type="application/json",
            headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
        )
