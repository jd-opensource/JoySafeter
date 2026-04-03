"""Proxy that wraps SandboxBackendProtocol to emit file events on write operations."""

from __future__ import annotations

from typing import Any

from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
)

from app.utils.file_event_emitter import FileEventEmitter


class FileTrackingProxy(SandboxBackendProtocol):
    """Transparent proxy that intercepts write operations and emits file events.

    All non-write methods are delegated directly to the wrapped backend.
    Unknown methods are forwarded via __getattr__ for forward compatibility.
    """

    def __init__(self, backend: SandboxBackendProtocol, emitter: FileEventEmitter) -> None:
        self._backend = backend
        self._emitter = emitter

    # ── Write operations (intercepted) ──────────────────────────────────

    def write(self, file_path: str, content: str | bytes) -> WriteResult:
        result = self._backend.write(file_path, content)
        if not getattr(result, "error", None):
            size = len(content) if isinstance(content, bytes) else len(content.encode("utf-8"))
            self._emitter.emit("write", file_path, size)
        return result

    def write_overwrite(self, file_path: str, content: str | bytes) -> WriteResult:
        result: WriteResult = getattr(self._backend, "write_overwrite")(file_path, content)
        if not getattr(result, "error", None):
            size = len(content) if isinstance(content, bytes) else len(content.encode("utf-8"))
            self._emitter.emit("write", file_path, size)
        return result

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        result = self._backend.edit(file_path, old_string, new_string, replace_all)
        if not getattr(result, "error", None):
            self._emitter.emit("edit", file_path)
        return result

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results = self._backend.upload_files(files)
        for (path, content), resp in zip(files, results):
            if not getattr(resp, "error", None):
                self._emitter.emit("write", path, len(content))
        return results

    # ── Read operations (delegated) ─────────────────────────────────────

    def read(self, *args: Any, **kwargs: Any) -> str:
        return self._backend.read(*args, **kwargs)

    def raw_read(self, *args: Any, **kwargs: Any) -> str:
        return str(getattr(self._backend, "raw_read")(*args, **kwargs))

    def ls_info(self, path: str) -> list[FileInfo]:
        return self._backend.ls_info(path)

    def execute(self, command: str) -> ExecuteResponse:
        return self._backend.execute(command)

    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> list[GrepMatch] | str:
        return self._backend.grep_raw(pattern, path, glob)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return self._backend.glob_info(pattern, path)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self._backend.download_files(paths)

    # ── Lifecycle (delegated) ───────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._backend.id

    def is_started(self) -> bool:
        return getattr(self._backend, "is_started")()  # type: ignore[no-any-return]

    def start(self) -> None:
        getattr(self._backend, "start")()

    def stop(self) -> None:
        getattr(self._backend, "stop")()

    def cleanup(self) -> None:
        getattr(self._backend, "cleanup")()

    # ── Forward compatibility ───────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)
