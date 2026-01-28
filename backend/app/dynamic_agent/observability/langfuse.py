import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from loguru import logger

from app.dynamic_agent.core.config import conf
from app.dynamic_agent.infra.metadata_context import MetadataContext, write_messages

# --- CTF Success Metrics ---


def log_ctf_metric(metric_name: str, data: Dict[str, Any], session_id: Optional[str] = None):
    """
    Log CTF success metrics for tracking SC-001 and SC-004.

    Metrics:
    - SC-001: First action cycle uses shell/Python within 30s
    - SC-004: Non-CTF requests maintain unchanged tool selection

    Args:
        metric_name: Name of the metric (e.g., 'CTF_FIRST_ACTION', 'NON_CTF_TOOL_ORDER')
        data: Metric data
        session_id: Optional session ID
    """
    write_json_log(f"CTF_METRIC_{metric_name}", data, session_id)


def log_ctf_first_action(
    tool_type: str, tool_name: str, elapsed_seconds: float, is_shell_or_python: bool, session_id: Optional[str] = None
):
    """
    Log SC-001: First action cycle uses shell/Python within 30s.

    Args:
        tool_type: Type of tool used (shell/python/other)
        tool_name: Name of the tool
        elapsed_seconds: Time from request to first action
        is_shell_or_python: Whether the tool is shell or python
        session_id: Optional session ID
    """
    success = is_shell_or_python and elapsed_seconds <= 30
    log_ctf_metric(
        "SC001_FIRST_ACTION",
        {
            "tool_type": tool_type,
            "tool_name": tool_name,
            "elapsed_seconds": elapsed_seconds,
            "is_shell_or_python": is_shell_or_python,
            "within_30s": elapsed_seconds <= 30,
            "success": success,
        },
        session_id,
    )


def log_ctf_hint_processing(total_hints: int, applied: int, skipped: int, session_id: Optional[str] = None):
    """
    Log SC-002: User-supplied ideas are executed or acknowledged.

    Args:
        total_hints: Total number of hints provided
        applied: Number of hints applied
        skipped: Number of hints skipped (with reasons)
        session_id: Optional session ID
    """
    # At least 80% should be applied or explicitly skipped with reason
    processed = applied + skipped
    success = total_hints == 0 or (processed / total_hints) >= 0.8
    log_ctf_metric(
        "SC002_HINT_PROCESSING",
        {
            "total_hints": total_hints,
            "applied": applied,
            "skipped": skipped,
            "processed_ratio": processed / total_hints if total_hints > 0 else 1.0,
            "success": success,
        },
        session_id,
    )


def log_non_ctf_tool_order(original_order: list, actual_order: list, session_id: Optional[str] = None):
    """
    Log SC-004: Non-CTF requests maintain unchanged tool selection.

    Args:
        original_order: Expected tool order (standard)
        actual_order: Actual tool order used
        session_id: Optional session ID
    """
    # Check if order is unchanged (first 5 tools match)
    success = original_order[:5] == actual_order[:5]
    log_ctf_metric(
        "SC004_NON_CTF_ORDER",
        {
            "original_order": original_order[:10],
            "actual_order": actual_order[:10],
            "order_preserved": success,
            "success": success,
        },
        session_id,
    )


# --- JSON Log Writer ---

LOG_DIR = Path(__file__).parent.parent / "logs"

# Idempotency cache: tracks recently written events to prevent duplicates
# Format: {(session_id, event_type, run_id_or_hash): timestamp}
_recent_log_entries: Dict[tuple, float] = {}
_DEDUP_WINDOW_SECONDS = 0.5  # Time window for deduplication (500ms)


def _get_session_log_file(session_id: str) -> Path:
    """Get log file path for a specific session."""
    # Sanitize session_id for use as filename
    safe_session_id = session_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    return LOG_DIR / f"session_{safe_session_id}.jsonl"


