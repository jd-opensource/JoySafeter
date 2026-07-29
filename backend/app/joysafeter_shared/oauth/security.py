"""Security checks for OAuth provider-controlled outbound endpoints."""

from __future__ import annotations

from app.joysafeter_shared.security.ssrf_guard import SSRFError, validate_url


def validate_oauth_endpoint_url(url: str, *, endpoint_type: str) -> str:
    try:
        return validate_url(url, context=f"OAuth {endpoint_type} endpoint")
    except SSRFError as exc:
        raise ValueError(f"Invalid OAuth {endpoint_type} URL") from exc
