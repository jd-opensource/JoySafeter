import asyncio
import functools
import logging
import random
from typing import Any, Callable, TypeVar

from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    InterfaceError,
    OperationalError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_ERRORS = (
    OperationalError,
    DisconnectionError,
    InterfaceError,
)

RETRYABLE_PGCODES = frozenset({
    "40001",  # serialization_failure
    "40P01",  # deadlock_detected
    "08006",  # connection_failure
    "08003",  # connection_does_not_exist
    "57P01",  # admin_shutdown
    "57P02",  # crash_shutdown
    "57P03",  # cannot_connect_now
})


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, RETRYABLE_ERRORS):
        return True
    if isinstance(exc, DBAPIError) and exc.orig:
        pgcode = getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None)
        if pgcode and pgcode in RETRYABLE_PGCODES:
            return True
    return False


async def with_db_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
    **kwargs: Any,
) -> Any:
    """Execute an async function with automatic retry on transient DB errors.

    Uses exponential backoff with jitter. Only retries on connection errors,
    deadlocks, and serialization failures.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            if not _is_retryable(e) or attempt >= max_retries:
                raise
            last_exc = e
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = delay * random.uniform(0.5, 1.0)
            logger.warning(
                "DB operation failed (attempt %d/%d), retrying in %.2fs: %s",
                attempt + 1, max_retries, jitter, e,
            )
            await asyncio.sleep(jitter)

    raise last_exc  # type: ignore[misc]


def db_retry(
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
):
    """Decorator for async functions that should retry on transient DB errors."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await with_db_retry(
                fn, *args,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                **kwargs,
            )
        return wrapper

    return decorator
