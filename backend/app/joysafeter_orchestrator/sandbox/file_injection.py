"""Strategy-based file injection into sandbox containers.

Selection priority:
1. PresignedUrlStrategy  — S3 storage + runner supports URL download
2. GrpcStreamStrategy    — runner supports FileMount proto processing
3. HostMountStrategy     — non-pool sandbox with workspace bind mount
4. ProviderStrategy      — fallback: delegate to SandboxProvider.inject_files
"""

import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional, Protocol

from app.joysafeter_orchestrator.sandbox.archive_utils import auto_extract_archive
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.storage.base import StorageBackend

if TYPE_CHECKING:
    from app.joysafeter_orchestrator.sandbox.provider import SandboxProvider

logger = logging.getLogger(__name__)


def _log_boundary_failure(
    *,
    code: str,
    message: str,
    operation: str,
    error: Exception | None = None,
    data: dict[str, object] | None = None,
    retryable: bool = True,
    user_action: str | None = "retry",
) -> None:
    logger.warning(
        message,
        extra={
            "error": async_boundary_error_payload(
                code=code,
                message=message,
                boundary="file_injection",
                operation=operation,
                data=data,
                retryable=retryable,
                user_action=user_action,
                detail=error.__class__.__name__ if error is not None else None,
            )
        },
        exc_info=error is not None,
    )


class InjectionStrategy(str, Enum):
    """File injection strategy — mirrors Rust InjectionStrategy."""

    PRESIGNED_URL = "presigned_url"
    GRPC_STREAM = "grpc_stream"
    HOST_MOUNT = "host_mount"
    PROVIDER_FALLBACK = "provider_fallback"


@dataclass
class FileToInject:
    """A file ready for injection — mirrors Rust FileToInject."""

    filename: str
    mount_path: str
    content: bytes | None = None
    storage_key: str | None = None
    size_bytes: int = 0
    url: str | None = None


@dataclass
class SessionFileRecord:
    mount_path: str
    storage_key: str
    filename: str
    size_bytes: int


@dataclass
class FileInjectionContext:
    session_id: uuid.UUID
    external_id: str
    workspace_path: Optional[str]
    provider: "SandboxProvider"
    storage: StorageBackend
    runner_capabilities: set[str] = field(default_factory=set)
    is_pool_sandbox: bool = False


class FileInjectionStrategy(Protocol):
    @property
    def name(self) -> str: ...
    async def inject(self, ctx: FileInjectionContext, files: list[SessionFileRecord]) -> int: ...


# ---------------------------------------------------------------------------
# Shared DB query
# ---------------------------------------------------------------------------


async def load_session_files(session_id: uuid.UUID) -> list[SessionFileRecord]:
    from sqlalchemy import select

    from app.joysafeter_domain.models.joysafeter_file import JoySafeterFile
    from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
    from app.joysafeter_shared.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(JoySafeterSessionFile, JoySafeterFile)
            .join(JoySafeterFile, JoySafeterSessionFile.file_id == JoySafeterFile.id)
            .where(JoySafeterSessionFile.session_id == session_id)
        )
        rows = result.all()

    return [
        SessionFileRecord(
            mount_path=sf.mount_path,
            storage_key=f.storage_key,
            filename=f.filename,
            size_bytes=f.size_bytes or 0,
        )
        for sf, f in rows
    ]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


class PresignedUrlStrategy:
    """Generate presigned URLs for runner to download directly from object storage."""

    @property
    def name(self) -> str:
        return "presigned_url"

    async def inject(self, ctx: FileInjectionContext, files: list[SessionFileRecord]) -> int:
        count = 0
        for f in files:
            url = await ctx.storage.presign_url(f.storage_key, expires=3600)
            if url:
                count += 1
                logger.debug("PresignedUrl ready: %s -> %s", f.filename, f.mount_path)
        if count:
            logger.info("Generated %d presigned URLs for session %s", count, ctx.session_id)
        return count


class GrpcStreamStrategy:
    """Send file bytes inline via gRPC SetupSandbox/StartTask FileMount field."""

    @property
    def name(self) -> str:
        return "grpc_stream"

    async def inject(self, ctx: FileInjectionContext, files: list[SessionFileRecord]) -> int:
        count = 0
        for f in files:
            try:
                await ctx.storage.get(f.storage_key)
                count += 1
            except Exception as e:
                _log_boundary_failure(
                    code="FILE_INJECTION_GRPC_LOAD_FAILED",
                    message="gRPC file injection failed to load file bytes",
                    operation="grpc_stream_load_file",
                    error=e,
                    data={
                        "session_id": str(ctx.session_id),
                        "filename": f.filename,
                        "storage_key": f.storage_key,
                        "mount_path": f.mount_path,
                    },
                )
        return count


