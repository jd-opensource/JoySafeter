"""
Rate limiting utilities.
Use in-memory storage (simple implementation); consider Redis for production.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Tuple

from fastapi import Request

from app.common.exceptions import TooManyRequestsException


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self):
        # storage format: {key: [(timestamp, count), ...]}
        self._records: Dict[str, list] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Check whether the rate limit has been exceeded.

        Returns: (allowed, remaining_requests)
        """
        async with self._lock:
            now = datetime.now()
            window_start = now - timedelta(seconds=window_seconds)

            # purge expired records
            records = self._records[key]
            records[:] = [(ts, count) for ts, count in records if ts > window_start]

            # count requests in the current window
            current_count = sum(count for _, count in records)

            if current_count >= max_requests:
                return False, 0

            # record this request
            records.append((now, 1))

            remaining = max_requests - current_count - 1
            return True, remaining

    async def reset(self, key: str):
        """Reset the rate limit for a given key."""
        async with self._lock:
            if key in self._records:
                del self._records[key]


# global rate limiter instance
rate_limiter = RateLimiter()


def get_client_identifier(request: Request) -> str:
    """Get a client identifier for rate limiting."""
    # prefer IP address
    client_ip = request.client.host if request.client else "unknown"

    # if X-Forwarded-For is present, use the first IP
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    return client_ip


async def check_rate_limit_decorator(max_requests: int, window_seconds: int, key_func=None):
    """
    Rate limiting decorator.

    Usage:
        @router.post("/login")
        @check_rate_limit_decorator(max_requests=5, window_seconds=60)
        async def login(...):
            ...
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # extract request from arguments
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if not request:
                for key, value in kwargs.items():
                    if isinstance(value, Request):
                        request = value
                        break

            if not request:
                # if no request found, skip rate limiting
                return await func(*args, **kwargs)

            # get client identifier
            if key_func:
                identifier = key_func(request)
            else:
                identifier = get_client_identifier(request)

            # check rate limit
            allowed, remaining = await rate_limiter.check_rate_limit(
                f"{func.__name__}:{identifier}", max_requests, window_seconds
            )

            if not allowed:
                raise TooManyRequestsException(
                    f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds."
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
