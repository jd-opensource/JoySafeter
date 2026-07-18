"""API response wrapper middleware.

Wraps all /api/v1 JSON responses in the standard envelope:

List:   {"success": true, "code": 200, "message": "OK", "data": [...], "has_more": true, ...}
Single: {"success": true, "code": 200, "message": "OK", "data": {...}}
"""

import json

from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

# Methods that mutate server state and therefore need CSRF protection when the
# request is authenticated by an ambient (browser-sent) session cookie.
_CSRF_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Endpoints that legitimately mutate state without (yet) having a CSRF cookie:
# pre-session identity bootstrap and the refresh/logout flows. These either run
# unauthenticated (no session cookie → skipped anyway) or manage the session
# cookie itself, so a stale/absent CSRF cookie must not lock the user out. Every
# other authenticated mutation under /auth (members, api-keys, projects,
# me/change-password, ...) stays protected.
_CSRF_EXEMPT_PATH_SUFFIXES = (
    "/auth/sign-up/email",
    "/auth/sign-in/email",
    "/auth/login/form",
    "/auth/refresh",
    "/auth/logout",
    "/auth/forgot-password",
    "/auth/reset-password",
    "/auth/verify-email",
    "/auth/resend-verification",
)


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


class RequestBodySizeLimitMiddleware:
    """Reject over-large request bodies before the application buffers them.

    An external, multi-tenant API that exposes file-upload endpoints must bound
    the memory a single request can force a worker to allocate. This is a pure
    ASGI middleware (not ``BaseHTTPMiddleware``) so it can reject on a declared
    ``Content-Length`` *before* the body is read, and enforce the same cap
    against the bytes actually streamed when the length is missing or understated
    (e.g. chunked transfer-encoding). It is the coarse outer guard; per-field
    content limits (prompt/message) are enforced separately at the schema layer.
    """

    def __init__(self, app, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: a declared Content-Length lets us reject without reading
        # (and therefore without allocating) the body at all.
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break
                if declared > self.max_body_bytes:
                    await self._reject(scope, receive, send)
                    return
                break

        # Slow path: enforce against the bytes actually streamed, covering a
        # missing or understated Content-Length (e.g. chunked transfer-encoding).
        received = 0
        max_body_bytes = self.max_body_bytes

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > max_body_bytes:
                    from app.joysafeter_shared.common.app_errors import PayloadTooLargeError

                    raise PayloadTooLargeError(data={"max_bytes": max_body_bytes})
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, scope, receive, send) -> None:
        from app.joysafeter_shared.common.app_errors import PayloadTooLargeError
        from app.joysafeter_shared.common.exceptions import create_error_response

        response = create_error_response(
            status_code=413,
            error=PayloadTooLargeError(data={"max_bytes": self.max_body_bytes}),
        )
        await response(scope, receive, send)


class SecurityHeadersMiddleware:
    """Attach standard hardening headers to every HTTP response.

    Pure ASGI so the headers apply to all responses (JSON, SSE, errors, docs)
    uniformly. ``setdefault`` semantics mean a route that intentionally sets one
    of these keeps its value. HSTS is only emitted in a secure (HTTPS) context so
    it never forces https on http://localhost during development.
    """

    def __init__(self, app, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
                if self.hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _is_csrf_exempt_path(path: str) -> bool:
    return any(path.endswith(suffix) for suffix in _CSRF_EXEMPT_PATH_SUFFIXES)


def _request_uses_header_auth(request: Request) -> bool:
    """A request authenticated by a header credential (Bearer / API key) is not
    CSRF-able: the browser does not attach those automatically cross-site."""
    if request.headers.get("X-Api-Key"):
        return True
    authorization = request.headers.get("Authorization", "")
    return authorization.startswith("Bearer ")


class CsrfProtectionMiddleware(BaseHTTPMiddleware):
    """Enforce signed double-submit CSRF on cookie-authenticated mutations.

    The check applies only when ALL of the following hold, so header-authenticated
    API traffic and anonymous/safe requests are never affected:

    * the method is state-changing (POST/PUT/PATCH/DELETE),
    * the path is not a session-bootstrap endpoint,
    * the request carries no header credential (Bearer / X-Api-Key), and
    * an ambient session cookie is present.

    In that case the ``X-CSRF-Token`` header must be a valid, unexpired CSRF JWT
    and must equal the ``csrf_token`` cookie (double-submit). Otherwise the
    request is rejected with a structured 403 so the client can refresh the token
    and retry.
    """

    async def dispatch(self, request: Request, call_next):
        if self._requires_csrf(request) and not self._has_valid_csrf(request):
            from app.joysafeter_shared.common.app_errors import AccessDeniedError
            from app.joysafeter_shared.common.exceptions import create_error_response

            return create_error_response(
                status_code=403,
                error=AccessDeniedError(
                    "CSRF 校验失败，请刷新页面后重试 / CSRF validation failed",
                    code="CSRF_VALIDATION_FAILED",
                    user_action="refresh",
                ),
            )
        return await call_next(request)

    @staticmethod
    def _requires_csrf(request: Request) -> bool:
        if request.method not in _CSRF_UNSAFE_METHODS:
            return False
        if _is_csrf_exempt_path(request.url.path):
            return False
        if _request_uses_header_auth(request):
            return False

        from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies

        # Only ambient cookie sessions can be forged cross-site.
        return bool(extract_token_from_cookies(request.cookies))

    @staticmethod
    def _has_valid_csrf(request: Request) -> bool:
        header_token = request.headers.get("X-CSRF-Token")
        cookie_token = request.cookies.get("csrf_token")
        if not header_token or not cookie_token or header_token != cookie_token:
            return False

        from app.joysafeter_shared.security import decode_token

        payload = decode_token(header_token)
        return bool(payload and payload.type == "csrf")
