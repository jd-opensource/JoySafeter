"""A2A (Agent-to-Agent) protocol client for calling remote A2A-compliant agents.

Production features:
- Long-running task polling (tasks/get)
- Retry with exponential backoff
- Connection pooling
- Structured logging
"""

from app.core.a2a.client import (
    A2AClientConfig,
    A2ASendResult,
    close_all_clients,
    get_task,
    resolve_a2a_url,
    send_message,
)

__all__ = [
    "A2AClientConfig",
    "A2ASendResult",
    "close_all_clients",
    "get_task",
    "resolve_a2a_url",
    "send_message",
]
