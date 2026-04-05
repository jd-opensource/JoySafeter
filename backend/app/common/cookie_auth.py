"""Shared cookie-based token extraction."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.core.settings import settings

_ALL_COOKIE_NAMES = (
    settings.cookie_name,
    "session-token",
    "session_token",
    "access_token",
    "auth_token",
)


def extract_token_from_cookies(cookies: Mapping[str, Any]) -> Optional[str]:
    """Return the first auth token found in *cookies*, or ``None``.

    Checks ``settings.cookie_name`` first, then common legacy names.
    """
    for name in _ALL_COOKIE_NAMES:
        value = cookies.get(name)
        if value:
            return value
    return None
