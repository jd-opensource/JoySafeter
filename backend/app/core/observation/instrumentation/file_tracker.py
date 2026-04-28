# backend/app/core/observation/instrumentation/file_tracker.py
"""File operation → EVENT observation tracker."""
from __future__ import annotations

from typing import Any

from app.core.observation.collector import ObservationCollector
from app.core.observation.types import SpanHandle


class FileOperationTracker:
    def __init__(self, collector: ObservationCollector, parent_span: SpanHandle | None = None):
        self._collector = collector
        self._parent_span = parent_span

    async def track_write(self, path: str, content: bytes | str, **kwargs: Any) -> None:
        size = len(content.encode() if isinstance(content, str) else content)
        preview = (content[:200] if isinstance(content, str) else content[:200].decode(errors="replace"))
        parent_id = self._parent_span.observation_id if self._parent_span else None
        await self._collector.record_event(
            f"file:write {path}",
            parent_id=parent_id,
            metadata={"file.path": path, "file.operation": "write", "file.size_bytes": size, "file.content_preview": preview},
        )

    async def track_read(self, path: str, content: bytes | str, **kwargs: Any) -> None:
        size = len(content.encode() if isinstance(content, str) else content)
        parent_id = self._parent_span.observation_id if self._parent_span else None
        await self._collector.record_event(
            f"file:read {path}",
            parent_id=parent_id,
            metadata={"file.path": path, "file.operation": "read", "file.size_bytes": size},
        )
