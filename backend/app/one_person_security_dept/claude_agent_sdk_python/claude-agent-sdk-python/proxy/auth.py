"""Authentication helpers for Anthropic-compatible inbound requests."""

from __future__ import annotations

from typing import Mapping


class AuthError(ValueError):
    """Raised when inbound auth headers are missing or invalid."""


def extract_inbound_token(headers: Mapping[str, str]) -> str:
    """Extract token from Anthropic-style headers.

    Priority:
    1) x-api-key
    2) Authorization: Bearer <token>
    """
    x_api_key = headers.get("x-api-key")
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()

    authorization = headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token

    raise AuthError("Missing authentication. Provide x-api-key or Authorization: Bearer <token>")


def mask_token(token: str) -> str:
    """Mask token for safe logs."""
    if not token:
        return "<empty>"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"