def _is_duplicate_entry(session_id: str, event_type: str, data: Dict[str, Any]) -> bool:
    """
    Check if this log entry is a duplicate of a recent entry.
    Uses run_id if available, otherwise hashes the data content.
    """
    import hashlib
    import time

    # Extract run_id if present (for tool calls and LLM events)
    run_id = data.get("run_id", "")
    if not run_id and "tool_calls" in data:
        # For LLM_RESPONSE, hash the tool_calls to detect duplicates
        try:
            run_id = hashlib.md5(json.dumps(data.get("tool_calls", []), sort_keys=True).encode()).hexdigest()[:8]
        except (TypeError, ValueError):
            run_id = ""

    cache_key = (session_id, event_type, run_id)
    current_time = time.time()

    # Clean up old entries
    keys_to_remove = [k for k, v in _recent_log_entries.items() if current_time - v > _DEDUP_WINDOW_SECONDS]
    for k in keys_to_remove:
        del _recent_log_entries[k]

    # Check if this is a duplicate
    if cache_key in _recent_log_entries:
        return True

    # Mark this entry as written
    _recent_log_entries[cache_key] = current_time
    return False


def write_json_log(event_type: str, data: Dict[str, Any], session_id: Optional[str] = None):
    """
    Write a JSON log entry to a session-specific log file.

    Each session gets its own log file: logs/session_{session_id}.jsonl
    Includes idempotency check to prevent duplicate writes within a short time window.

    Args:
        event_type: Type of event (LLM_CALL, LLM_RESPONSE, TOOL_CALL, ERROR)
        data: Event data dictionary
        session_id: Optional session ID (auto-detected from MetadataContext if not provided)
    """
    try:
        # Get session_id from context if not provided
        if session_id is None:
            metas = MetadataContext.get()
            if metas:
                # Try multiple possible keys for session_id
                session_id = metas.get("session_id") or metas.get("langfuse_session_id") or "unknown"
            else:
                session_id = "unknown"

        # Idempotency check: skip if this is a duplicate entry
        if _is_duplicate_entry(session_id, event_type, data):
            return

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "event_type": event_type,
            "data": data,
        }

        # Ensure log directory exists
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # Append to session-specific log file
        log_file = _get_session_log_file(session_id)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        # Don't let logging errors break the main flow
    except Exception:
        pass


