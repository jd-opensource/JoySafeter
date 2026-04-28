# backend/app/core/observation/instrumentation/cli_extractor.py
"""CLI message stream → observation extractor for CLI engines."""
from __future__ import annotations

from app.core.agent.cli_backends.base import CLIMessage
from app.core.observation.collector import ObservationCollector
from app.core.observation.types import ObservationType, SpanHandle


FILE_TOOLS = frozenset({
    "read_file", "write_file", "create_file", "edit_file",
    "Read", "Write", "Edit", "Glob", "Grep",
})


class CLIObservationExtractor:
    def __init__(self, collector: ObservationCollector, root_span: SpanHandle):
        self._collector = collector
        self._root = root_span
        self._text_buffer: list[str] = []
        self._current_tool_span: SpanHandle | None = None
        self._current_usage: dict | None = None

    async def process_message(self, msg: CLIMessage) -> None:
        match msg.type:
            case "text":
                self._text_buffer.append(msg.content or "")

            case "tool_use":
                await self._flush_generation()
                tool_name = msg.tool_name or msg.tool or msg.content or "tool"
                tool_input = msg.tool_input or msg.input or {}
                self._current_tool_span = await self._root.child_span(
                    ObservationType.TOOL, name=tool_name,
                    input={"arguments": tool_input},
                )
                if tool_name in FILE_TOOLS:
                    path = tool_input.get("path", tool_input.get("file_path", ""))
                    op = (
                        "read"
                        if "read" in tool_name.lower() or tool_name in ("Read", "Glob", "Grep")
                        else "write"
                    )
                    await self._current_tool_span.record_event(
                        f"file:{op} {path}",
                        metadata={"file.path": path, "file.operation": op},
                    )

            case "tool_result":
                if self._current_tool_span:
                    await self._current_tool_span.end(
                        output={"result": msg.content}
                    )
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

        await self._collector.record_generation(
            "cli-generation",
            parent_id=self._root.observation_id,
            input=None,
            output={"completion": text},
            model=None,
            usage_details=usage if usage else None,
            cost_details=None,
            latency_ms=0,
        )
