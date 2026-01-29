"""
Global metadata context management for agent tool calls.

This module provides a thread-safe way to pass metadata through the entire
agent execution chain, making it accessible to all tools without explicit
parameter passing.

Usage:
    # Set metadata before agent execution
    MetadataContext.set({"session_id": "123", "user_id": "user1"})

    try:
        # Execute agent
        result = await agent.ainvoke(...)
    finally:
        # Always clear metadata
        MetadataContext.clear()

    # In tools, access metadata
    @tool
    def my_tool(input_str: str) -> str:
        metadata = MetadataContext.get()
        session_id = metadata.get("session_id") if metadata else None
        return result
"""

import contextvars
from typing import Any, Dict, Optional

from loguru import logger

# Thread-safe context variable for metadata
_metadata_context: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "metadata_context", default=None
)


class MetadataContext:
    """
    Global context manager for metadata propagation through agent execution.

    Uses Python's contextvars for thread-safe and async-safe storage.
    """

    @staticmethod
    def set(metadata: Dict[str, Any]) -> None:
        """
        Set metadata for the current execution context.

        Args:
            metadata: Dictionary containing metadata (session_id, user_id, etc.)

        Example:
            MetadataContext.set({
                "session_id": "session_123",
                "user_id": "user_456",
                "scenario": "web_reconnaissance"
            })
        """
        if not isinstance(metadata, dict):
            logger.warning(f"Metadata should be a dict, got {type(metadata)}")
            return

        _metadata_context.set(metadata)
        logger.debug(f"Metadata context set: {list(metadata.keys())}")

    @staticmethod
    def get() -> Optional[Dict[str, Any]]:
        """
        Get metadata from the current execution context.

        Returns:
            Dictionary containing metadata, or None if not set

        Example:
            metadata = MetadataContext.get()
            session_id = metadata.get("session_id") if metadata else None
        """
        return _metadata_context.get()

    @staticmethod
    def get_value(key: str, default: Any = None) -> Any:
        """
        Get a specific value from metadata.

        Args:
            key: Key to retrieve
            default: Default value if key not found

        Returns:
            Value from metadata or default

        Example:
            session_id = MetadataContext.get_value("session_id", "unknown")
        """
        metadata = _metadata_context.get()
        if metadata is None:
            return default
        return metadata.get(key, default)

    @staticmethod
    def clear() -> None:
        """
        Clear metadata from the current execution context.

        Should always be called in a finally block to prevent context leaks.

        Example:
            try:
                MetadataContext.set(metadata)
                # Execute agent
            finally:
                MetadataContext.clear()
        """
        _metadata_context.set(None)
        logger.debug("Metadata context cleared")

    @staticmethod
    def update(updates: Dict[str, Any]) -> None:
        """
        Update metadata with new values.

        Args:
            updates: Dictionary with values to update

        Example:
            MetadataContext.update({"status": "completed"})
        """
        metadata = _metadata_context.get()
        if metadata is None:
            metadata = {}

        metadata.update(updates)
        _metadata_context.set(metadata)
        logger.debug(f"Metadata context updated: {list(updates.keys())}")

    @staticmethod
    def has_key(key: str) -> bool:
        """
        Check if a key exists in metadata.

        Args:
            key: Key to check

        Returns:
            True if key exists, False otherwise
        """
        metadata = _metadata_context.get()
        return metadata is not None and key in metadata

    @staticmethod
    def to_dict() -> Dict[str, Any]:
        """
        Get a copy of the entire metadata dictionary.

        Returns:
            Copy of metadata dictionary, or empty dict if not set
        """
        metadata = _metadata_context.get()
        return dict(metadata) if metadata else {}


import queue  # noqa: E402


def write_messages(messages: list[str]) -> None:
    """Write intermediate messages to response queue during execution"""
    from typing import Any

    metas = MetadataContext.get()
    if metas:
        q_raw = metas.get("response_queue")
        if q_raw is not None and isinstance(q_raw, queue.Queue):
            q: queue.Queue[Any] = q_raw
            for m in messages:
                q.put(
                    {
                        "status": "success",
                        "type": "intermediate",
                        # "data": f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]}{m}'
                        "data": m,
                    }
                )
