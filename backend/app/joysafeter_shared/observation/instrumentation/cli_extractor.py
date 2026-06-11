"""CLI message stream → observation extractor for CLI engines."""

from __future__ import annotations

from app.joysafeter_domain.agent.cli_backends.base import CLIMessage
from app.joysafeter_shared.observation.collector import ObservationCollector
from app.joysafeter_shared.observation.otel.span_wrapper import ObservationSpan
from app.joysafeter_shared.observation.types import ObservationType

FILE_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "create_file",
        "edit_file",
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
    }
)


class CLIObservationExtractor:
    def __init__(self, collector: ObservationCollector, root_span: ObservationSpan):
        self._collector = collector
        self._root = root_span
        self._text_buffer: list[str] = []
        self._current_tool_span: ObservationSpan | None = None
        self._current_usage: dict | None = None

    async def process_message(self, msg: CLIMessage) -> None:
        match msg.type:
            case "text":
                self._text_buffer.append(msg.content or "")

            case "tool_use":
                await self._flush_generation()
                tool_name = msg.tool_name or msg.tool or msg.content or "tool"
                tool_input = msg.tool_input or msg.input or {}
                self._current_tool_span = self._collector.child_span(
                    self._root,
                    ObservationType.TOOL,
                    name=tool_name,
                    input={"arguments": tool_input},
                )
                if tool_name in FILE_TOOLS:
                    path = tool_input.get("path", tool_input.get("file_path", ""))
                    op = "read" if "read" in tool_name.lower() or tool_name in ("Read", "Glob", "Grep") else "write"
                    self._collector.record_event(
                        f"file:{op} {path}",
                        parent=self._current_tool_span,
                        metadata={"file.path": path, "file.operation": op},
                    )

            case "tool_result":
                if self._current_tool_span:
                    self._current_tool_span.set_output({"result": msg.content})
                    self._current_tool_span.end()
                    self._current_tool_span = None

            case "usage":
                self._current_usage = msg.usage

    async def flush_pending(self) -> None:
        await self._flush_generation()

    async def _flush_generation(self) -> None:
        if not self._text_buffer:
            return
        text = "".join(self._text_buffer)
        self._text_buffer.clear()
        usage = self._current_usage or {}
        self._current_usage = None

        self._collector.record_generation(
            "cli-generation",
            parent=self._root,
            input=None,
            output={"completion": text},
            model=None,
            usage_details=usage if usage else None,
            cost_details=None,
        )
