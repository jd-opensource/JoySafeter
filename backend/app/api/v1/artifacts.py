"""
Agent run artifacts API: list runs, list files, download, delete.

All paths are scoped by current user (user_id from CurrentUser).
"""

import mimetypes
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, PlainTextResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.common.exceptions import AppException, BadRequestException, InternalServerException, NotFoundException
from app.common.response import success_response
from app.core.agent.artifacts import ArtifactResolver, FileInfo, RunInfo
from app.core.database import get_db

router = APIRouter(prefix="/v1/artifacts", tags=["Artifacts"])


@lru_cache
def get_resolver() -> ArtifactResolver:
    return ArtifactResolver()


def _run_info_to_dict(r: RunInfo) -> dict:
    return {
        "run_id": r.run_id,
        "thread_id": r.thread_id,
        "user_id": r.user_id,
        "path": r.path,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "status": r.status,
        "agent_type": r.agent_type,
        "graph_id": r.graph_id,
        "file_count": r.file_count,
    }


def _file_info_to_dict(f: FileInfo) -> dict:
    d: dict[str, Any] = {
        "name": f.name,
        "path": f.path,
        "type": f.type,
        "size": f.size,
        "content_type": f.content_type,
    }
    if f.children is not None:
        d["children"] = [_file_info_to_dict(c) for c in f.children]
    return d


@router.get("/{thread_id}/runs")
async def list_artifact_runs(
    thread_id: str,
    current_user: CurrentUser,
    resolver: ArtifactResolver = Depends(get_resolver),
):
    """List all runs for the given thread (current user's artifacts)."""
    runs = resolver.list_runs(str(current_user.id), thread_id)
    data = [_run_info_to_dict(r) for r in runs]
    return {**success_response(data=data, message="Fetched runs"), "runs": data}


@router.get("/{thread_id}/{run_id}/files")
async def list_artifact_files(
    thread_id: str,
    run_id: str,
    current_user: CurrentUser,
    resolver: ArtifactResolver = Depends(get_resolver),
):
    """List files (tree) for the given run."""
    files = resolver.list_files_tree(str(current_user.id), thread_id, run_id)
    data = [_file_info_to_dict(f) for f in files]
    return {**success_response(data=data, message="Fetched files"), "files": data}


@router.get("/{thread_id}/{run_id}/download/{file_path:path}")
async def download_artifact_file(
    thread_id: str,
    run_id: str,
    file_path: str,
    current_user: CurrentUser,
    resolver: ArtifactResolver = Depends(get_resolver),
):
    """Download or preview a file from the run. Returns file with appropriate Content-Type."""
    path = resolver.get_file_path(str(current_user.id), thread_id, run_id, file_path)
    if path is None:
        raise NotFoundException("File not found or path invalid")
    filename = path.name
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=path,
        media_type=media_type or "application/octet-stream",
        filename=filename,
    )


@router.get("/{thread_id}/live/{file_path:path}")
async def live_read_file(
    thread_id: str,
    file_path: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Read a file directly from the running sandbox container (live preview during execution)."""
    from app.services.sandbox_manager import SandboxManagerService, _sandbox_pool

    service = SandboxManagerService(db)
    user_id = str(current_user.id)
    record = await service.get_user_sandbox_record(user_id)
    if not record:
        raise NotFoundException("No sandbox found")

    handle = None  # tracks SandboxHandle when reconnect path is used
    adapter = await _sandbox_pool.get(record.id)
    if not adapter or not adapter.is_started():
        if adapter:
            await _sandbox_pool.release(record.id)
            adapter = None
        # Sandbox disappeared from pool (process restart, idle cleanup, etc.)
        # Try to reconnect/restart it instead of failing immediately.
        try:
            handle = await service.ensure_sandbox_running(user_id)
            adapter = handle.adapter
        except Exception as e:
            logger.warning(f"Sandbox reconnect failed for user {user_id}: {e}")
            raise NotFoundException("Sandbox not running")

    try:
        raw_read = getattr(adapter, "raw_read", None)
        if callable(raw_read):
            content = raw_read(file_path)
        else:
            content = adapter.read(file_path)
        if content.startswith("[Error:") or content.startswith("Error:"):
            raise NotFoundException(content)
        return PlainTextResponse(content)
    except AppException:
        raise
    except Exception as e:
        logger.warning(f"Live read failed for {file_path}: {e}")
        raise InternalServerException(f"Failed to read file: {e}")
    finally:
        if handle:
            await handle.release()
        else:
            await _sandbox_pool.release(record.id)


@router.delete("/{thread_id}/{run_id}")
async def delete_artifact_run(
    thread_id: str,
    run_id: str,
    current_user: CurrentUser,
    resolver: ArtifactResolver = Depends(get_resolver),
):
    """Delete all artifacts for the given run."""
    ok = resolver.delete_run(str(current_user.id), thread_id, run_id)
    if not ok:
        raise BadRequestException("Delete failed or path invalid")
    return success_response(message="Run artifacts deleted", data={"run_id": run_id})
