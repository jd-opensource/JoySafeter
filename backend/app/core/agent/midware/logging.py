"""Logging middleware - Provide comprehensive operation logs and audit trails."""

import json
import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    pass

from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware.types import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from typing_extensions import NotRequired


class LoggingState(AgentState):
    """State for the logging middleware."""

    session_id: NotRequired[str]  # type: ignore[valid-type]
    """Session ID."""

    log_config: NotRequired[Dict[str, Any]]  # type: ignore[valid-type]
    """Log configuration."""

    interaction_count: NotRequired[int]  # type: ignore[valid-type]
    """Interaction count."""

    session_start_time: NotRequired[float]  # type: ignore[valid-type]
    """Session start time."""

    last_activity: NotRequired[float]  # type: ignore[valid-type]
    """Last activity time."""


class LoggingMiddleware(AgentMiddleware):
    """Logging middleware.

    Provide comprehensive operation logging:
    - Conversation history
    - Tool call logs
    - Performance metrics
    - Error tracking
    - User behavior analysis
    - Session statistics
    """

    state_schema = LoggingState

    def __init__(
        self,
        *,
        backend: BackendProtocol,
        log_path: str = "/logs/",
        session_id: Optional[str] = None,
        enable_conversation_logging: bool = True,
        enable_tool_logging: bool = True,
        enable_performance_logging: bool = True,
        enable_error_logging: bool = True,
        log_level: str = "INFO",
        max_log_files: int = 10,
        max_file_size: int = 10 * 1024 * 1024,  # 10MB
        rotate_interval: int = 24,  # hours
    ) -> None:
        """Initialize the logging middleware."""
        self.backend = backend
        self.log_path = log_path.rstrip("/") + "/"
        self.session_id = session_id or self._generate_session_id()
        self.enable_conversation_logging = enable_conversation_logging
        self.enable_tool_logging = enable_tool_logging
        self.enable_performance_logging = enable_performance_logging
        self.enable_error_logging = enable_error_logging
        self.log_level = getattr(logging, log_level.upper())
        self.max_log_files = max_log_files
        self.max_file_size = max_file_size
        self.rotate_interval = rotate_interval

        # log file paths
        self.conversation_log_path = f"{self.log_path}conversations/{self.session_id}.jsonl"
        self.tool_log_path = f"{self.log_path}tools/{self.session_id}.jsonl"
        self.performance_log_path = f"{self.log_path}performance/{self.session_id}.jsonl"
        self.error_log_path = f"{self.log_path}errors/{self.session_id}.jsonl"

        # initialize log directories
        self._init_log_directories()

    def _generate_session_id(self) -> str:
        """Generate a session ID."""
        import uuid

        return str(uuid.uuid4())[:12]

    def _init_log_directories(self) -> None:
        """Initialize log directories."""
        directories = [
            f"{self.log_path}conversations",
            f"{self.log_path}tools",
            f"{self.log_path}performance",
            f"{self.log_path}errors",
            f"{self.log_path}sessions",
        ]

        for directory in directories:
            try:
                self.backend.write(f"{directory}/.gitkeep", "")
            except Exception as e:
                print(f"Warning: Failed to initialize log directory {directory}: {e}")

    def _write_log_entry(self, log_path: str, entry: Dict[str, Any]) -> None:
        """Write a log entry."""
        try:
            # add timestamp
            entry["timestamp"] = datetime.now().isoformat()
            entry["session_id"] = self.session_id

            # write log
            log_line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
            try:
                # check if file exists and read existing content (BackendProtocol extension may have exists)
                existing_content = ""
                exists_fn = getattr(self.backend, "exists", None)
                if exists_fn is not None and callable(exists_fn) and exists_fn(log_path):
                    existing_content = self.backend.read(log_path) or ""

                # add new line
                new_content = existing_content + log_line + "\n"
                self.backend.write(log_path, new_content)
            except Exception:
                # if append fails, try writing directly
                self.backend.write(log_path, log_line + "\n")
        except Exception as e:
            print(f"Warning: Failed to write log entry to {log_path}: {e}")

    def _log_conversation_entry(self, entry_type: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Log a conversation entry."""
        if not self.enable_conversation_logging:
            return

        entry = {
            "type": entry_type,
            "content": content,
            "metadata": metadata or {},
            "length": len(content),
        }

        self._write_log_entry(self.conversation_log_path, entry)

    def _log_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any = None,
        execution_time: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log a tool call."""
        if not self.enable_tool_logging:
            return

        entry = {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "result_type": type(result).__name__ if result else "None",
            "execution_time_seconds": execution_time,
            "error": error,
            "success": error is None,
        }

        # if result is large, log only a summary
        if result and len(str(result)) > 1000:
            entry["result_summary"] = f"{type(result).__name__} object, size: {len(str(result))} chars"
        else:
            entry["result"] = result

        self._write_log_entry(self.tool_log_path, entry)

    def _log_performance_metrics(self, operation: str, metrics: Dict[str, Any]) -> None:
        """Log performance metrics."""
        if not self.enable_performance_logging:
            return

        entry = {"operation": operation, "metrics": metrics}

        self._write_log_entry(self.performance_log_path, entry)

    def _log_error(self, error_type: str, error_message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Log an error."""
        if not self.enable_error_logging:
            return

        entry = {
            "error_type": error_type,
            "error_message": error_message,
            "context": context or {},
            "traceback": (traceback.format_exc() if traceback.format_exc().strip() != "NoneType: None" else None),
        }

        self._write_log_entry(self.error_log_path, entry)

    def _update_session_stats(self, state: Dict[str, Any]) -> None:  # type: ignore[assignment]
        """Update session statistics."""
        try:
            session_stats = {
                "session_id": self.session_id,
                "interaction_count": state.get("interaction_count", 0),
                "session_start_time": state.get("session_start_time", time.time()),
                "last_activity": time.time(),
                "total_duration": time.time() - state.get("session_start_time", time.time()),
                "log_config": {
                    "conversation_logging": self.enable_conversation_logging,
                    "tool_logging": self.enable_tool_logging,
                    "performance_logging": self.enable_performance_logging,
                    "error_logging": self.enable_error_logging,
                },
            }

            # save session statistics
            session_path = f"{self.log_path}sessions/{self.session_id}.json"
            self.backend.write(session_path, json.dumps(session_stats, indent=2))
        except Exception as e:
            print(f"Warning: Failed to update session stats: {e}")

    def _extract_conversation_content(self, request: ModelRequest) -> str:
        """Extract conversation content from a request."""
        if hasattr(request, "content") and request.content:
            return str(request.content)
        elif hasattr(request, "messages") and request.messages:
            # get the last user message
            for msg in reversed(request.messages):
                # compatible with LangChain Message objects and dict format
                role = None
                if hasattr(msg, "type"):
                    role = "user" if msg.type == "human" else "assistant" if msg.type == "ai" else None
                elif isinstance(msg, dict):
                    role = msg.get("role")

                if role == "user":
                    if hasattr(msg, "content"):
                        content = msg.content
                    elif isinstance(msg, dict):
                        content = msg.get("content", "")
                    else:
                        content = ""
                    return str(content) if content is not None else ""
        return ""

    def _extract_response_content(self, response: ModelResponse) -> str:
        """Extract response content."""
        if hasattr(response, "content") and response.content:
            return str(response.content)
        elif hasattr(response, "messages") and response.messages:
            # get the last assistant message
            for msg in reversed(response.messages):
                # compatible with LangChain Message objects and dict format
                role = None
                if hasattr(msg, "type"):
                    role = "user" if msg.type == "human" else "assistant" if msg.type == "ai" else None
                elif isinstance(msg, dict):
                    role = msg.get("role")

                if role == "assistant":
                    if hasattr(msg, "content"):
                        content = msg.content
                    elif isinstance(msg, dict):
                        content = msg.get("content", "")
                    else:
                        content = ""
                    return str(content) if content is not None else ""
        return ""

    def _extract_tool_calls(self, response: ModelResponse) -> List[Dict[str, Any]]:
        """Extract tool calls from a response."""
        tool_calls = []

        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_calls.extend(response.tool_calls)
        elif hasattr(response, "messages") and response.messages:
            for msg in response.messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_calls.extend(msg.tool_calls)

        return tool_calls

    def before_agent(
        self,
        state: AgentState[Any],  # type: ignore[assignment]
        runtime,
    ) -> dict[str, Any]:  # type: ignore[override]
        """Initialize logging before agent execution."""
        session_id = self.session_id

        log_config = {
            "conversation_logging": self.enable_conversation_logging,
            "tool_logging": self.enable_tool_logging,
            "performance_logging": self.enable_performance_logging,
            "error_logging": self.enable_error_logging,
            "log_level": self.log_level,
            "max_log_files": self.max_log_files,
            "max_file_size": self.max_file_size,
        }

        return {
            "session_id": session_id,
            "log_config": log_config,
            "interaction_count": 0,
            "session_start_time": time.time(),
            "last_activity": time.time(),
            "messages": [],  # Add required messages key
        }

    async def abefore_agent(
        self,
        state: AgentState[Any],  # type: ignore[assignment]
        runtime,
    ) -> dict[str, Any]:  # type: ignore[override]
        """Async: initialize logging before agent execution."""
        return self.before_agent(state, runtime)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Wrap model call and log details."""
        start_time = time.time()

        # extract request content
        request_content = self._extract_conversation_content(request)

        # log user input
        if request_content:
            self._log_conversation_entry(
                "user_input",
                request_content,
                {"source": "model_request", "timestamp": datetime.now().isoformat()},
            )

        try:
            # execute model call
            response = handler(request)

            # compute execution time
            execution_time = time.time() - start_time

            # extract response content
            response_content = self._extract_response_content(response)

            # log AI response
            if response_content:
                self._log_conversation_entry(
                    "assistant_response",
                    response_content,
                    {
                        "source": "model_response",
                        "execution_time": execution_time,
                        "response_length": len(response_content),
                    },
                )

            # log tool calls
            tool_calls = self._extract_tool_calls(response)
            if tool_calls:
                for tool_call in tool_calls:
                    time.time()
                    tool_name = tool_call.get("name", "unknown")
                    tool_args = tool_call.get("args", {})

                    try:
                        # only log the call here; actual execution is handled by other middleware
                        self._log_tool_call(
                            tool_name,
                            tool_args,
                            execution_time=0.0,  # actual execution time is recorded elsewhere
                            result=None,
                        )
                    except Exception as e:
                        self._log_error(
                            "tool_logging_error",
                            f"Failed to log tool call: {str(e)}",
                            {"tool_name": tool_name, "tool_args": tool_args},
                        )

            # log performance metrics
            self._log_performance_metrics(
                "model_call",
                {
                    "execution_time": execution_time,
                    "request_length": len(request_content) if request_content else 0,
                    "response_length": len(response_content) if response_content else 0,
                    "tool_calls_count": len(tool_calls),
                },
            )

            # update interaction count
            state_dict = dict(request.state)  # type: ignore[arg-type]
            current_count = state_dict.get("interaction_count", 0)
            if not isinstance(current_count, int):
                current_count = 0
            state_dict["interaction_count"] = current_count + 1  # type: ignore[assignment]
            state_dict["last_activity"] = time.time()  # type: ignore[assignment]

            # update session statistics
            self._update_session_stats(state_dict)  # type: ignore[arg-type]

            return response

        except Exception as e:
            # log error
            error_msg = str(e)
            execution_time = time.time() - start_time

            # provide more detailed context for "No generations found in stream" errors
            context = {
                "request_content_preview": (
                    request_content[:100] + "..." if len(request_content) > 100 else request_content
                ),
                "execution_time": execution_time,
            }

            # if the error is "No generations found in stream", add extra diagnostics
            if "No generations found in stream" in error_msg:
                context.update(
                    {
                        "error_type": "stream_timeout_or_empty",
                        "diagnosis": (
                            "This error typically occurs when: "
                            "1) The model stream timed out (default 60s), "
                            "2) The API returned an empty stream, or "
                            "3) Network connectivity issues. "
                            f"Execution time was {execution_time:.2f}s. "
                            "Consider increasing the model timeout or checking network connectivity."
                        ),
                    }
                )

            self._log_error(
                "model_call_error",
                error_msg,
                context,
            )
            raise

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async: wrap model call and log details."""
        start_time = time.time()

        # extract request content
        request_content = self._extract_conversation_content(request)

        # log user input
        if request_content:
            self._log_conversation_entry(
                "user_input",
                request_content,
                {
                    "source": "model_request_async",
                    "timestamp": datetime.now().isoformat(),
                },
            )

        try:
            # execute model call
            response = await handler(request)

            # compute execution time
            execution_time = time.time() - start_time

            # extract response content
            response_content = self._extract_response_content(response)

            # log AI response
            if response_content:
                self._log_conversation_entry(
                    "assistant_response",
                    response_content,
                    {
                        "source": "model_response_async",
                        "execution_time": execution_time,
                        "response_length": len(response_content),
                    },
                )

            # log tool calls
            tool_calls = self._extract_tool_calls(response)
            if tool_calls:
                for tool_call in tool_calls:
                    tool_name = tool_call.get("name", "unknown")
                    tool_args = tool_call.get("args", {})

                    try:
                        self._log_tool_call(tool_name, tool_args, execution_time=0.0, result=None)
                    except Exception as e:
                        self._log_error(
                            "tool_logging_error",
                            f"Failed to log tool call: {str(e)}",
                            {"tool_name": tool_name, "tool_args": tool_args},
                        )

            # log performance metrics
            self._log_performance_metrics(
                "model_call_async",
                {
                    "execution_time": execution_time,
                    "request_length": len(request_content) if request_content else 0,
                    "response_length": len(response_content) if response_content else 0,
                    "tool_calls_count": len(tool_calls),
                },
            )

            # update interaction count
            state_dict = dict(request.state)  # type: ignore[arg-type]
            current_count = state_dict.get("interaction_count", 0)
            if not isinstance(current_count, int):
                current_count = 0
            state_dict["interaction_count"] = current_count + 1  # type: ignore[assignment]
            state_dict["last_activity"] = time.time()  # type: ignore[assignment]

            # update session statistics
            self._update_session_stats(state_dict)  # type: ignore[arg-type]

            return response

        except Exception as e:
            # log error
            error_msg = str(e)
            execution_time = time.time() - start_time

            # provide more detailed context for "No generations found in stream" errors
            context = {
                "request_content_preview": (
                    request_content[:100] + "..." if len(request_content) > 100 else request_content
                ),
                "execution_time": execution_time,
            }

            # if the error is "No generations found in stream", add extra diagnostics
            if "No generations found in stream" in error_msg:
                context.update(
                    {
                        "error_type": "stream_timeout_or_empty",
                        "diagnosis": (
                            "This error typically occurs when: "
                            "1) The model stream timed out (default 60s), "
                            "2) The API returned an empty stream, or "
                            "3) Network connectivity issues. "
                            f"Execution time was {execution_time:.2f}s. "
                            "Consider increasing the model timeout or checking network connectivity."
                        ),
                    }
                )

            self._log_error(
                "model_call_error",
                error_msg,
                context,
            )
            raise

    def get_session_statistics(self) -> Dict[str, Any]:
        """Get session statistics."""
        try:
            session_path = f"{self.log_path}sessions/{self.session_id}.json"
            session_data = self.backend.read(session_path)
            if session_data:
                result = json.loads(session_data)
                return result if isinstance(result, dict) else {"error": "Invalid session data format"}
        except Exception:
            pass

        return {"error": "Session statistics not available"}

    def get_recent_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent conversation records."""
        try:
            conversation_data = self.backend.read(self.conversation_log_path)
            if conversation_data:
                lines = conversation_data.strip().split("\n")
                recent_lines = lines[-limit:] if len(lines) > limit else lines

                return [json.loads(line) for line in recent_lines if line.strip()]
        except Exception:
            pass

        return []

    def get_error_summary(self) -> Dict[str, Any]:
        """Get error summary."""
        try:
            error_data = self.backend.read(self.error_log_path)
            if not error_data:
                return {"total_errors": 0}

            lines = error_data.strip().split("\n")
            error_entries = []
            for line in lines:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        if isinstance(entry, dict):
                            error_entries.append(entry)
                    except json.JSONDecodeError:
                        continue

            error_types: Dict[str, int] = {}
            recent_errors: List[Dict[str, Any]] = []

            for entry in error_entries[-20:]:  # last 20 errors
                error_type = entry.get("error_type", "unknown")
                error_types[error_type] = error_types.get(error_type, 0) + 1

                if len(recent_errors) < 10:
                    recent_errors.append(
                        {
                            "timestamp": entry.get("timestamp"),
                            "error_type": error_type,
                            "error_message": entry.get("error_message", "")[:100],
                        }
                    )

            return {
                "total_errors": len(error_entries),
                "error_types": error_types,
                "recent_errors": recent_errors,
            }
        except Exception:
            return {"error": "Failed to generate error summary"}

    def cleanup_old_logs(self, days_to_keep: int = 30) -> None:
        """Clean up old log files."""
        time.time() - (days_to_keep * 24 * 60 * 60)

        try:
            # concrete cleanup logic needs to be implemented here;
            # limited by BackendProtocol, this is a placeholder
            pass
        except Exception as e:
            print(f"Warning: Failed to cleanup old logs: {e}")


# (no additional imports needed)
