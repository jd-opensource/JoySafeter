"""File event emitter for real-time artifact preview during Agent execution."""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field


@dataclass
class FileEvent:
    """A single file operation event."""

    action: str  # "write" | "edit" | "delete"
    path: str
    size: int | None = None
    timestamp: float = field(default_factory=time.time)


class FileEventEmitter:
    """Thread-safe file event collector. Proxy emits, SSE loop drains."""

    def __init__(self) -> None:
        self._queue: collections.deque[FileEvent] = collections.deque()

    def emit(self, action: str, path: str, size: int | None = None) -> None:
        self._queue.append(FileEvent(action=action, path=path, size=size))

    def drain(self) -> list[FileEvent]:
        """Atomically pop all pending events. Uses popleft loop to avoid
        race between list()+clear() when emit() is called concurrently."""
        events: list[FileEvent] = []
        while self._queue:
            try:
                events.append(self._queue.popleft())
            except IndexError:
                break
        return events
