"""Shared cookie-based token extraction."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.joysafeter_shared.config.settings import settings


def extract_token_from_cookies(cookies: Mapping[str, Any]) -> Optional[str]:
    """Return the configured authentication cookie value, or ``None``."""
    value: str | None = cookies.get(settings.cookie_name)
    return value or None
