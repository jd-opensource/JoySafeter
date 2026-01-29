"""
Rich Console Callback for Agent Execution Visualization.

This module provides a rich, structured CLI output for Agent execution,
replacing the default text-heavy debug output with visual components.

Features:
- Spinner for LLM thinking
- Panels for tool calls with syntax highlighting
- Progress bars for execution plans
- Color-coded status indicators
- Collapsible long outputs
"""

import json
import re
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from loguru import logger

from app.dynamic_agent.core.constants import AGENT_TOOL_NAME, THINK_TOOL_NAME
from app.dynamic_agent.models.display_models import (
    DisplayState,
    ToolCallDisplay,
    ToolStatus,
)

# Rich imports with graceful fallback
try:
    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn  # noqa: F401
    from rich.spinner import Spinner  # noqa: F401
    from rich.style import Style  # noqa: F401
    from rich.syntax import Syntax
    from rich.table import Table  # noqa: F401
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Constants for truncation (from clarifications)
MAX_LINES = 20
MAX_CHARS = 2000

# Deduplicate Rich output across multiple callback instances
_SEEN_LLM_ENDS: set[str] = set()
_SEEN_TOOL_STARTS: set[str] = set()
_SEEN_TOOL_ENDS: set[str] = set()
_SEEN_LOCK = threading.Lock()
_SEEN_MAX = 5000


def _seen_before(seen_set: set[str], key: Optional[str]) -> bool:
    """Return True if key was seen before; record it otherwise."""
    if not key:
        return False
    with _SEEN_LOCK:
        if key in seen_set:
            return True
        seen_set.add(key)
        if len(seen_set) > _SEEN_MAX:
            seen_set.clear()
    return False


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_pattern.sub("", text)


def truncate_content(content: str, max_lines: int = MAX_LINES, max_chars: int = MAX_CHARS) -> tuple[str, bool]:
    """
    Truncate content if it exceeds thresholds.

    Returns:
        Tuple of (truncated_content, was_truncated)
    """
    if not content:
        return "", False

    lines = content.split("\n")
    total_lines = len(lines)

    if total_lines <= max_lines and len(content) <= max_chars:
        return content, False

    # Truncate by lines first
    truncated_lines = lines[:max_lines]
    result = "\n".join(truncated_lines)

    # Then truncate by chars if needed
    if len(result) > max_chars:
        result = result[:max_chars]

    return f"{result}\n... ({total_lines} lines, {len(content)} chars total)", True


def detect_language(content: str, tool_name: str = "") -> str:
    """Detect syntax highlighting language from content or tool name."""
    # Check tool name hints
    if "python" in tool_name.lower():
        return "python"
    if "shell" in tool_name.lower() or "command" in tool_name.lower() or "bash" in tool_name.lower():
        return "shell"

    # Check content patterns
    content_lower = content.lower()[:500] if content else ""

    if content.strip().startswith("{") or content.strip().startswith("["):
        return "json"
    if "def " in content_lower or "import " in content_lower or "class " in content_lower:
        return "python"
    if content.strip().startswith("$") or "bash" in content_lower or "#!" in content[:20]:
        return "shell"

    return ""  # No syntax highlighting


