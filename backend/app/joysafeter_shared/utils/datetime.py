"""Timezone-aware date/time utility functions."""

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_now() -> datetime:
    """
    Return the current UTC time (timezone-aware).

    Replace the deprecated datetime.utcnow() with datetime.now(UTC).

    Returns:
        datetime: current UTC time with timezone info

    Example:
        >>> from app.joysafeter_shared.utils.datetime import utc_now
        >>> now = utc_now()
        >>> print(now.tzinfo)  # UTC
    """
    return datetime.now(UTC)


def platform_timezone() -> ZoneInfo:
    """Return the configured platform timezone, falling back to UTC."""
    timezone_name = os.getenv("JOYSAFETER_TIMEZONE", "").strip() or os.getenv("TZ", "").strip() or "UTC"
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def platform_now() -> datetime:
    """Return the current time converted from UTC to the platform timezone."""
    return utc_now().astimezone(platform_timezone())
