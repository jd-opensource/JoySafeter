"""Logging interfaces and implementations."""

from typing import Any, Dict, List, Optional

import structlog

from app.dynamic_agent.agent_core.types import Message


class ConsoleLogger:
    """Simple console logger for development."""

    def __init__(self):
        """Initialize console logger."""
        self.logger = structlog.get_logger()

    def event(self, name: str, props: Optional[Dict[str, str]] = None) -> None:
        """Log an event."""
        self.logger.info("event", event_name=name, **(props or {}))

    def error(self, err: Exception) -> None:
        """Log an error."""
        self.logger.error("error", error=str(err), exc_info=True)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self.logger.info(message, **kwargs)

    def write_sidechain(self, path: str, messages: List[Message]) -> None:
        """Write sidechain log (no-op for console)."""
        pass


class StructuredLogger:
    """
    Structured logger with support for external services.

    Can integrate with Sentry, Statsig, or other observability platforms.
    """

    def __init__(self, sentry_dsn: Optional[str] = None, statsig_key: Optional[str] = None):
        """
        Initialize structured logger.

        Args:
            sentry_dsn: Sentry DSN for error tracking
            statsig_key: Statsig API key for events
        """
        self.logger = structlog.get_logger()
        self.sentry_dsn = sentry_dsn
        self.statsig_key = statsig_key

        # Initialize Sentry if DSN provided
        if sentry_dsn:
            try:
                import sentry_sdk

                sentry_sdk.init(dsn=sentry_dsn)
            except ImportError:
                self.logger.warning("sentry_sdk not installed, skipping Sentry init")

    def event(self, name: str, props: Optional[Dict[str, str]] = None) -> None:
        """Log an event."""
        self.logger.info("event", event_name=name, **(props or {}))

        # Send to Statsig if configured
        if self.statsig_key:
            self._send_to_statsig(name, props)

    def error(self, err: Exception) -> None:
        """Log an error."""
        self.logger.error("error", error=str(err), exc_info=True)

        # Send to Sentry if configured
        if self.sentry_dsn:
            try:
                import sentry_sdk

                sentry_sdk.capture_exception(err)
            except ImportError:
                pass

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self.logger.info(message, **kwargs)

    def write_sidechain(self, path: str, messages: List[Message]) -> None:
        """Write sidechain log to file."""
        try:
            import json
            from pathlib import Path

            Path(path).parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w") as f:
                json.dump([msg.model_dump() if hasattr(msg, "model_dump") else msg for msg in messages], f, indent=2)
        except Exception as e:
            self.logger.error("Failed to write sidechain log", error=str(e))

    def _send_to_statsig(self, event_name: str, props: Optional[Dict[str, str]]) -> None:
        """Send event to Statsig (placeholder)."""
        # In a real implementation, you would use the Statsig SDK
        pass


class NodeBridgeLogger:
    """
    Logger that bridges to Node.js via JSON-RPC.

    Sends log events back to Node.js for unified logging.
    """

    def __init__(self, send_to_node_callback):
        """
        Initialize Node bridge logger.

        Args:
            send_to_node_callback: Async function to send logs to Node
        """
        self.send_to_node = send_to_node_callback
        self.logger = structlog.get_logger()

    def event(self, name: str, props: Optional[Dict[str, str]] = None) -> None:
        """Log an event and send to Node."""
        self.logger.info("event", event_name=name, **(props or {}))

        try:
            # Send to Node asynchronously (fire and forget)
            import asyncio

            asyncio.create_task(self.send_to_node({"type": "event", "name": name, "props": props or {}}))
        except Exception:
            pass

    def error(self, err: Exception) -> None:
        """Log an error and send to Node."""
        self.logger.error("error", error=str(err), exc_info=True)

        try:
            import asyncio

            asyncio.create_task(self.send_to_node({"type": "error", "error": str(err)}))
        except Exception:
            pass

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self.logger.info(message, **kwargs)

    def write_sidechain(self, path: str, messages: List[Message]) -> None:
        """Delegate sidechain writing to Node."""
        try:
            import asyncio

            asyncio.create_task(
                self.send_to_node(
                    {
                        "type": "write_sidechain",
                        "path": path,
                        "messages": [msg.model_dump() if hasattr(msg, "model_dump") else msg for msg in messages],
                    }
                )
            )
        except Exception:
            pass
