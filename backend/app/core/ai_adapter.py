"""AI model adapter for web use (decoupled from CLI runtime and dynamic imports).

This refactor removes:
- sys.path manipulations to locate backend CLI code
- _import_cli_modules dynamic loader and the global cli_modules
- Tight coupling to backend runtime construction inside this layer

Design goals:
- Keep a stable, minimal interface for the web layer (stream_response + memory helpers)
- Allow optional injection of an engine that implements a simple streaming protocol
- Provide a safe fallback behavior when no engine is available
"""

from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol

from .settings import settings


class AgentEngine(Protocol):
    """Protocol for pluggable agent engines used by AgentBridge.

    Implementations should provide a `stream` method that yields tuples compatible
    with downstream processing in AgentBridge._process_stream_chunk.

    Expected yield format per chunk:
        (namespace: str, stream_mode: str, data: Any)
    where stream_mode is typically one of: "messages", "updates".
    """

    def stream(
        self,
        input: Dict[str, Any],
        stream_mode: List[str],
        subgraphs: bool,
        config: Dict[str, Any],
        durability: str,
    ): ...


class AgentBridge:
    """Adapter class to bridge AI logic with the web interface.

    Independent from backend CLI code. An engine implementing AgentEngine may be
    injected optionally to enable full functionality. Without an engine, the adapter
    provides a graceful mock response suitable for UI integration tests.
    """

    def __init__(
        self,
        session_id: str,
        workspace_path: str,
        engine: Optional[AgentEngine] = None,
    ):
        """Initialize AI adapter for a specific session.

        Args:
            session_id: Unique identifier for the web session
            workspace_path: Path to the user's workspace directory
            engine: Optional agent engine implementation to power the adapter
        """
        self.session_id = session_id
        self.workspace_path = Path(workspace_path)
        self.engine = engine

        # Create per-session directories using configured workspace root
        workspace_root = Path(settings.WORKSPACE_ROOT)
        self.session_dir = workspace_root / "sessions" / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Memory directory
        self.memory_dir = workspace_root / "memories" / session_id
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Streaming state
        self.pending_text = ""  # Accumulated text buffer
        self.tool_call_buffers: Dict[str, Dict[str, Any]] = {}  # Tool call buffers
        self.last_chunk_time: float = 0  # Last time we received a text chunk
        self.chunk_timeout: float = 2.0  # Timeout in seconds before flushing buffer
        self.is_thinking = False
        self.sent_thinking = False
        self.has_sent_thinking_for_current_request = False

    def set_engine(self, engine: AgentEngine):
        """Attach or replace the underlying engine at runtime."""
        self.engine = engine

    async def stream_response(
        self, message: str, file_references: Optional[List[str]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream AI response for web interface.

        Args:
            message: User message
            file_references: List of file paths to include in context

        Yields:
            Dict containing streaming response chunks
        """
        # Reset thinking state for each request
        self.sent_thinking = False
        self.has_sent_thinking_for_current_request = False

        # If no engine is provided, return a mock response
        if not self.engine:
            yield {
                "type": "message",
                "content": f"I received your message: '{message}'. This is a mock AI response. The full version will be provided by an injected engine.",
                "session_id": self.session_id,
            }
            return

        # Immediately send thinking status
        yield {
            "type": "status",
            "content": "AI is thinking...",
            "session_id": self.session_id,
            "metadata": {"state": "thinking"},
        }

        # Build full input (include referenced files content if any)
        full_input = self._build_input_with_files(message, file_references or [])

        # Engine config
        config = {
            "configurable": {"thread_id": self.session_id},
            "metadata": {"session_id": self.session_id, "source": "web"},
        }

        try:
            # Stream from the engine
            for chunk in self.engine.stream(
                {"messages": [{"role": "user", "content": full_input}]},
                stream_mode=["messages", "updates"],
                subgraphs=True,
                config=config,
                durability="exit",
            ):
                processed_chunk = self._process_stream_chunk(chunk)
                if processed_chunk:
                    yield processed_chunk

            # On stream end, flush any remaining buffered text
            final_chunks = self.flush_pending_text(final=True)
            for final_chunk in final_chunks:
                yield final_chunk

        except Exception as e:
            # Attempt to flush buffered text even on error
            error_chunks = self.flush_pending_text(final=True)
            for chunk in error_chunks:
                yield chunk

            yield {
                "type": "error",
                "content": f"AI response error: {str(e)}",
                "session_id": self.session_id,
            }

    def _build_input_with_files(self, message: str, file_paths: List[str]) -> str:
        """Build input message with file contents included."""
        if not file_paths:
            return message

        context_parts = [message, "\n\n## Referenced Files\n"]

        for file_path in file_paths:
            try:
                full_path = self.workspace_path / file_path
                if full_path.exists():
                    content = full_path.read_text(encoding="utf-8")
                    # Limit file size to avoid overwhelming context
                    if len(content) > 50000:
                        content = content[:50000] + "\n... (file truncated)"

                    context_parts.append(f"\n### {full_path.name}\nPath: `{file_path}`\n```\n{content}\n```")
                else:
                    context_parts.append(f"\n### {Path(file_path).name}\n[Error: File not found - {file_path}]")
            except Exception as e:
                context_parts.append(f"\n### {Path(file_path).name}\n[Error reading file: {e}]")

        return "\n".join(context_parts)

    def _process_stream_chunk(self, chunk) -> Optional[Dict[str, Any]]:
        """Process streaming chunk from AI engine with CLI-style buffering."""
        import time

        if not isinstance(chunk, tuple) or len(chunk) != 3:
            return None

        namespace, stream_mode, data = chunk
        current_time = time.time()
        results: List[Dict[str, Any]] = []

        if stream_mode == "messages":
            if isinstance(data, tuple) and len(data) == 2:
                message, metadata = data

                # Handle AI message content
                if hasattr(message, "content_blocks"):
                    # First handle tool call chunks
                    for block in message.content_blocks:
                        if block.get("type") == "tool_call_chunk":
                            tool_name = block.get("name")
                            tool_args = block.get("args", {})
                            tool_call_id = block.get("id", "default")

                            # Buffer tool call data
                            if tool_call_id not in self.tool_call_buffers:
                                self.tool_call_buffers[tool_call_id] = {
                                    "name": tool_name,
                                    "args": "",
                                    "complete": False,
                                }

                            buffer = self.tool_call_buffers[tool_call_id]
                            if tool_args:
                                buffer["args"] += tool_args

                            # Check completion
                            if block.get("complete", False):
                                buffer["complete"] = True
                                results.append(
                                    {
                                        "type": "tool_call",
                                        "tool": buffer["name"],
                                        "args": buffer["args"],
                                        "session_id": self.session_id,
                                        "tool_call_id": tool_call_id,
                                        "complete": True,
                                    }
                                )
                                del self.tool_call_buffers[tool_call_id]

                    # Then handle text chunks
                    for block in message.content_blocks:
                        if block.get("type") == "text":
                            text_content = block.get("text", "")
                            if text_content:
                                # Detect structured tool output and format nicely
                                if self._is_tool_output(text_content):
                                    formatted_output = self._format_tool_output(text_content)
                                    if formatted_output:
                                        results.append(
                                            {
                                                "type": "tool_result",
                                                "content": formatted_output,
                                                "session_id": self.session_id,
                                            }
                                        )
                                else:
                                    # Accumulate text to buffer
                                    self.pending_text += text_content
                                    self.last_chunk_time = current_time

        elif stream_mode == "updates":
            # Handle updates (including HITL interrupts)
            if isinstance(data, dict):
                if "__interrupt__" in data:
                    interrupt_data = data["__interrupt__"]
                    if interrupt_data and interrupt_data.get("action_requests"):
                        results.append(
                            {
                                "type": "approval_request",
                                "approval_data": interrupt_data,
                                "session_id": self.session_id,
                            }
                        )

                elif "todos" in data:
                    results.append(
                        {
                            "type": "todos",
                            "todos": data["todos"],
                            "session_id": self.session_id,
                        }
                    )

        # Decide whether to flush buffered text (only if no active tool calls)
        should_flush_text = False
        if self.pending_text and not self.tool_call_buffers:
            time_elapsed = current_time - self.last_chunk_time

            # Condition 1: timeout exceeded
            if time_elapsed > self.chunk_timeout:
                should_flush_text = True
            # Condition 2: likely complete sentence and not too short
            elif self._has_complete_sentence(self.pending_text) and len(self.pending_text) > 30:
                should_flush_text = True
            # Condition 3: very long buffer
            elif len(self.pending_text) > 200:
                should_flush_text = True

        if should_flush_text:
            text_to_send = self.pending_text.rstrip()
            if text_to_send:
                results.append(
                    {
                        "type": "message",
                        "content": text_to_send,
                        "session_id": self.session_id,
                        "is_stream": True,
                    }
                )
                self.pending_text = ""
                self.last_chunk_time = current_time

        # Priority: tool_call > tool_result > status > other > text
        if results:
            tool_call_messages = [r for r in results if r.get("type") == "tool_call"]
            tool_result_messages = [r for r in results if r.get("type") == "tool_result"]
            status_messages = [r for r in results if r.get("type") == "status"]
            other_messages = [
                r for r in results if r.get("type") not in ["tool_call", "tool_result", "status", "message"]
            ]
            text_messages = [r for r in results if r.get("type") == "message"]

            if tool_call_messages:
                return tool_call_messages[0]
            elif tool_result_messages:
                return tool_result_messages[0]
            elif status_messages:
                return status_messages[0]
            elif other_messages:
                return other_messages[0]
            elif text_messages:
                return text_messages[0]

        return None

    def _is_tool_output(self, text: str) -> bool:
        """Check if text is a JSON array likely representing tool output."""
        import json

        text_stripped = text.strip()
        if text_stripped.startswith("[") and text_stripped.endswith("]"):
            try:
                parsed = json.loads(text_stripped)
                return isinstance(parsed, list) and len(parsed) > 0
            except json.JSONDecodeError:
                return False
        return False

    def _format_tool_output(self, text: str) -> Optional[str]:
        """Format tool output into a friendly text."""
        import json

        try:
            items = json.loads(text.strip())
            if not isinstance(items, list):
                return None

            formatted_lines: List[str] = []
            for item in items:
                if isinstance(item, list) and len(item) > 0:
                    main_item = item[0] if isinstance(item[0], str) else str(item[0])

                    if main_item.startswith("/") or ("/" in main_item and "." in main_item):
                        formatted_lines.append(f"📁 {main_item}")
                        for sub_item in item[1:]:
                            if isinstance(sub_item, str) and sub_item.strip():
                                if sub_item.startswith("/"):
                                    formatted_lines.append(f"   📄 {sub_item}")
                                else:
                                    formatted_lines.append(f"   • {sub_item}")
                    else:
                        formatted_lines.append(f"• {main_item}")
                        for sub_item in item[1:]:
                            if isinstance(sub_item, str) and sub_item.strip():
                                formatted_lines.append(f"   • {sub_item}")
                elif isinstance(item, str):
                    if item.startswith("/"):
                        formatted_lines.append(f"📁 {item}")
                    else:
                        formatted_lines.append(f"• {item}")

            return "\n".join(formatted_lines) if formatted_lines else None

        except (json.JSONDecodeError, Exception):
            return None

    def _has_complete_sentence(self, text: str) -> bool:
        """Heuristic detection for complete sentences to decide flush timing."""
        import re

        text_stripped = text.strip()
        if len(text_stripped) < 20:
            return False

        end_chars = [".", "!", "?", "。", "！", "？", "\n"]
        ends_with_sentence = any(text_stripped.endswith(char) for char in end_chars)

        sentence_patterns = [
            r".*[。！？]\s*$",
            r"[.!?]\s*$",
            r"：\s*.*[。！？.!?]",
            r"\s*\n\s*$",
        ]
        has_sentence_structure = any(re.match(pattern, text_stripped) for pattern in sentence_patterns)

        avoid_split_patterns = [
            r".*```$",
            r".*`[^`]*$",
            r".*\d+\.$",
            r".*[-*+]\s*$",
        ]
        should_avoid_split = any(re.match(pattern, text_stripped) for pattern in avoid_split_patterns)

        return ends_with_sentence and has_sentence_structure and not should_avoid_split

    def flush_pending_text(self, final: bool = False) -> List[Dict[str, Any]]:
        """Force flush accumulated text buffer."""
        results: List[Dict[str, Any]] = []
        if self.pending_text and (final or self.pending_text.strip()):
            text_to_send = self.pending_text.rstrip()
            if text_to_send:
                results.append(
                    {
                        "type": "message",
                        "content": text_to_send,
                        "session_id": self.session_id,
                        "is_stream": not final,
                    }
                )
                self.pending_text = ""

        if final:
            self.sent_thinking = False
            self.is_thinking = False
            self.has_sent_thinking_for_current_request = False

        return results

    def get_memory_files(self) -> List[str]:
        """Get list of memory files for this session."""
        memory_files: List[str] = []
        if self.memory_dir.exists():
            for file_path in self.memory_dir.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(self.memory_dir)
                    memory_files.append(str(relative_path))
        return memory_files

    def read_memory_file(self, file_path: str) -> str:
        """Read content from a memory file."""
        full_path = self.memory_dir / file_path
        if full_path.exists() and full_path.is_file():
            return full_path.read_text(encoding="utf-8")
        return ""

    def write_memory_file(self, file_path: str, content: str) -> None:
        """Write content to a memory file."""
        full_path = self.memory_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
