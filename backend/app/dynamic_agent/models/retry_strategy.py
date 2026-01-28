"""
Retry Strategy Model

Provides intelligent retry mechanism with:
- Error type classification
- Exponential backoff
- Payload/header adjustment suggestions
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

ErrorType = Literal["network", "auth", "param", "timeout", "unknown"]


# Error patterns for classification
ERROR_PATTERNS: Dict[ErrorType, List[str]] = {
    "network": [
        r"connection\s*(refused|reset|timeout)",
        r"network\s*(unreachable|error)",
        r"dns\s*(resolution|lookup)\s*failed",
        r"socket\s*(error|timeout)",
        r"econnrefused",
        r"enotfound",
        r"etimedout",
        r"no\s*route\s*to\s*host",
    ],
    "auth": [
        r"401\s*unauthorized",
        r"403\s*forbidden",
        r"authentication\s*(failed|required|error)",
        r"invalid\s*(token|credentials|password)",
        r"access\s*denied",
        r"permission\s*denied",
        r"login\s*(failed|required)",
        r"session\s*(expired|invalid)",
    ],
    "param": [
        r"400\s*bad\s*request",
        r"422\s*unprocessable",
        r"invalid\s*(parameter|argument|input|value)",
        r"missing\s*(required|parameter|field)",
        r"validation\s*(error|failed)",
        r"malformed\s*(request|data|json)",
    ],
    "timeout": [
        r"timeout",
        r"timed?\s*out",
        r"504\s*gateway\s*timeout",
        r"request\s*timeout",
        r"read\s*timeout",
        r"connect\s*timeout",
    ],
}


def classify_error(error_message: str) -> ErrorType:
    """
    Classify error message into error type.

    Args:
        error_message: The error message to classify

    Returns:
        ErrorType: One of network, auth, param, timeout, unknown
    """
    if not error_message:
        return "unknown"

    error_lower = error_message.lower()

    for error_type, patterns in ERROR_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, error_lower):
                return error_type

    return "unknown"


@dataclass
class RetryAdjustment:
    """Suggested adjustment for retry attempt."""

    type: str  # header, payload, method, etc.
    action: str  # add, modify, remove
    key: str
    value: Optional[str] = None
    reason: str = ""


@dataclass
class RetryStrategy:
    """
    Retry strategy for a specific error type.

    Defines retry behavior including:
    - Maximum retry attempts
    - Backoff timing
    - Suggested adjustments
    """

    error_type: ErrorType
    max_retries: int = 3
    base_delay_ms: int = 1000
    backoff_multiplier: float = 2.0
    adjustments: List[RetryAdjustment] = field(default_factory=list)

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay for given attempt number (0-indexed).

        Uses exponential backoff: base_delay * (multiplier ^ attempt)

        Returns:
            Delay in seconds
        """
        delay_ms = self.base_delay_ms * (self.backoff_multiplier**attempt)
        return delay_ms / 1000

    def should_retry(self, attempt: int) -> bool:
        """Check if another retry should be attempted."""
        return attempt < self.max_retries

    def get_adjustment_suggestions(self) -> List[str]:
        """Get human-readable adjustment suggestions."""
        return [f"{adj.action.capitalize()} {adj.type} '{adj.key}': {adj.reason}" for adj in self.adjustments]


# Predefined retry strategies for each error type
# Note: adjustments are kept generic - Agent should analyze and decide specifics
RETRY_STRATEGIES: Dict[ErrorType, RetryStrategy] = {
    "network": RetryStrategy(
        error_type="network",
        max_retries=3,
        base_delay_ms=2000,
        backoff_multiplier=2.0,
        adjustments=[],  # Agent should analyze network errors
    ),
    "auth": RetryStrategy(
        error_type="auth",
        max_retries=2,
        base_delay_ms=500,
        backoff_multiplier=1.5,
        adjustments=[],  # Agent should analyze auth errors
    ),
    "param": RetryStrategy(
        error_type="param",
        max_retries=3,
        base_delay_ms=100,
        backoff_multiplier=1.0,  # No backoff for param errors
        adjustments=[],  # Agent should analyze param errors
    ),
    "timeout": RetryStrategy(
        error_type="timeout",
        max_retries=2,
        base_delay_ms=5000,
        backoff_multiplier=2.0,
        adjustments=[],  # Agent should analyze timeout errors
    ),
    "unknown": RetryStrategy(
        error_type="unknown",
        max_retries=1,
        base_delay_ms=1000,
        backoff_multiplier=2.0,
        adjustments=[],  # Agent should analyze unknown errors
    ),
}


