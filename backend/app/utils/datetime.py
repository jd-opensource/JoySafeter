"""
Date/time utility functions.

Provide timezone-aware datetime helpers.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """
    Return the current UTC time (timezone-aware).

    Replace the deprecated datetime.utcnow() with datetime.now(UTC).

    Returns:
        datetime: current UTC time with timezone info

    Example:
        >>> from app.utils.datetime import utc_now
        >>> now = utc_now()
        >>> print(now.tzinfo)  # UTC
    """
    return datetime.now(UTC)
