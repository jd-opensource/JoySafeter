from __future__ import annotations

import asyncio
import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Coroutine

from app.utils.task_manager import task_manager

_UNSET = object()


@dataclass
class ChatTaskEntry:
    thread_id: str | None
    task: asyncio.Task[Any]
    heartbeat_task: asyncio.Task[Any] | None = None
    run_id: uuid_lib.UUID | None = None
    persist_on_disconnect: bool = False
    request_id: str = ""


class ChatTaskSupervisor:
    def __init__(
        self,
        *,
        stop_task: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._tasks: dict[str, ChatTaskEntry] = {}
        self._thread_to_request: dict[str, str] = {}
        self._stop_task = stop_task

    @property
    def tasks(self) -> dict[str, ChatTaskEntry]:
        return self._tasks

    def register(self, request_id: str, entry: ChatTaskEntry) -> None:
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
        entry = self._tasks.get(request_id)
        if entry is None:
            return None

        if thread_id is not _UNSET:
            entry.thread_id = thread_id
            self._bind_thread(request_id, thread_id)
        if task is not _UNSET:
            entry.task = task
        if heartbeat_task is not _UNSET:
            entry.heartbeat_task = heartbeat_task
        if run_id is not _UNSET:
            entry.run_id = run_id
        if persist_on_disconnect is not _UNSET:
            entry.persist_on_disconnect = persist_on_disconnect

        return entry

    def has_request(self, request_id: str) -> bool:
        return request_id in self._tasks

    def is_thread_active(self, thread_id: str) -> bool:
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
        entry = self._tasks.get(request_id)
        if entry is None:
            return

        if entry.thread_id:
            try:
                await self._stop_thread(entry.thread_id)
            except Exception:
                pass

        entry.task.cancel()
        if entry.heartbeat_task is not None:
            entry.heartbeat_task.cancel()

    async def finalize(self, request_id: str) -> ChatTaskEntry | None:
        entry = self._tasks.pop(request_id, None)
        if entry and entry.thread_id:
            self._thread_to_request.pop(entry.thread_id, None)
        if entry and entry.heartbeat_task is not None:
            entry.heartbeat_task.cancel()
            try:
                await entry.heartbeat_task
            except asyncio.CancelledError:
                pass
        return entry

    async def cancel_all(self) -> None:
        cancellable = [
            (request_id, entry) for request_id, entry in list(self._tasks.items()) if not entry.persist_on_disconnect
        ]

        for request_id, _ in cancellable:
            await self.stop_by_request_id(request_id)

        for request_id, entry in cancellable:
            try:
                await entry.task
            except BaseException:
                pass
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
