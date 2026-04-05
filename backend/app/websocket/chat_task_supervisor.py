"""Supervisor for cancellable async tasks tied to a WebSocket connection."""

from __future__ import annotations

import asyncio
import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Coroutine, cast

from loguru import logger

from app.utils.task_manager import task_manager

_UNSET = object()


@dataclass
class ChatTaskEntry:
    """Tracks an in-flight chat turn and its associated asyncio task."""

    thread_id: str | None
    task: asyncio.Task[Any]
    heartbeat_task: asyncio.Task[Any] | None = None
    run_id: uuid_lib.UUID | None = None
    persist_on_disconnect: bool = False
    request_id: str = ""


class ChatTaskSupervisor:
    """Manages the lifecycle of concurrent chat tasks for one connection.

    Provides request-id and thread-id based lookup, cancellation,
    and graceful cleanup on disconnect.
    """

    def __init__(
        self,
        *,
        stop_task: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the supervisor.

        Args:
            stop_task: Optional callback to stop a task by thread_id;
                falls back to the global task_manager.
        """
        self._tasks: dict[str, ChatTaskEntry] = {}
        self._thread_to_request: dict[str, str] = {}
        self._stop_task = stop_task

    @property
    def tasks(self) -> dict[str, ChatTaskEntry]:
        """Return the internal request_id-to-entry mapping."""
        return self._tasks

    def register(self, request_id: str, entry: ChatTaskEntry) -> None:
        """Register an already-created task entry."""
        if not entry.request_id:
            entry.request_id = request_id
        self._tasks[request_id] = entry
        self._bind_thread(request_id, entry.thread_id)

    def create_task(
        self,
        request_id: str,
        runner: Coroutine[Any, Any, Any],
        *,
        name: str,
        thread_id: str | None,
        run_id: uuid_lib.UUID | None = None,
        persist_on_disconnect: bool = False,
    ) -> ChatTaskEntry:
        """Create an asyncio task from a coroutine, register it, and return the entry."""
        task = asyncio.create_task(runner, name=name)
        entry = ChatTaskEntry(
            request_id=request_id,
            thread_id=thread_id,
            task=task,
            run_id=run_id,
            persist_on_disconnect=persist_on_disconnect,
        )
        self.register(request_id, entry)
        return entry

    def get(self, request_id: str) -> ChatTaskEntry | None:
        """Look up a task entry by request_id."""
        return self._tasks.get(request_id)

    def update(
        self,
        request_id: str,
        *,
        thread_id: str | None | object = _UNSET,
        task: asyncio.Task[Any] | object = _UNSET,
        heartbeat_task: asyncio.Task[Any] | None | object = _UNSET,
        run_id: uuid_lib.UUID | None | object = _UNSET,
        persist_on_disconnect: bool | object = _UNSET,
    ) -> ChatTaskEntry | None:
        """Patch fields on an existing entry, skipping any that are _UNSET."""
        entry = self._tasks.get(request_id)
        if entry is None:
            return None

        if thread_id is not _UNSET:
            thread_id_value = cast(str | None, thread_id)
            entry.thread_id = thread_id_value
            self._bind_thread(request_id, thread_id_value)
        if task is not _UNSET:
            entry.task = cast(asyncio.Task[Any], task)
        if heartbeat_task is not _UNSET:
            entry.heartbeat_task = cast(asyncio.Task[Any] | None, heartbeat_task)
        if run_id is not _UNSET:
            entry.run_id = cast(uuid_lib.UUID | None, run_id)
        if persist_on_disconnect is not _UNSET:
            entry.persist_on_disconnect = cast(bool, persist_on_disconnect)

        return entry

    def has_request(self, request_id: str) -> bool:
        """Return True if a task is tracked under the given request_id."""
        return request_id in self._tasks

    def is_thread_active(self, thread_id: str) -> bool:
        """Return True if any tracked task is running on the given thread."""
        request_id = self._thread_to_request.get(thread_id)
        if request_id is not None:
            entry = self._tasks.get(request_id)
            if entry is not None and entry.thread_id == thread_id:
                return True
            self._thread_to_request.pop(thread_id, None)

        for mapped_request_id, entry in self._tasks.items():
            if entry.thread_id == thread_id:
                self._thread_to_request[thread_id] = mapped_request_id
                return True
        return False

    async def stop_by_request_id(self, request_id: str) -> None:
        """Signal a stop and cancel the asyncio task for the given request."""
        entry = self._tasks.get(request_id)
        if entry is None:
            return

        if entry.thread_id:
            try:
                await self._stop_thread(entry.thread_id)
            except Exception:
                logger.debug("chat task supervisor cleanup error", exc_info=True)

        entry.task.cancel()
        if entry.heartbeat_task is not None:
            entry.heartbeat_task.cancel()

    async def finalize(self, request_id: str) -> ChatTaskEntry | None:
        """Remove a task entry and cancel its heartbeat, returning the entry."""
        entry = self._tasks.pop(request_id, None)
        if entry and entry.thread_id:
            self._thread_to_request.pop(entry.thread_id, None)
        if entry and entry.heartbeat_task is not None:
            entry.heartbeat_task.cancel()
            try:
                await entry.heartbeat_task
            except asyncio.CancelledError:
                logger.debug("task cancelled during cleanup")
        return entry

    async def cancel_all(self) -> None:
        """Cancel all non-persistent tasks and await their completion."""
        cancellable = [
            (request_id, entry) for request_id, entry in list(self._tasks.items()) if not entry.persist_on_disconnect
        ]

        for request_id, _ in cancellable:
            await self.stop_by_request_id(request_id)

        for request_id, entry in cancellable:
            try:
                await entry.task
            except BaseException:
                logger.debug("suppressed exception during final cleanup", exc_info=True)
            if request_id in self._tasks:
                await self.finalize(request_id)

    def _bind_thread(self, request_id: str, thread_id: str | None) -> None:
        for existing_thread_id, existing_request_id in list(self._thread_to_request.items()):
            if existing_request_id == request_id:
                self._thread_to_request.pop(existing_thread_id, None)
        if thread_id:
            self._thread_to_request[thread_id] = request_id

    async def _stop_thread(self, thread_id: str) -> None:
        if self._stop_task is not None:
            await self._stop_task(thread_id)
            return
        await task_manager.stop_task(thread_id)