def get_retry_strategy(error_message: str) -> RetryStrategy:
    """
    Get appropriate retry strategy for an error message.

    Args:
        error_message: The error message

    Returns:
        RetryStrategy for the classified error type
    """
    error_type = classify_error(error_message)
    return RETRY_STRATEGIES[error_type]


def generate_adjustments(error_type: ErrorType) -> List[RetryAdjustment]:
    """
    Generate specific adjustment suggestions based on error type.

    Args:
        error_type: The classified error type

    Returns:
        List of RetryAdjustment suggestions
    """
    if error_type == "auth":
        return [
            RetryAdjustment(
                type="header", action="add", key="Cookie", reason="Include session cookie from previous login"
            ),
            RetryAdjustment(type="header", action="add", key="Authorization", reason="Add auth token if available"),
            RetryAdjustment(
                type="flow",
                action="check",
                key="login_status",
                reason="Verify login was successful before accessing protected resource",
            ),
        ]
    elif error_type == "param":
        return [
            RetryAdjustment(
                type="payload", action="modify", key="format", reason="Try different encoding (form-urlencoded vs JSON)"
            ),
            RetryAdjustment(
                type="payload",
                action="modify",
                key="content-type",
                reason="Adjust Content-Type header to match payload format",
            ),
            RetryAdjustment(type="method", action="try", key="POST/GET", reason="Try alternative HTTP method"),
        ]
    elif error_type == "network":
        return [
            RetryAdjustment(type="target", action="verify", key="host:port", reason="Confirm target is reachable"),
            RetryAdjustment(type="timeout", action="increase", key="value", reason="Increase request timeout"),
        ]
    elif error_type == "timeout":
        return [
            RetryAdjustment(type="timeout", action="increase", key="value", reason="Double the timeout value"),
            RetryAdjustment(type="request", action="simplify", key="payload", reason="Reduce payload size if possible"),
        ]
    else:  # unknown
        return [
            RetryAdjustment(
                type="general", action="check", key="target_service", reason="Verify target service is available"
            ),
            RetryAdjustment(
                type="general", action="verify", key="request_params", reason="Double-check all request parameters"
            ),
        ]


def generate_error_report(
    error_message: str,
    attempts: int,
    error_history: List[str],
) -> str:
    """
    Generate detailed error report after max retries exhausted.

    Args:
        error_message: Final error message
        attempts: Number of attempts made
        error_history: List of error messages from each attempt

    Returns:
        Formatted error report string
    """
    error_type = classify_error(error_message)
    strategy = RETRY_STRATEGIES[error_type]

    lines = [
        "## ❌ Retry Failure Report",
        "",
        f"**Error Type**: {error_type}",
        f"**Attempts**: {attempts}/{strategy.max_retries}",
        f"**Final Error**: {error_message}",
        "",
        "### Error History",
        "",
    ]

    for i, err in enumerate(error_history, 1):
        lines.append(f"{i}. {err}")

    lines.extend(
        [
            "",
            "### Suggested Actions",
            "",
        ]
    )

    suggestions = strategy.get_adjustment_suggestions()
    if suggestions:
        for suggestion in suggestions:
            lines.append(f"- {suggestion}")
    else:
        lines.append("- Check if target service is available")
        lines.append("- Verify request parameters are correct")

    return "\n".join(lines)
