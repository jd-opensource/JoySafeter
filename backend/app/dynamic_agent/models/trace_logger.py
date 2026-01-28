"""
TraceLogger - JSONL debug logging for agent execution.

006: Single Subagent Clean Architecture
- TraceLogEntry: Individual log entry with parent-child relationships
- TraceLogger: Session-based JSONL file writer
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, TextIO

# Log directory
LOG_DIR = Path(__file__).parent.parent / "logs"

# Event types
EventType = Literal[
    "prompt", "tool_call", "tool_result", "summary", "error", "LLM_CALL", "LLM_RESPONSE", "TOOL_CALL", "ERROR"
]

# Level types
LevelType = Literal["main_agent", "subagent", "tool"]


@dataclass
class TraceLogEntry:
    """
    Individual trace log entry.

    Attributes:
        id: Unique entry identifier
        timestamp: ISO format timestamp
        session_id: Session identifier
        level: Agent level (main_agent, subagent, tool)
        event_type: Type of event
        content: Event content/data
        parent_id: Parent entry ID for tree structure
        duration_ms: Execution duration if applicable
    """

    id: str
    timestamp: str
    session_id: str
    level: LevelType
    event_type: EventType
    content: Dict[str, Any]
    parent_id: Optional[str] = None
    duration_ms: Optional[int] = None

    def to_jsonl(self) -> str:
        """
        Convert entry to JSONL format (single line JSON).

        Returns:
            JSON string without newlines
        """
        # Use compact format for viewer.html compatibility
        data: Dict[str, Any] = {
            "id": self.id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "level": self.level,
            "event_type": self.event_type,
            "data": self.content,  # Use 'data' key for viewer.html compatibility
        }
        if self.parent_id:
            data["parent_id"] = self.parent_id
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms

        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> "TraceLogEntry":
        """
        Parse JSONL line into TraceLogEntry.

        Args:
            line: Single JSON line

        Returns:
            TraceLogEntry instance
        """
        data = json.loads(line)
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            session_id=data.get("session_id", "unknown"),
            level=data.get("level", "main_agent"),
            event_type=data.get("event_type", "error"),
            content=data.get("data", data.get("content", {})),
            parent_id=data.get("parent_id"),
            duration_ms=data.get("duration_ms"),
        )


class TraceLogger:
    """
    Session-based JSONL trace logger.

    Creates and writes to `logs/{session_id}.jsonl` files.
    Supports hierarchical logging with parent-child relationships.
    """

    def __init__(self, session_id: str, log_dir: Optional[Path] = None):
        """
        Initialize TraceLogger.

        Args:
            session_id: Session identifier
            log_dir: Custom log directory (default: backend/agent/logs/)
        """
        self.session_id = session_id
        self.log_dir = log_dir or LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = self.log_dir / f"session_{session_id}.jsonl"
        self._file_handle: Optional[TextIO] = None
        self._entry_count = 0
        self._current_parent_id: Optional[str] = None

    def _ensure_open(self) -> None:
        """Ensure file handle is open."""
        if self._file_handle is None:
            self._file_handle = open(self.log_file, "a", encoding="utf-8")

    def log(
        self,
        level: LevelType,
        event_type: EventType,
        content: Dict[str, Any],
        parent_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> str:
        """
        Log an entry.

        Args:
            level: Agent level
            event_type: Event type
            content: Event content
            parent_id: Parent entry ID (for tree structure)
            duration_ms: Execution duration

        Returns:
            Entry ID
        """
        entry_id = f"{self.session_id[:8]}_{self._entry_count:04d}"
        self._entry_count += 1

        entry = TraceLogEntry(
            id=entry_id,
            timestamp=datetime.now().isoformat(),
            session_id=self.session_id,
            level=level,
            event_type=event_type,
            content=content,
            parent_id=parent_id or self._current_parent_id,
            duration_ms=duration_ms,
        )

        self._ensure_open()
        if self._file_handle is not None:
            self._file_handle.write(entry.to_jsonl() + "\n")
            self._file_handle.flush()

        return entry_id

    def set_parent(self, parent_id: Optional[str]) -> None:
        """Set current parent ID for subsequent entries."""
        self._current_parent_id = parent_id

    def clear_parent(self) -> None:
        """Clear current parent ID."""
        self._current_parent_id = None

    # Convenience methods

    def log_prompt(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        model: str = "unknown",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Log LLM prompt/call.

        Args:
            system_prompt: System prompt text
            messages: Conversation messages
            model: Model name
            temperature: Temperature setting
            max_tokens: Max tokens setting

        Returns:
            Entry ID
        """
        content: Dict[str, Any] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "model": model,
        }
        if temperature is not None:
            content["temperature"] = temperature
        if max_tokens is not None:
            content["max_tokens"] = max_tokens

        return self.log("main_agent", "LLM_CALL", content)

    def log_tool_call(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        phase: str = "execution",
        run_id: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> str:
        """
        Log tool call.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters
            phase: Execution phase
            run_id: Run identifier
            parent_id: Parent entry ID

        Returns:
            Entry ID
        """
        content = {
            "tool_name": tool_name,
            "input": tool_input,
            "phase": phase,
        }
        if run_id:
            content["run_id"] = run_id

        return self.log("tool", "TOOL_CALL", content, parent_id=parent_id)

    def log_tool_result(
        self,
        tool_name: str,
        output: Any,
        success: bool = True,
        duration_ms: Optional[int] = None,
        parent_id: Optional[str] = None,
    ) -> str:
        """
        Log tool result.

        Args:
            tool_name: Name of the tool
            output: Tool output
            success: Whether tool succeeded
            duration_ms: Execution duration
            parent_id: Parent entry ID

        Returns:
            Entry ID
        """
        content = {
            "tool_name": tool_name,
            "output": str(output)[:5000] if output else "",  # Truncate large outputs
            "success": success,
        }

        return self.log("tool", "TOOL_CALL", content, parent_id=parent_id, duration_ms=duration_ms)

    def log_llm_response(
        self,
        content_text: Optional[str],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        usage: Optional[Dict[str, int]] = None,
        parent_id: Optional[str] = None,
    ) -> str:
        """
        Log LLM response.

        Args:
            content_text: Response text content
            tool_calls: Tool calls in response
            usage: Token usage stats
            parent_id: Parent entry ID

        Returns:
            Entry ID
        """
        content: Dict[str, Any] = {}
        if content_text:
            content["content"] = content_text[:5000]  # Truncate
        if tool_calls:
            content["tool_calls"] = tool_calls
        if usage:
            content["usage"] = usage

        return self.log("main_agent", "LLM_RESPONSE", content, parent_id=parent_id)

    def log_summary(
        self,
        summary: str,
        success: bool,
        key_findings: Optional[List[str]] = None,
        duration_ms: Optional[int] = None,
        parent_id: Optional[str] = None,
    ) -> str:
        """
        Log subagent summary.

        Args:
            summary: Summary text
            success: Whether task succeeded
            key_findings: Key findings list
            duration_ms: Execution duration
            parent_id: Parent entry ID

        Returns:
            Entry ID
        """
        content = {
            "summary": summary,
            "success": success,
        }
        if key_findings:
            content["key_findings"] = key_findings

        return self.log("subagent", "summary", content, parent_id=parent_id, duration_ms=duration_ms)

    def log_error(
        self,
        error_type: str,
        message: str,
        stacktrace: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> str:
        """
        Log error.

        Args:
            error_type: Error type/class
            message: Error message
            stacktrace: Stack trace
            parent_id: Parent entry ID

        Returns:
            Entry ID
        """
        content = {
            "error_type": error_type,
            "message": message,
        }
        if stacktrace:
            content["stacktrace"] = stacktrace

        return self.log("main_agent", "ERROR", content, parent_id=parent_id)

    def close(self) -> None:
        """Close file handle."""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None

    def __enter__(self) -> "TraceLogger":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    @classmethod
    def get_or_create(cls, session_id: str) -> "TraceLogger":
        """
        Get or create a TraceLogger for a session.

        This is a simple factory method. For production use,
        consider implementing a registry/cache.

        Args:
            session_id: Session identifier

        Returns:
            TraceLogger instance
        """
        return cls(session_id)


# Global logger registry (simple implementation)
_loggers: Dict[str, TraceLogger] = {}


def get_trace_logger(session_id: str) -> TraceLogger:
    """
    Get or create a TraceLogger for a session.

    Args:
        session_id: Session identifier

    Returns:
        TraceLogger instance
    """
    if session_id not in _loggers:
        _loggers[session_id] = TraceLogger(session_id)
    return _loggers[session_id]


def close_trace_logger(session_id: str) -> None:
    """
    Close and remove a TraceLogger.

    Args:
        session_id: Session identifier
    """
    if session_id in _loggers:
        _loggers[session_id].close()
        del _loggers[session_id]
