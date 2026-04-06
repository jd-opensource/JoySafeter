"""
Langfuse callback handler for LLM observability.

Integrates Langfuse tracing with LangChain/LangGraph agents to track:
- LLM calls (prompts, responses, tokens, costs)
- Tool calls and results
- Agent execution traces
- User interactions
"""

import os
from typing import Any

from loguru import logger

try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    logger.warning("langfuse not installed. Langfuse tracing will be disabled.")


def get_langfuse_callbacks(enabled: bool = True, **kwargs: Any) -> list[Any]:
    """
    Get list of Langfuse callbacks for use with LangChain/LangGraph.

    Environment variables are automatically read from .env:
    - LANGFUSE_PUBLIC_KEY
    - LANGFUSE_SECRET_KEY
    - LANGFUSE_HOST (optional, defaults to https://cloud.langfuse.com)

    Returns a list that can be used in two ways:
    1. Via with_config: runnable.with_config({"callbacks": [...]})
    2. Via invoke: agent.invoke(..., config={"callbacks": [...]})

    Example:
        # Simple usage - environment variables from .env
        langfuse_handler = CallbackHandler()
        config = {
            "callbacks": [langfuse_handler],
            "configurable": {...}
        }
        result = graph.astream(input=initial_state, config=config)

    Args:
        enabled: Whether to enable Langfuse tracing
        **kwargs: Additional arguments (for backward compatibility, but not used)

    Returns:
        List of callback handlers (empty list if disabled or unavailable)
    """
    if not enabled:
        logger.debug("[langfuse] Langfuse tracing is disabled")
        return []

    if not LANGFUSE_AVAILABLE:
        logger.warning("[langfuse] Langfuse package not installed, skipping callback creation")
        return []

    # Check if environment variables are set
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    # Print configuration (mask sensitive keys)
    def _mask_key(k):
        return f"{k[:8]}...{k[-4:]}" if k and len(k) > 12 else "***" if k else None

    logger.info(
        f"[langfuse] Configuration: enabled={enabled}, "
        f"public_key={_mask_key(public_key)}, "
        f"secret_key={'***' if secret_key else None}, "
        f"host={host}"
    )

    if not public_key or not secret_key:
        logger.warning(
            "[langfuse] Langfuse keys not found in environment variables. "
            "Please set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env file"
        )
        return []

    try:
        # Create handler with trace_id from context for cross-system correlation
        from app.core.trace_context import get_trace_id

        trace_id = get_trace_id()
        handler = LangfuseCallbackHandler(
            trace_context={"trace_id": trace_id} if trace_id else None,
        )
        logger.info(f"[langfuse] Langfuse callback handler created successfully (host: {host})")
        return [handler]
    except Exception as e:
        logger.error(f"[langfuse] Failed to create Langfuse callback handler: {e}")
        return []
