"""
Langfuse callback handler for LLM observability.

Integrates Langfuse tracing with LangChain/LangGraph agents to track:
- LLM calls (prompts, responses, tokens, costs)
- Tool calls and results
- Agent execution traces
- User interactions
"""

import os
from typing import Any, Dict, Optional

from loguru import logger

try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    logger.warning("langfuse not installed. Langfuse tracing will be disabled.")


def create_langfuse_callback(
    public_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    host: Optional[str] = None,
    enabled: bool = True,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs: Any,
) -> Optional[Any]:
    """
    Create a Langfuse callback handler for LangChain/LangGraph.

    Args:
        public_key: Langfuse public key
        secret_key: Langfuse secret key (for langfuse 3.x, set via LANGFUSE_SECRET_KEY env var)
        host: Langfuse host URL (for langfuse 3.x, set via LANGFUSE_HOST env var)
        enabled: Whether to enable Langfuse tracing
        session_id: Session ID for tracking conversations
        user_id: User ID for tracking user interactions
        **kwargs: Additional arguments passed to LangfuseCallbackHandler

    Returns:
        LangfuseCallbackHandler instance if enabled and keys are provided, None otherwise
    """

    # Print configuration parameters
    def _mask_key(k):
        return f"{k[:8]}...{k[-4:]}" if k and len(k) > 12 else "***" if k else None

    logger.info(
        f"[langfuse] Configuration: enabled={enabled}, "
        f"public_key={_mask_key(public_key or os.getenv('LANGFUSE_PUBLIC_KEY'))}, "
        f"secret_key={'***' if (secret_key or os.getenv('LANGFUSE_SECRET_KEY')) else None}, "
        f"host={host or os.getenv('LANGFUSE_HOST', 'https://cloud.langfuse.com')}, "
        f"session_id={session_id}, user_id={user_id}"
    )

    if not enabled:
        logger.debug("[langfuse] Langfuse tracing is disabled")
        return None

    if not LANGFUSE_AVAILABLE:
        logger.warning("[langfuse] Langfuse package not installed, skipping callback creation")
        return None

    # For langfuse 3.x, secret_key and host are set via environment variables
    # Set them if provided as parameters
    if secret_key:
        os.environ["LANGFUSE_SECRET_KEY"] = secret_key
    if host:
        os.environ["LANGFUSE_HOST"] = host

    # Check if keys are available (either via parameter or env var)
    effective_public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
    effective_secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY")

    if not effective_public_key or not effective_secret_key:
        logger.warning("[langfuse] Langfuse keys not provided, skipping callback creation")
        return None

    try:
        # For langfuse 3.x, CallbackHandler only needs public_key
        # secret_key and host are set via environment variables
        handler_kwargs = {"public_key": effective_public_key}

        # Add trace_context if session_id or user_id provided
        trace_context: Dict[str, str] = {}
        if session_id:
            trace_context["session_id"] = session_id
        if user_id:
            trace_context["user_id"] = user_id
        if trace_context:
            handler_kwargs["trace_context"] = trace_context  # type: ignore[assignment]

        # Merge with any additional kwargs
        handler_kwargs.update(kwargs)

        handler = LangfuseCallbackHandler(**handler_kwargs)  # type: ignore[arg-type]
        effective_host = host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        logger.info(f"[langfuse] Langfuse callback handler created successfully (host: {effective_host})")
        return handler
    except Exception as e:
        logger.error(f"[langfuse] Failed to create Langfuse callback handler: {e}")
        return None


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
        # Create handler - environment variables are automatically read
        handler = LangfuseCallbackHandler()
        logger.info(f"[langfuse] Langfuse callback handler created successfully (host: {host})")
        return [handler]
    except Exception as e:
        logger.error(f"[langfuse] Failed to create Langfuse callback handler: {e}")
        return []


def set_langfuse_trace_metadata(
    trace_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Set metadata for the current Langfuse trace.

    This should be called at the start of a request/conversation to set context.

    Note: In langfuse 3.x, trace metadata is typically set via trace_context
    when creating the CallbackHandler, not via this function.

    Args:
        trace_id: Optional trace ID (if None, uses current trace)
        user_id: User ID
        session_id: Session ID
        metadata: Additional metadata dictionary
    """
    if not LANGFUSE_AVAILABLE:
        return

    try:
        # For langfuse 3.x, use the Langfuse client to update trace metadata
        from langfuse import Langfuse

        client = Langfuse()
        if hasattr(client, "update_current_trace"):
            # Update trace with available parameters
            update_kwargs: Dict[str, Any] = {}
            if trace_id:
                update_kwargs["trace_id"] = trace_id  # type: ignore[dict-item]
            if user_id:
                update_kwargs["user_id"] = user_id
            if session_id:
                update_kwargs["session_id"] = session_id
            if metadata:
                update_kwargs["metadata"] = metadata
            if update_kwargs:
                client.update_current_trace(**update_kwargs)  # type: ignore[call-arg]
        else:
            # Fallback: metadata should be set via trace_context when creating handler
            logger.debug("[langfuse] Trace metadata should be set via trace_context in CallbackHandler")
    except Exception as e:
        logger.debug(f"[langfuse] Failed to set trace metadata: {e}")