class ChainDebugCallback(BaseCallbackHandler):
    """
    Full-chain debugging callback for LCEL, Agent, LLM, Tool.
    Automatically prints input/output, tokens, errors, and hierarchy for each step.
    Supports streaming intermediate results to response_queue.
    """

    # Markdown separators to avoid structure conflicts
    SECTION_SEPARATOR = "\n---\n"
    CODE_BLOCK_SEPARATOR = "\n\n"

    def __init__(self):
        self.depth = 0

    # --- Utility ---
    def indent(self):
        return "  " * self.depth

    def _create_collapsible_block(
        self, content: str, language: str = "", summary: str = "", collapsed: bool = True
    ) -> str:
        """
        Create a collapsible code block with single-line/expanded view toggle.

        Args:
            content: Full code block content
            language: Code language for syntax highlighting (e.g., 'json', 'shell')
            summary: Single-line summary (auto-generated if not provided)
            collapsed: Default to collapsed (single-line) view

        Returns:
            Markdown with HTML details element for collapsible display
        """
        if not summary:
            # Auto-generate summary from first line or content length
            lines = content.strip().split("\n")
            if len(lines) > 1:
                summary = f"{lines[0][:60]}..." if len(lines[0]) > 60 else lines[0]
            else:
                summary = content[:60] + "..." if len(content) > 60 else content

        # Use HTML details element for collapsible display
        # This is supported by most Markdown renderers (GitHub, GitLab, etc.)
        open_attr = "" if collapsed else " open"

        return f"<details{open_attr}>\n<summary>{summary}</summary>\n\n```{language}\n{content}\n```\n\n</details>"

    # --- Chain ---

    def on_chain_start(self, serialized, inputs, **kwargs):
        # name = serialized.get("name", serialized.get("id", "<chain>"))
        self.depth += 1
        self.depth += 1

    def on_chain_end(self, outputs, **kwargs):
        self.depth -= 1

    # --- LLM ---

    def on_llm_start(self, serialized, prompts, **kwargs):
        # name = serialized.get("name", serialized.get("id", "<llm>"))
        self.depth += 1

        # Note: JSON logging is handled by JsonFileLoggingCallback
        # on_llm_start receives prompts as strings, not messages
        # Use on_chat_model_start for full message details

    def on_chat_model_start(self, serialized, messages, **kwargs):
        """
        Capture full message list for chat models (OpenAI, etc.)
        This is called instead of on_llm_start for chat models.
        """
        serialized.get("id", "<chat>") if serialized else "<chat>"
        self.depth += 1

        # --- JSON Log: LLM_INPUT with full messages ---
        invocation_params = kwargs.get("invocation_params", {})

        # messages is a list of lists: [[SystemMessage, HumanMessage, ...]]
        all_messages = messages[0] if messages else []

        formatted_messages = []

        for msg in all_messages:
            msg_type = getattr(msg, "type", "unknown")
            msg_content = getattr(msg, "content", str(msg))

            if msg_type == "system":
                pass
            else:
                # Include tool_calls and tool_call_id if present
                msg_data = {
                    "role": msg_type,
                    "content": msg_content,
                }
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    msg_data["tool_calls"] = [
                        {"id": tc.get("id", ""), "name": tc.get("name", ""), "args": tc.get("args", {})}
                        if isinstance(tc, dict)
                        else {
                            "id": getattr(tc, "id", ""),
                            "name": getattr(tc, "name", ""),
                            "args": getattr(tc, "args", {}),
                        }
                        for tc in msg.tool_calls
                    ]
                if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                    msg_data["tool_call_id"] = msg.tool_call_id

                formatted_messages.append(msg_data)

        # Extract tool definitions from invocation_params (for display only)
        tools_definitions = []
        bound_tools = invocation_params.get("tools", [])
        for tool in bound_tools:
            if isinstance(tool, dict):
                # OpenAI function format
                func = tool.get("function", {})
                tools_definitions.append(
                    {
                        "name": func.get("name", ""),
                        "description": func.get("description", "")[:500],  # Truncate long descriptions
                    }
                )
        # Note: JSON logging is handled by JsonFileLoggingCallback

    def on_llm_new_token(self, token, **kwargs):
        pass

    def on_llm_end(self, response, **kwargs):
        self.depth -= 1
        # response.generations[0][0].message.tool_calls
        # Note: JSON logging is handled by JsonFileLoggingCallback

    def on_llm_error(self, error, **kwargs):
        self.depth -= 1
        # Traceback printed to stderr by default/logger, no need to print to stdout
        logger.exception("LLM Error")
        # Note: JSON logging is handled by JsonFileLoggingCallback

    # --- Tools ---

    def on_tool_start(self, serialized, input_str, **kwargs):
        name = serialized.get("id", "")
        if not name:
            name = serialized.get("name", "<tool>")

        # 简化输出：只显示工具名称和开始状态
        write_messages([f"🔧 {name} 工具执行中 ..."])
        self.depth += 1

    def on_tool_end(self, output, **kwargs):
        try:
            name = kwargs.get("name", "<tool>")

            self.depth -= 1

            # 简化输出：只显示工具名称和结束状态
            write_messages([f"✅ {name} 工具执行结束."])
        except Exception:
            pass

    def on_tool_error(self, error, **kwargs):
        name = kwargs.get("name", "<tool>")

        self.depth -= 1

        # 简化输出：只显示工具名称和失败状态
        write_messages([f"❌ {name} 工具执行失败 !"])
        traceback.print_exc()

    def on_chain_error(self, error, **kwargs):
        self.depth -= 1
        traceback.print_exc()
        # Note: JSON logging is handled by JsonFileLoggingCallback


if conf.LANGFUSE_SECRET_KEY:
    langfuse = Langfuse(
        public_key=conf.LANGFUSE_PUBLIC_KEY,
        secret_key=conf.LANGFUSE_SECRET_KEY,
        host=conf.LANGFUSE_HOST,
    )


def callbacks():
    """
    Create callback handlers for agent execution.

    Returns:
        List of callback handlers including:
        - JsonFileLoggingCallback (always, for log persistence)
        - LangfuseHandler (if configured)
        - RichConsoleCallback or ChainDebugCallback (based on RICH_CLI_ENABLED, for UI only)
    """
    result = []

    # 1. Always add the dedicated JSON file logger (centralized persistence)
    from app.dynamic_agent.observability.json_logger import JsonFileLoggingCallback

    result.append(JsonFileLoggingCallback())

    # 2. Add Langfuse handler if configured
    if conf.LANGFUSE_SECRET_KEY:
        langfuse_handler = CallbackHandler()
        result.append(langfuse_handler)

    # 3. Add UI handler based on configuration (display only, no file logging)
    if conf.RICH_CLI_ENABLED:
        try:
            from app.dynamic_agent.observability.rich_console import RichConsoleCallback

            result.append(RichConsoleCallback())
        except ImportError:
            # Fallback to classic debug if Rich not available
            result.append(ChainDebugCallback())
    else:
        result.append(ChainDebugCallback())

    return result
