"""
Rate limiting decorator for API endpoints.
IP-based and user-based rate limiting using in-memory storage.
"""

import time
from dataclasses import dataclass
from functools import wraps
from ipaddress import ip_address, ip_network
from typing import Callable, Optional

from fastapi import Request
from loguru import logger

from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.common.app_errors import RateLimitExceededError

_REDIS_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    reset_at: int


class RateLimiter:
    """In-memory fallback limiter used when Redis is unavailable."""

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

    def check(self, key: str, max_requests: int, window_seconds: int) -> RateLimitDecision:
        allowed = self.is_allowed(key, max_requests, window_seconds)
        return RateLimitDecision(
            allowed=allowed,
            remaining=self.get_remaining(key, max_requests, window_seconds),
            reset_at=int(time.time() + window_seconds),
        )


class DistributedRateLimiter:
    """Redis-backed limiter with in-memory fallback for degraded local/dev mode."""

    def __init__(self, fallback: RateLimiter) -> None:
        self._fallback = fallback

    async def check(self, key: str, max_requests: int, window_seconds: int) -> RateLimitDecision:
        redis = RedisClient.get_client()
        if redis is None:
            return self._fallback.check(key, max_requests, window_seconds)

        try:
            current_raw, ttl_raw = await redis.eval(_REDIS_RATE_LIMIT_SCRIPT, 1, key, window_seconds)
            current = int(current_raw)
            ttl = int(ttl_raw)
            reset_after = ttl if ttl > 0 else window_seconds
            return RateLimitDecision(
                allowed=current <= max_requests,
                remaining=max(0, max_requests - current),
                reset_at=int(time.time() + reset_after),
            )
        except Exception as exc:
            logger.warning("Redis rate limiter failed; falling back to in-memory limiter: {}", exc)
            return self._fallback.check(key, max_requests, window_seconds)


# global rate limiter instance
_rate_limiter = RateLimiter()
_distributed_rate_limiter = DistributedRateLimiter(_rate_limiter)


def get_client_ip(request: Request) -> str:
    """Return the client IP address."""
    from app.joysafeter_shared.config.settings import settings

    direct_ip = str(request.client.host) if request.client else "unknown"
    if settings.trust_forwarded_headers and _is_trusted_proxy(direct_ip, settings.trusted_proxy_cidrs):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return str(forwarded).split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return str(real_ip)

    return direct_ip


def _is_trusted_proxy(client_ip: str, cidrs: str) -> bool:
    if not cidrs.strip() or client_ip == "unknown":
        return False
    try:
        address = ip_address(client_ip)
    except ValueError:
        return False
    for raw_cidr in cidrs.split(","):
        cidr = raw_cidr.strip()
        if not cidr:
            continue
        try:
            if address in ip_network(cidr, strict=False):
                return True
        except ValueError:
            logger.warning("Ignoring invalid trusted proxy CIDR: {}", cidr)
    return False


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

            decision = await _distributed_rate_limiter.check(rate_limit_key, max_requests, window_seconds)
            if not decision.allowed:
                raise RateLimitExceededError(
                    message=f"Rate limit exceeded. Try again in {window_seconds} seconds.",
                    data={
                        "headers": {
                            "X-RateLimit-Limit": str(max_requests),
                            "X-RateLimit-Remaining": str(decision.remaining),
                            "X-RateLimit-Reset": str(decision.reset_at),
                        }
                    },
                )

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