class HostMountStrategy:
    """Write files to host workspace directory; visible via container bind mount."""

    @property
    def name(self) -> str:
        return "host_mount"

    async def inject(self, ctx: FileInjectionContext, files: list[SessionFileRecord]) -> int:
        if not ctx.workspace_path:
            return 0

        count = 0
        for f in files:
            try:
                relative = f.mount_path.lstrip("/")
                if relative.startswith("workspace/"):
                    relative = relative[len("workspace/") :]
                host_file_path = os.path.realpath(os.path.join(ctx.workspace_path, relative))
                if not host_file_path.startswith(os.path.realpath(ctx.workspace_path)):
                    _log_boundary_failure(
                        code="FILE_INJECTION_PATH_TRAVERSAL_BLOCKED",
                        message="Host mount file injection blocked path traversal",
                        operation="host_mount_validate_path",
                        data={
                            "session_id": str(ctx.session_id),
                            "filename": f.filename,
                            "mount_path": f.mount_path,
                        },
                        retryable=False,
                        user_action=None,
                    )
                    continue

                os.makedirs(os.path.dirname(host_file_path), exist_ok=True)
                data = await ctx.storage.get(f.storage_key)
                with open(host_file_path, "wb") as fh:
                    fh.write(data)
                try:
                    auto_extract_archive(host_file_path)
                except Exception as e:
                    _log_boundary_failure(
                        code="FILE_INJECTION_AUTO_EXTRACT_FAILED",
                        message="Host mount file injection failed to auto-extract archive",
                        operation="host_mount_auto_extract",
                        error=e,
                        data={
                            "session_id": str(ctx.session_id),
                            "filename": f.filename,
                            "mount_path": f.mount_path,
                        },
                    )
                count += 1
            except Exception as e:
                _log_boundary_failure(
                    code="FILE_INJECTION_HOST_WRITE_FAILED",
                    message="Host mount file injection failed to write file",
                    operation="host_mount_write_file",
                    error=e,
                    data={
                        "session_id": str(ctx.session_id),
                        "filename": f.filename,
                        "storage_key": f.storage_key,
                        "mount_path": f.mount_path,
                    },
                )
        return count


class ProviderStrategy:
    """Fallback: delegate to SandboxProvider.inject_files (e.g., docker cp)."""

    @property
    def name(self) -> str:
        return "provider"

    async def inject(self, ctx: FileInjectionContext, files: list[SessionFileRecord]) -> int:
        if not ctx.external_id:
            return 0
        await ctx.provider.inject_files(ctx.external_id, ctx.session_id)
        return len(files)


# ---------------------------------------------------------------------------
# Strategy selection
# ---------------------------------------------------------------------------


def select_strategies(ctx: FileInjectionContext) -> list[FileInjectionStrategy]:
    strategies: list[FileInjectionStrategy] = []

    if "url_download" in ctx.runner_capabilities:
        strategies.append(PresignedUrlStrategy())

    if "file_mount" in ctx.runner_capabilities:
        strategies.append(GrpcStreamStrategy())

    if ctx.workspace_path and not ctx.is_pool_sandbox:
        strategies.append(HostMountStrategy())

    strategies.append(ProviderStrategy())
    return strategies


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


async def inject_session_files(ctx: FileInjectionContext) -> None:
    """Load session file records and inject using the best available strategy."""
    files = await load_session_files(ctx.session_id)
    if not files:
        return

    for strategy in select_strategies(ctx):
        try:
            count = await strategy.inject(ctx, files)
            if count > 0:
                logger.info(
                    "Injected %d files via %s for session %s",
                    count,
                    strategy.name,
                    ctx.session_id,
                )
                return
        except Exception as e:
            _log_boundary_failure(
                code="FILE_INJECTION_STRATEGY_FAILED",
                message="File injection strategy failed; trying next strategy",
                operation="run_injection_strategy",
                error=e,
                data={"session_id": str(ctx.session_id), "strategy": strategy.name},
            )

    _log_boundary_failure(
        code="FILE_INJECTION_ALL_STRATEGIES_FAILED",
        message="All file injection strategies failed",
        operation="inject_session_files",
        data={"session_id": str(ctx.session_id), "file_count": len(files)},
    )
