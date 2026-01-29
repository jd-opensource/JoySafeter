#!/usr/bin/env python
# coding=utf-8
"""
Utility functions and classes for CodeAgent.

This module provides rate limiting, retry mechanisms, and other utilities
for reliable agent execution.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import TypeVar

from loguru import logger

__all__ = [
    "RateLimiter",
    "Retrying",
    "retry",
    "is_rate_limit_error",
    "is_transient_error",
]


T = TypeVar("T")


def is_rate_limit_error(error: Exception) -> bool:
    """
    Check if an error is a rate limit error.

    Args:
        error: The exception to check.

    Returns:
        True if this appears to be a rate limit error.
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    rate_limit_indicators = [
        "rate limit",
        "ratelimit",
        "rate_limit",
        "too many requests",
        "429",
        "quota exceeded",
        "quota_exceeded",
        "throttle",
        "throttling",
    ]

    return any(indicator in error_str or indicator in error_type for indicator in rate_limit_indicators)


def is_transient_error(error: Exception) -> bool:
    """
    Check if an error is transient and worth retrying.

    Args:
        error: The exception to check.

    Returns:
        True if this is a transient error that might succeed on retry.
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    transient_indicators = [
        "timeout",
        "timed out",
        "connection",
        "network",
        "temporary",
        "service unavailable",
        "503",
        "502",
        "504",
        "internal server error",
        "500",
        "overloaded",
        "capacity",
    ]

    # Also consider rate limits as transient
    if is_rate_limit_error(error):
        return True

    return any(indicator in error_str or indicator in error_type for indicator in transient_indicators)


class RateLimiter:
    """
    Rate limiter for API calls.

    Implements a simple rate limiting strategy based on requests per minute.
    Can be used to prevent hitting API rate limits.

    Example:
        >>> limiter = RateLimiter(requests_per_minute=60)
        >>> for request in requests:
        ...     await limiter.throttle()  # or limiter.throttle_sync()
        ...     response = await api.call(request)
    """

    def __init__(
        self,
        requests_per_minute: float | None = None,
        requests_per_second: float | None = None,
    ):
        """
        Initialize the rate limiter.

        Args:
            requests_per_minute: Maximum requests per minute (mutually exclusive with requests_per_second).
            requests_per_second: Maximum requests per second (takes precedence).
        """
        if requests_per_second is not None:
            self._min_interval = 1.0 / requests_per_second
        elif requests_per_minute is not None:
            self._min_interval = 60.0 / requests_per_minute
        else:
            self._min_interval = 0.0

        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()
        self._sync_lock_time: float = 0.0

    @property
    def is_enabled(self) -> bool:
        """Check if rate limiting is enabled."""
        return self._min_interval > 0

    async def throttle(self) -> float:
        """
        Wait if necessary to respect rate limits.

        Returns:
            The time waited in seconds.
        """
        if not self.is_enabled:
            return 0.0

        async with self._lock:
            now = time.time()
            time_since_last = now - self._last_request_time

            if time_since_last < self._min_interval:
                wait_time = self._min_interval - time_since_last
                await asyncio.sleep(wait_time)
                self._last_request_time = time.time()
                return wait_time

            self._last_request_time = now
            return 0.0

    def throttle_sync(self) -> float:
        """
        Synchronous version of throttle.

        Returns:
            The time waited in seconds.
        """
        if not self.is_enabled:
            return 0.0

        now = time.time()
        time_since_last = now - self._sync_lock_time

        if time_since_last < self._min_interval:
            wait_time = self._min_interval - time_since_last
            time.sleep(wait_time)
            self._sync_lock_time = time.time()
            return wait_time

        self._sync_lock_time = now
        return 0.0

    def reset(self) -> None:
        """Reset the rate limiter state."""
        self._last_request_time = 0.0
        self._sync_lock_time = 0.0


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    wait_seconds: float = 1.0
    exponential_base: float = 2.0
    max_wait_seconds: float = 60.0
    jitter: bool = True
    jitter_factor: float = 0.1

    def get_wait_time(self, attempt: int) -> float:
        """
        Calculate wait time for a given attempt.

        Args:
            attempt: The attempt number (0-indexed).

        Returns:
            Wait time in seconds.
        """
        # Exponential backoff
        wait = self.wait_seconds * (self.exponential_base**attempt)

        # Cap at max wait
        wait = min(wait, self.max_wait_seconds)

        # Add jitter if enabled
        if self.jitter:
            jitter_range = wait * self.jitter_factor
            wait += random.uniform(-jitter_range, jitter_range)

        return max(0, wait)


class Retrying:
    """
    Retry mechanism with exponential backoff.

    Provides configurable retry logic for operations that may fail transiently.

    Example:
        >>> retrying = Retrying(max_attempts=3, wait_seconds=1.0)
        >>> result = await retrying(api_call, query="test")

        # Or as decorator:
        >>> @Retrying(max_attempts=3)
        ... async def my_api_call():
        ...     return await api.call()
    """

    def __init__(
        self,
        max_attempts: int = 3,
        wait_seconds: float = 1.0,
        exponential_base: float = 2.0,
        max_wait_seconds: float = 60.0,
        jitter: bool = True,
        retry_predicate: Callable[[Exception], bool] | None = None,
        on_retry: Callable[[Exception, int], None] | None = None,
    ):
        """
        Initialize the retry mechanism.

        Args:
            max_attempts: Maximum number of attempts (including first try).
            wait_seconds: Initial wait time between retries.
            exponential_base: Base for exponential backoff.
            max_wait_seconds: Maximum wait time between retries.
            jitter: Whether to add random jitter to wait times.
            retry_predicate: Function to determine if an error should trigger retry.
                            Defaults to is_transient_error.
            on_retry: Optional callback called before each retry.
        """
        self.config = RetryConfig(
            max_attempts=max_attempts,
            wait_seconds=wait_seconds,
            exponential_base=exponential_base,
            max_wait_seconds=max_wait_seconds,
            jitter=jitter,
        )
        self.retry_predicate = retry_predicate or is_transient_error
        self.on_retry = on_retry

    async def __call__(
        self,
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> T:
        """
        Execute a function with retry logic.

        Args:
            func: The function to execute (can be sync or async).
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The function's return value.

        Raises:
            The last exception if all retries fail.
        """
        last_exception: Exception | None = None

        for attempt in range(self.config.max_attempts):
            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result  # type: ignore[no-any-return]
                return result  # type: ignore[no-any-return]

            except Exception as e:
                last_exception = e

                # Check if we should retry
                if not self.retry_predicate(e):
                    raise

                # Check if we have retries left
                if attempt + 1 >= self.config.max_attempts:
                    raise

                # Calculate wait time
                wait_time = self.config.get_wait_time(attempt)

                # Call retry callback
                if self.on_retry:
                    self.on_retry(e, attempt + 1)

                logger.warning(
                    f"Retry {attempt + 1}/{self.config.max_attempts - 1}: "
                    f"{type(e).__name__}: {e}. Waiting {wait_time:.2f}s..."
                )

                await asyncio.sleep(wait_time)

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected state in retry logic")

    def call_sync(
        self,
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> T:
        """
        Synchronous version of __call__.

        Args:
            func: The function to execute (must be sync).
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The function's return value.
        """
        last_exception: Exception | None = None

        for attempt in range(self.config.max_attempts):
            try:
                return func(*args, **kwargs)

            except Exception as e:
                last_exception = e

                if not self.retry_predicate(e):
                    raise

                if attempt + 1 >= self.config.max_attempts:
                    raise

                wait_time = self.config.get_wait_time(attempt)

                if self.on_retry:
                    self.on_retry(e, attempt + 1)

                logger.warning(
                    f"Retry {attempt + 1}/{self.config.max_attempts - 1}: "
                    f"{type(e).__name__}: {e}. Waiting {wait_time:.2f}s..."
                )

                time.sleep(wait_time)

        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected state in retry logic")

    def wrap(self, func: Callable[..., T]) -> Callable[..., T]:
        """
        Wrap a function with retry logic.

        Args:
            func: The function to wrap.

        Returns:
            A wrapped function with retry logic.
        """
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await self(func, *args, **kwargs)

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                return self.call_sync(func, *args, **kwargs)

            return sync_wrapper


def retry(
    max_attempts: int = 3,
    wait_seconds: float = 1.0,
    exponential_base: float = 2.0,
    max_wait_seconds: float = 60.0,
    jitter: bool = True,
    retry_predicate: Callable[[Exception], bool] | None = None,
) -> Callable:
    """
    Decorator for adding retry logic to a function.

    Example:
        >>> @retry(max_attempts=3, wait_seconds=1.0)
        ... async def my_api_call():
        ...     return await api.call()

    Args:
        max_attempts: Maximum number of attempts.
        wait_seconds: Initial wait time between retries.
        exponential_base: Base for exponential backoff.
        max_wait_seconds: Maximum wait time.
        jitter: Whether to add jitter.
        retry_predicate: Function to determine if error is retryable.

    Returns:
        Decorator function.
    """
    retrying = Retrying(
        max_attempts=max_attempts,
        wait_seconds=wait_seconds,
        exponential_base=exponential_base,
        max_wait_seconds=max_wait_seconds,
        jitter=jitter,
        retry_predicate=retry_predicate,
    )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        return retrying.wrap(func)

    return decorator
