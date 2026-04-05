"""
Rate limiting decorator for API endpoints.
IP-based and user-based rate limiting using in-memory storage.
"""

import time
from functools import wraps
from typing import Callable, Optional

from fastapi import HTTPException, Request


class RateLimiter:
    """In-memory rate limiter (simple implementation; production should use Redis)."""

    def __init__(self):
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """
        Check whether the request is allowed.

        Args:
            key: rate-limit key (typically an IP address or user ID)
            max_requests: maximum number of requests within the time window
            window_seconds: time window in seconds

        Returns:
            True if allowed, False otherwise
        """
        now = time.time()

        # get request history for this key
        if key not in self._requests:
            self._requests[key] = []

        # remove expired request records
        cutoff_time = now - window_seconds
        self._requests[key] = [req_time for req_time in self._requests[key] if req_time > cutoff_time]

        # check whether the limit is exceeded
        if len(self._requests[key]) >= max_requests:
            return False

        # record this request
        self._requests[key].append(now)
        return True

    def get_remaining(self, key: str, max_requests: int, window_seconds: int) -> int:
        """Return the remaining request count."""
        now = time.time()
        cutoff_time = now - window_seconds

        if key not in self._requests:
            return max_requests

        # remove expired records
        self._requests[key] = [req_time for req_time in self._requests[key] if req_time > cutoff_time]

        used = len(self._requests[key])
        return max(0, max_requests - used)


# global rate limiter instance
_rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """Return the client IP address."""
    # prefer X-Forwarded-For (behind proxy / load balancer)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return str(forwarded).split(",")[0].strip()

    # try X-Real-IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return str(real_ip)

    # fall back to direct client address
    if request.client:
        return str(request.client.host)

    return "unknown"


def rate_limit(max_requests: int = 5, window_seconds: int = 60, key_func: Optional[Callable[[Request], str]] = None):
    """
    Rate-limit decorator.

    Args:
        max_requests: maximum number of requests within the time window
        window_seconds: time window in seconds
        key_func: custom key function; receives a Request and returns a rate-limit key.
                  Defaults to using the client IP address.

    Example:
        @router.post("/login")
        @rate_limit(max_requests=5, window_seconds=60)
        async def login(request: Request, ...):
            ...
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # extract the Request object from arguments
            request: Optional[Request] = None

            # search positional arguments
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            # search keyword arguments (check several common names)
            if not request:
                for key in ["http_request", "request", "req"]:
                    if key in kwargs and isinstance(kwargs[key], Request):
                        request = kwargs[key]
                        break

            if not request:
                # if no Request object found, skip rate limiting
                return await func(*args, **kwargs)

            # generate rate-limit key
            if key_func:
                rate_limit_key = key_func(request)
            else:
                rate_limit_key = f"rate_limit:ip:{get_client_ip(request)}"

            # check rate limit
            if not _rate_limiter.is_allowed(rate_limit_key, max_requests, window_seconds):
                remaining = _rate_limiter.get_remaining(rate_limit_key, max_requests, window_seconds)
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Try again in {window_seconds} seconds.",
                    headers={
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": str(remaining),
                        "X-RateLimit-Reset": str(int(time.time() + window_seconds)),
                    },
                )

            # add rate-limit response headers
            remaining = _rate_limiter.get_remaining(rate_limit_key, max_requests, window_seconds)

            # execute the original function
            result = await func(*args, **kwargs)

            return result

        return wrapper

    return decorator


# pre-defined common rate-limit configurations
def auth_rate_limit():
    """Rate limit for auth endpoints: 5 requests/minute."""
    return rate_limit(max_requests=5, window_seconds=60)


def strict_rate_limit():
    """Strict rate limit: 3 requests/minute."""
    return rate_limit(max_requests=3, window_seconds=60)


def api_rate_limit():
    """General API rate limit: 60 requests/minute."""
    return rate_limit(max_requests=60, window_seconds=60)
