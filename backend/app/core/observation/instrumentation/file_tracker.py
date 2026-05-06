"""File operation → EVENT observation tracker."""

from __future__ import annotations

from app.core.observation.collector import ObservationCollector
from app.core.observation.otel.span_wrapper import ObservationSpan


class FileOperationTracker:
    def __init__(
        self,
        collector: ObservationCollector,
        parent_span: ObservationSpan | None = None,
    ):
        self._collector = collector
        self._parent_span = parent_span

    async def track_write(self, path: str, content: bytes | str) -> None:
        size, preview = self._byte_len(content), None
        if isinstance(content, str):
            preview = content[:200]
        else:
            preview = content[:200].decode(errors="replace")
        await self._track(path, "write", size, content_preview=preview)

    async def track_read(self, path: str, content: bytes | str) -> None:
        await self._track(path, "read", self._byte_len(content))

    async def _track(self, path: str, operation: str, size: int, **extra: str | None) -> None:
        meta: dict = {"file.path": path, "file.operation": operation, "file.size_bytes": size}
        meta.update({k: v for k, v in extra.items() if v is not None})
        self._collector.record_event(
            f"file:{operation} {path}",
            parent=self._parent_span,
            metadata=meta,
        )

    @staticmethod
    def _byte_len(content: bytes | str) -> int:
        return len(content.encode() if isinstance(content, str) else content)