class RichConsoleCallback(BaseCallbackHandler):
    """
    Rich Console Callback for structured CLI output.

    Provides visual feedback for Agent execution including:
    - Spinner during LLM thinking
    - Panels for tool calls with syntax highlighting
    - Status icons for success/failure
    - Content truncation for long outputs
    """

    def __init__(self):
        """Initialize the Rich console callback."""
        self.console = Console(force_terminal=None)  # Auto-detect TTY
        self.state = DisplayState()
        self.depth = 0
        self.tool_start_times: Dict[str, datetime] = {}
        self._live: Optional[Live] = None

    def _is_tty(self) -> bool:
        """Check if output is a TTY (for graceful fallback)."""
        return bool(self.console.is_terminal)

    def _convert_messages_to_log_format(self, messages: List) -> List[Dict]:
        """
        Convert LangChain messages to log format.

        This directly extracts info from LangChain message objects,
        ensuring the log matches exactly what the LLM receives.

        Args:
            messages: List of LangChain message objects

        Returns:
            List of dicts with role, content, tool_calls, tool_call_id
        """
        ROLE_MAP = {"human": "user", "ai": "assistant"}
        result = []

        for msg in messages:
            # Extract basic info
            if hasattr(msg, "type"):
                role = ROLE_MAP.get(msg.type, msg.type)
                content = getattr(msg, "content", "") or ""
            elif hasattr(msg, "role"):
                role = ROLE_MAP.get(msg.role, msg.role)
                content = getattr(msg, "content", "") or ""
            elif isinstance(msg, dict):
                role = ROLE_MAP.get(msg.get("role", ""), msg.get("role", "unknown"))
                content = msg.get("content", "")
            else:
                continue

            entry = {"role": role, "content": content}

            # Extract tool_calls (for assistant messages)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", ""),
                        "name": tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", ""),
                        "args": tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}),
                    }
                    for tc in msg.tool_calls
                ]
            elif isinstance(msg, dict) and msg.get("tool_calls"):
                entry["tool_calls"] = msg["tool_calls"]

            # Extract tool_call_id (for tool messages)
            if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            elif isinstance(msg, dict) and msg.get("tool_call_id"):
                entry["tool_call_id"] = msg["tool_call_id"]

            result.append(entry)

        return result

    # =========================================================================
    # T014: LLM Start - Show spinner
    # =========================================================================
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Called when LLM starts processing."""
        self.state.current_phase = "thinking"
        # Note: JSON logging is handled by JsonFileLoggingCallback

        if not self._is_tty():
            # Fallback for non-TTY
            logger.info("🤔 Thinking...")
            return

        # Show thinking indicator
        self.console.print()
        self.console.print("[dim]🤔 Thinking...[/dim]", end="\r")
        self.depth += 1

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List, **kwargs) -> None:
        """
        Called when chat model starts - captures full message list.
        This is called instead of on_llm_start for chat models (OpenAI, etc.)
        """
        self.state.current_phase = "thinking"
        # Note: JSON logging is handled by JsonFileLoggingCallback

        if not self._is_tty():
            logger.info("🤔 Thinking...")
            return

        self.console.print()
        self.console.print("[dim]🤔 Thinking...[/dim]", end="\r")
        self.depth += 1

    # =========================================================================
    # T015: LLM End - Stop spinner, show decision
    # =========================================================================
    def on_llm_end(self, response, **kwargs) -> None:
        """Called when LLM completes processing."""
        run_id = str(kwargs.get("run_id", "")) or None
        if _seen_before(_SEEN_LLM_ENDS, run_id):
            return
        self.depth = max(0, self.depth - 1)
        self.state.current_phase = "idle"
        # Note: JSON logging is handled by JsonFileLoggingCallback

        if not self._is_tty():
            return

        # Clear thinking indicator
        self.console.print(" " * 50, end="\r")  # Clear line

        # Extract tool calls if any
        try:
            if hasattr(response, "generations") and response.generations:
                gen = response.generations[0][0] if response.generations[0] else None
                if gen and hasattr(gen, "message"):
                    msg = gen.message
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        # Show decision for first tool
                        tool_name = msg.tool_calls[0].get("name", "unknown")
                        if tool_name != THINK_TOOL_NAME:
                            display_name = tool_name.replace("seclens_", "").replace("_", " ")
                            self.console.print(f"[cyan]🎯 Decision: {display_name}[/cyan]")
        except Exception as e:
            logger.debug(f"Failed to display LLM end event: {e}")

    def on_llm_error(self, error: BaseException, *, run_id=None, parent_run_id=None, **kwargs) -> None:  # type: ignore[override]
        """Called when LLM encounters an error."""
        self.depth = max(0, self.depth - 1)
        self.state.current_phase = "idle"
        # Note: JSON logging is handled by JsonFileLoggingCallback

        self._show_error_panel("LLM Error", str(error))

    # =========================================================================
    # T016: Tool Start - Show Panel with input
    # =========================================================================
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """Called when a tool starts executing."""
        run_id = str(kwargs.get("run_id", ""))
        if _seen_before(_SEEN_TOOL_STARTS, run_id):
            return
        name = serialized.get("name", serialized.get("id", "<tool>"))

        self.state.current_phase = "tool_call"
        self.tool_start_times[run_id] = datetime.now()

        # Parse input
        try:
            input_obj = eval(input_str) if isinstance(input_str, str) else input_str
        except (SyntaxError, ValueError, NameError) as e:
            logger.debug(f"Failed to parse tool input: {e}")
            input_obj = {"raw": input_str}

        # Store in state
        self.state.active_tools[run_id] = ToolCallDisplay(
            run_id=run_id,
            tool_name=name,
            input_data=input_obj,
            status=ToolStatus.RUNNING,
        )
        # Note: JSON logging is handled by JsonFileLoggingCallback

        # Handle think tool specially
        if name == THINK_TOOL_NAME:
            thought = input_obj.get("thought", "") if isinstance(input_obj, dict) else str(input_obj)
            self._show_thinking_panel(thought)
            self.depth += 1
            return

        # Handle agent tool specially
        if name == AGENT_TOOL_NAME:
            self._show_agent_panel(input_obj)
            self.depth += 1
            return

        # Regular tool - show input panel
        self._show_tool_start_panel(name, input_obj)
        self.depth += 1

    # =========================================================================
    # T017: Tool End - Show status and output Panel
    # =========================================================================
    def on_tool_end(self, output: Any, **kwargs) -> None:
        """Called when a tool completes."""
        self.depth = max(0, self.depth - 1)
        run_id = str(kwargs.get("run_id", ""))
        if _seen_before(_SEEN_TOOL_ENDS, run_id):
            return
        name = kwargs.get("name", "<tool>")

        # Calculate duration
        start_time = self.tool_start_times.pop(run_id, None)
        duration_str = ""
        if start_time:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            duration_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms / 1000:.1f}s"

        # Get output content - handle various types (string, list, dict, ToolMessage)
        if hasattr(output, "content"):
            content = output.content
        else:
            content = output

        # Convert non-string content to string
        if isinstance(content, (list, dict)):
            try:
                content = json.dumps(content, ensure_ascii=False, indent=2)
            except (TypeError, ValueError) as e:
                logger.debug(f"Failed to JSON serialize content: {e}")
                content = str(content)
        elif not isinstance(content, str):
            content = str(content)

        # Update state
        if run_id in self.state.active_tools:
            tool_display = self.state.active_tools[run_id]
            tool_display.status = ToolStatus.SUCCESS
            tool_display.output_data = content
            tool_display.end_time = datetime.now()
        # Note: JSON logging is handled by JsonFileLoggingCallback

        # Skip output panel for think tool
        if name == THINK_TOOL_NAME:
            return

        # Show output panel
        self._show_tool_end_panel(name, content, duration_str, success=True)
        self.state.current_phase = "idle"

    def on_tool_error(self, error: BaseException, *, run_id=None, parent_run_id=None, **kwargs) -> None:  # type: ignore[override]
        """Called when a tool encounters an error."""
        self.depth = max(0, self.depth - 1)
        run_id_str = str(run_id) if run_id else str(kwargs.get("run_id", ""))
        name = kwargs.get("name", "<tool>")

        # Update state
        if run_id_str in self.state.active_tools:
            tool_display = self.state.active_tools[run_id_str]
            tool_display.status = ToolStatus.FAILED
            tool_display.error_message = str(error)
            tool_display.end_time = datetime.now()
        # Note: JSON logging is handled by JsonFileLoggingCallback

        self._show_error_panel(f"Tool Error: {name}", str(error))
        self.state.current_phase = "idle"

    # =========================================================================
    # Chain callbacks
    # =========================================================================
    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain starts."""
        pass  # Minimal logging for chains

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain completes."""
        pass  # Minimal logging for chains

    def on_chain_error(self, error: BaseException, *, run_id=None, parent_run_id=None, **kwargs) -> None:  # type: ignore[override]
        """Called when a chain encounters an error."""
        # Note: JSON logging is handled by JsonFileLoggingCallback
        self._show_error_panel("Chain Execution Error", str(error))

    # =========================================================================
    # Helper methods for rendering panels
    # =========================================================================

    def _show_thinking_panel(self, thought: str) -> None:
        """Show thinking content in a dim, collapsed style."""
        if not self._is_tty():
            logger.info(f"💭 Reasoning: {thought[:100]}...")
            return

        # T018: Truncate if needed
        truncated, was_truncated = truncate_content(thought)

        title = "💭 Reasoning"
        if was_truncated:
            title += " [dim](truncated)[/dim]"

        panel = Panel(
            Text(truncated, style="dim italic"),
            title=title,
            border_style="dim",
            box=box.ROUNDED,
        )
        self.console.print(panel)

    def _show_agent_panel(self, input_obj: Dict[str, Any]) -> None:
        """Show agent tool invocation."""
        if not self._is_tty():
            task_count = len(input_obj.get("task_details", []))
            logger.info(f"🤖 Agent: Spawning {task_count} sub-task(s)")
            return

        context = input_obj.get("context", "")[:200]
        task_details = input_obj.get("task_details", [])

        # Build content - simplified display without level
        content = f"[bold]Context:[/bold] {context}...\n\n"
        content += f"[bold]Tasks ({len(task_details)}):[/bold]\n"
        for i, task in enumerate(task_details[:5], 1):
            content += f"  {i}. {task[:80]}...\n" if len(task) > 80 else f"  {i}. {task}\n"
        if len(task_details) > 5:
            content += f"  ... and {len(task_details) - 5} more\n"

        panel = Panel(
            content,
            title="🤖 Agent Sub-tasks",
            border_style="blue",
            box=box.ROUNDED,
        )
        self.console.print(panel)

    def _show_tool_start_panel(self, name: str, input_obj: Dict[str, Any]) -> None:
        """Show tool start with input parameters."""
        # Special handling for agent_tool - show as sub-task delegation
        if name == "agent_tool":
            task_details = input_obj.get("task_details", [])
            task_summary = task_details[0][:100] if task_details else "Execute sub-task"
            if not self._is_tty():
                logger.info(f"🤖 Delegating sub-task: {task_summary}...")
                return
            panel = Panel(
                f"[bold]Task:[/bold] {task_summary}{'...' if len(task_details[0]) > 100 else ''}",
                title="🤖 Delegating Sub-task",
                subtitle="[dim]🔄 Executing...[/dim]",
                border_style="blue",
                box=box.ROUNDED,
            )
            self.console.print(panel)
            return

        # Simplify tool name for display
        display_name = name.replace("seclens_", "").replace("_", " ")

        if not self._is_tty():
            logger.info(f"🔧 Tool Execution: {display_name}")
            return

        # Format input as JSON with syntax highlighting
        try:
            input_json = json.dumps(input_obj, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as e:
            logger.debug(f"Failed to JSON serialize tool input: {e}")
            input_json = str(input_obj)

        # T018: Truncate if needed
        truncated, was_truncated = truncate_content(input_json)

        # T024: JSON syntax highlighting
        syntax = Syntax(truncated, "json", theme="monokai", word_wrap=True)

        title = f"🔧 Tool Execution: {display_name}"
        if was_truncated:
            title += " [dim](truncated)[/dim]"

        panel = Panel(
            syntax,
            title=title,
            subtitle="[dim]🔄 Executing...[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
        self.console.print(panel)

    def _show_tool_end_panel(self, name: str, output: str, duration: str, success: bool = True) -> None:
        """Show tool completion with output."""
        # Special handling for agent_tool
        if name == "agent_tool":
            status = "✅" if success else "❌"
            if not self._is_tty():
                logger.info(f"{status} Sub-task completed ({duration})")
                return
            # For agent_tool, show simplified completion
            truncated, _ = truncate_content(strip_ansi(output))
            content = (
                Syntax(truncated, "json", theme="monokai", word_wrap=True)
                if truncated.strip().startswith("{")
                else Text(truncated)
            )
            title = f"{status} Sub-task completed [dim]({duration})[/dim]"
            panel = Panel(content, title=title, border_style="green" if success else "red", box=box.ROUNDED)
            self.console.print(panel)
            return

        # Simplify tool name for display
        display_name = name.replace("seclens_", "").replace("_", " ")

        if not self._is_tty():
            status = "✅" if success else "❌"
            logger.info(f"{status} Tool Result: {display_name} ({duration})")
            return

        # Clean ANSI sequences
        output = strip_ansi(output)

        # T018: Truncate if needed
        truncated, was_truncated = truncate_content(output)

        # T025: Detect and apply syntax highlighting
        lang = detect_language(output, name)
        if lang:
            content = Syntax(truncated, lang, theme="monokai", word_wrap=True)
        else:
            content = Text(truncated)

        # Status styling
        if success:
            status_icon = "✅"
            border_style = "green"
        else:
            status_icon = "❌"
            border_style = "red"

        title = f"{status_icon} Tool Result: {display_name}"
        if duration:
            title += f" [dim]({duration})[/dim]"
        if was_truncated:
            title += " [dim](truncated)[/dim]"

        panel = Panel(
            content,
            title=title,
            border_style=border_style,
            box=box.ROUNDED,
        )
        self.console.print(panel)

    def _show_error_panel(self, title: str, error: str) -> None:
        """Show error in red panel."""
        if not self._is_tty():
            logger.error(f"❌ {title}: {error}")
            return

        panel = Panel(
            Text(error, style="red"),
            title=f"❌ {title}",
            border_style="red",
            box=box.HEAVY,
        )
        self.console.print(panel)
