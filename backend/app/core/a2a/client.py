"""A2A protocol client: message/send, tasks/get and Task parsing.

Reference: https://google.github.io/A2A/specification/
Example: https://raw.githubusercontent.com/langchain-samples/A2A-google-adk/refs/heads/main/test_agent_conversation.py

Production features:
- Long-running task polling (tasks/get)
- Retry with exponential backoff
- Connection pooling
- Structured logging with context
- Optional Langfuse tracing (via trace_id in extra)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from loguru import logger

LOG_PREFIX = "[A2A]"

# ==================== Configuration ====================


@dataclass
class A2AClientConfig:
    """Global A2A client configuration."""

    # Timeout settings
    connect_timeout: float = 10.0
    read_timeout: float = 120.0
    write_timeout: float = 30.0

    # Retry settings
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    retry_exponential_base: float = 2.0

    # Polling settings (for long-running tasks)
    poll_interval: float = 2.0
    max_poll_attempts: int = 60  # 60 * 2s = 2 minutes max

    # Connection pool
    max_connections: int = 10
    max_keepalive_connections: int = 5


# Default config instance
DEFAULT_CONFIG = A2AClientConfig()

# ==================== Connection Pool ====================

_client_pool: dict[str, httpx.AsyncClient] = {}


def _get_client(base_url: str, config: A2AClientConfig = DEFAULT_CONFIG) -> httpx.AsyncClient:
    """Get or create a pooled async client for the given base URL."""
    # Normalize URL for pool key
    pool_key = base_url.rstrip("/").split("://")[-1].split("/")[0]  # Extract host

    if pool_key not in _client_pool:
        _client_pool[pool_key] = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=config.connect_timeout,
                read=config.read_timeout,
                write=config.write_timeout,
                pool=config.connect_timeout,
            ),
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive_connections,
            ),
        )
    return _client_pool[pool_key]


async def close_all_clients():
    """Close all pooled clients. Call on shutdown."""
    for client in _client_pool.values():
        await client.aclose()
    _client_pool.clear()


# ==================== Result Types ====================


@dataclass
class A2ASendResult:
    """Result of a message/send or tasks/get call."""

    ok: bool
    text: str
    task_id: Optional[str] = None
    context_id: Optional[str] = None
    state: Optional[str] = None  # Task state (completed, working, failed, etc.)
    error: Optional[str] = None
    duration_ms: int = 0
    raw_result: Optional[dict] = field(default=None, repr=False)  # Full result for debugging


async def resolve_a2a_url(
    agent_card_url: str,
    auth_headers: Optional[dict[str, str]] = None,
    config: A2AClientConfig = DEFAULT_CONFIG,
) -> str:
    """Resolve A2A base URL from an Agent Card URL.

    Fetches the Agent Card JSON and returns the 'url' field (A2A service endpoint).
    """
    client = _get_client(agent_card_url, config)
    headers = dict(auth_headers or {})
    try:
        resp = await client.get(agent_card_url, headers=headers or None)
        resp.raise_for_status()
        card = resp.json()
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Failed to fetch Agent Card: HTTP {e.response.status_code}") from e
    except Exception as e:
        raise ValueError(f"Failed to fetch Agent Card: {e}") from e

    url = card.get("url")
    if not url or not isinstance(url, str):
        raise ValueError(f"Agent Card missing or invalid 'url': {agent_card_url}")
    result: str = url.rstrip("/")
    return result


def _extract_text_from_task(result: dict[str, Any]) -> str:
    """Extract agent reply text from A2A Task result."""
    artifacts = result.get("artifacts") or []
    if not artifacts:
        # Fallback: status.message may contain text
        status = result.get("status") or {}
        msg = status.get("message") or {}
        parts = (msg.get("parts") or []) if isinstance(msg, dict) else []
        for p in parts:
            if isinstance(p, dict) and p.get("kind") == "text":
                return (p.get("text") or "").strip()
        return ""
    first = artifacts[0] if isinstance(artifacts[0], dict) else {}
    parts = first.get("parts") or []
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "text":
            return (p.get("text") or "").strip()
    return ""


def _task_state_terminal(state: str) -> bool:
    """Check if task state is terminal (no more updates expected)."""
    terminal = ("completed", "canceled", "failed", "rejected", "unknown")
    return (state or "").lower() in terminal


def _is_retryable_error(e: Exception) -> bool:
    """Check if an error is retryable (network issues, 5xx, etc.)."""
    if isinstance(e, httpx.TimeoutException):
        return True
    if isinstance(e, httpx.ConnectError):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code >= 500
    return False


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json: Optional[dict] = None,
    headers: Optional[dict] = None,
    config: A2AClientConfig = DEFAULT_CONFIG,
) -> httpx.Response:
    """Make HTTP request with exponential backoff retry."""
    last_error: Optional[Exception] = None

    for attempt in range(config.max_retries + 1):
        try:
            if method.upper() == "POST":
                resp = await client.post(url, json=json, headers=headers)
            else:
                resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_error = e
            if not _is_retryable_error(e) or attempt >= config.max_retries:
                raise
            # Exponential backoff
            delay = min(
                config.retry_base_delay * (config.retry_exponential_base**attempt),
                config.retry_max_delay,
            )
            logger.warning(
                f"{LOG_PREFIX} Request failed (attempt {attempt + 1}/{config.max_retries + 1}), "
                f"retrying in {delay:.1f}s: {e}"
            )
            await asyncio.sleep(delay)

    # Should not reach here, but just in case
    raise last_error or RuntimeError("Request failed after retries")


async def get_task(
    url: str,
    task_id: str,
    *,
    auth_headers: Optional[dict[str, str]] = None,
    config: A2AClientConfig = DEFAULT_CONFIG,
) -> A2ASendResult:
    """Query task status via tasks/get (JSON-RPC 2.0).

    Args:
        url: A2A Server base URL.
        task_id: Task ID to query.
        auth_headers: Optional HTTP headers.
        config: Client configuration.

    Returns:
        A2ASendResult with current task state and text.
    """
    start_time = time.monotonic()
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tasks/get",
        "params": {"id": task_id},
    }

    post_url = url.rstrip("/")
    if not post_url.startswith(("http://", "https://")):
        return A2ASendResult(ok=False, text="", error=f"Invalid A2A URL: {url}")

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth_headers:
        headers.update(auth_headers)

    client = _get_client(url, config)

    try:
        resp = await _request_with_retry(client, "POST", post_url, json=payload, headers=headers, config=config)
        data = resp.json()
    except httpx.HTTPStatusError as e:
        err = f"HTTP {e.response.status_code}: {e.response.text[:200] if e.response.text else ''}"
        logger.warning(f"{LOG_PREFIX} tasks/get failed: {err}", task_id=task_id)
        return A2ASendResult(ok=False, text="", error=err, duration_ms=int((time.monotonic() - start_time) * 1000))
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} tasks/get error: {e}", task_id=task_id)
        return A2ASendResult(ok=False, text="", error=str(e), duration_ms=int((time.monotonic() - start_time) * 1000))

    duration_ms = int((time.monotonic() - start_time) * 1000)

    if "error" in data:
        err_obj = data["error"]
        err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
        return A2ASendResult(ok=False, text="", error=err_msg, duration_ms=duration_ms)

    result = data.get("result")
    if result is None:
        return A2ASendResult(ok=False, text="", error="Response missing 'result'", duration_ms=duration_ms)

    task_id_out = result.get("id") if isinstance(result, dict) else None
    context_id_out = result.get("contextId") if isinstance(result, dict) else None
    status = result.get("status") or {} if isinstance(result, dict) else {}
    state = status.get("state") if isinstance(status, dict) else "unknown"
    text_out = _extract_text_from_task(result)

    return A2ASendResult(
        ok=True,
        text=text_out,
        task_id=task_id_out,
        context_id=context_id_out,
        state=state,
        duration_ms=duration_ms,
        raw_result=result,
    )


async def send_message(
    url: str,
    text: str,
    *,
    context_id: Optional[str] = None,
    task_id: Optional[str] = None,
    auth_headers: Optional[dict[str, str]] = None,
    config: A2AClientConfig = DEFAULT_CONFIG,
    wait_for_completion: bool = True,
) -> A2ASendResult:
    """Send a message to an A2A Server via message/send (JSON-RPC 2.0).

    Production features:
    - Automatic retry with exponential backoff
    - Long-running task polling (tasks/get)
    - Connection pooling
    - Structured logging

    Args:
        url: A2A Server base URL (e.g. from Agent Card or config).
        text: User message text to send.
        context_id: Optional context ID for multi-turn.
        task_id: Optional task ID for follow-up.
        auth_headers: Optional HTTP headers (e.g. Authorization).
        config: Client configuration (timeouts, retries, polling).
        wait_for_completion: If True, poll until task reaches terminal state.

    Returns:
        A2ASendResult with ok, text, task_id, context_id, state, or error.
    """
    start_time = time.monotonic()
    request_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    message: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": message_id,
        "kind": "message",
    }
    if context_id:
        message["contextId"] = context_id
    if task_id:
        message["taskId"] = task_id

    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": message,
            "messageId": message_id,
        },
    }

    post_url = url.rstrip("/")
    if not post_url.startswith(("http://", "https://")):
        return A2ASendResult(ok=False, text="", error=f"Invalid A2A URL: {url}")

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth_headers:
        headers.update(auth_headers)

    client = _get_client(url, config)

    # Log request (structured) - compatible with Langfuse via trace_id
    logger.info(
        f"{LOG_PREFIX} message/send request",
        extra={
            "a2a_url": post_url,
            "request_id": request_id,
            "context_id": context_id,
            "task_id": task_id,
            "text_length": len(text),
            "span_type": "a2a_send",  # For tracing integration
        },
    )

    try:
        resp = await _request_with_retry(client, "POST", post_url, json=payload, headers=headers, config=config)
        data = resp.json()
    except httpx.HTTPStatusError as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        err = f"HTTP {e.response.status_code}: {e.response.text[:200] if e.response.text else ''}"
        logger.warning(
            f"{LOG_PREFIX} message/send failed",
            extra={"a2a_url": post_url, "error": err, "duration_ms": duration_ms},
        )
        return A2ASendResult(ok=False, text="", error=err, duration_ms=duration_ms)
    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning(
            f"{LOG_PREFIX} message/send error",
            extra={"a2a_url": post_url, "error": str(e), "duration_ms": duration_ms},
        )
        return A2ASendResult(ok=False, text="", error=str(e), duration_ms=duration_ms)

    if "error" in data:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        err_obj = data["error"]
        err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
        logger.warning(
            f"{LOG_PREFIX} message/send JSON-RPC error",
            extra={"a2a_url": post_url, "error": err_msg, "duration_ms": duration_ms},
        )
        return A2ASendResult(ok=False, text="", error=err_msg, duration_ms=duration_ms)

    result = data.get("result")
    if result is None:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return A2ASendResult(ok=False, text="", error="Response missing 'result'", duration_ms=duration_ms)

    # Parse initial result
    task_id_out = result.get("id") if isinstance(result, dict) else None
    context_id_out = result.get("contextId") if isinstance(result, dict) else None
    status = result.get("status") or {} if isinstance(result, dict) else {}
    state_raw = status.get("state") if isinstance(status, dict) else "unknown"
    state: str = str(state_raw) if state_raw else "unknown"
    text_out = _extract_text_from_task(result)

    # Poll for completion if task is not terminal
    if wait_for_completion and not _task_state_terminal(state) and task_id_out:
        logger.info(
            f"{LOG_PREFIX} Task not terminal (state={state}), starting polling",
            extra={"task_id": task_id_out, "a2a_url": post_url},
        )

        for poll_attempt in range(config.max_poll_attempts):
            await asyncio.sleep(config.poll_interval)

            poll_result = await get_task(url, task_id_out, auth_headers=auth_headers, config=config)

            if not poll_result.ok:
                logger.warning(
                    f"{LOG_PREFIX} Poll attempt {poll_attempt + 1} failed: {poll_result.error}",
                    extra={"task_id": task_id_out},
                )
                continue

            state = poll_result.state or "unknown"
            if _task_state_terminal(state):
                text_out = poll_result.text
                context_id_out = poll_result.context_id or context_id_out
                logger.info(
                    f"{LOG_PREFIX} Task reached terminal state",
                    extra={"task_id": task_id_out, "state": state, "poll_attempts": poll_attempt + 1},
                )
                break

            logger.debug(
                f"{LOG_PREFIX} Poll attempt {poll_attempt + 1}: state={state}",
                extra={"task_id": task_id_out},
            )
        else:
            # Max polls reached without terminal state
            logger.warning(
                f"{LOG_PREFIX} Max poll attempts reached, returning partial result",
                extra={"task_id": task_id_out, "state": state, "max_polls": config.max_poll_attempts},
            )

    duration_ms = int((time.monotonic() - start_time) * 1000)

    logger.info(
        f"{LOG_PREFIX} message/send completed",
        extra={
            "a2a_url": post_url,
            "task_id": task_id_out,
            "context_id": context_id_out,
            "state": state,
            "duration_ms": duration_ms,
            "text_length": len(text_out) if text_out else 0,
        },
    )

    return A2ASendResult(
        ok=True,
        text=text_out or "(no text in response)",
        task_id=task_id_out,
        context_id=context_id_out,
        state=state,
        duration_ms=duration_ms,
        raw_result=result,
    )
