"""
Module: Files API

Overview:
- Provides file upload, read, delete, clear, and list operations within a user's sandbox
- All operations go through PydanticSandboxAdapter (Docker sandbox API)
- Files are stored at /workspace/uploads/ inside the container and accessible to the Agent
  via FilesystemMiddleware

Routes:
- POST /files/upload: Upload a file
- GET /files/list: List files
- GET /files/read/{filename}: Read file content
- DELETE /files/{filename}: Delete specified file
- DELETE /files: Clear all files in upload directory

Dependencies:
- Auth: CurrentUser
- Storage: PydanticSandboxAdapter (Docker sandbox)
- Unified response: BaseResponse[T]

Security notes:
- Always use sanitize_filename() to avoid path traversal
- Upload directory is scoped to /workspace/uploads/ inside the container

Error codes:
- 404: File not found
- 500: File upload/read/delete failed
"""

import asyncio
import base64
import mimetypes
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from loguru import logger
from pydantic import BaseModel

from app.common.dependencies import CurrentUser
from app.core.agent.backends.constants import (
    DEFAULT_WORKING_DIR,
    SANDBOX_UPLOADS_SUBDIR,
)
from app.core.rate_limit import get_client_ip, rate_limit
from app.schemas import BaseResponse
from app.utils.path_utils import sanitize_filename

# Container-side path for uploaded files (what the Agent sees)
CONTAINER_UPLOADS_PATH = f"{DEFAULT_WORKING_DIR}/{SANDBOX_UPLOADS_SUBDIR}"

router = APIRouter(prefix="/v1/files", tags=["Files"])

# File upload security limits (matching frontend)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB
MAX_STORAGE_PER_USER = 5 * 1024 * 1024 * 1024  # 5GB per user
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".epub",
    ".txt", ".csv", ".md", ".html", ".css",
    ".js", ".ts", ".py", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
    ".sh", ".sql", ".yaml", ".yml", ".toml", ".xml", ".json",
    ".jsx", ".tsx", ".vue", ".svelte",
    ".jpeg", ".jpg", ".png", ".gif", ".webp",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".apk",
}


class FileInfo(BaseModel):
    filename: str
    size: int
    path: str


class FileListResponse(BaseModel):
    files: list[FileInfo]
    total: int


class UploadResponse(BaseModel):
    filename: str
    path: str
    size: int
    message: str


# Magic number signatures for file type validation
MAGIC_NUMBERS: dict[str, list[bytes]] = {
    ".pdf": [b"%PDF"],
    ".zip": [b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".webp": [b"RIFF", b"WEBP"],
    ".tar": [b"ustar", b"GNUtar"],
    ".gz": [b"\x1f\x8b"],
    ".7z": [b"7z\xbc\xaf\x27\x1c"],
    ".rar": [b"Rar!\x1a\x07", b"Rar!\x1a\x07\x00"],
    ".doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    ".docx": [b"PK\x03\x04"],
    ".xls": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    ".xlsx": [b"PK\x03\x04"],
    ".ppt": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    ".pptx": [b"PK\x03\x04"],
    ".apk": [b"PK\x03\x04"],
}


def _validate_file_content(filename: str, content: bytes) -> None:
    """Validate file content using magic number check."""
    if len(content) == 0:
        return
    file_ext = Path(filename).suffix.lower()
    if file_ext not in MAGIC_NUMBERS:
        return
    expected_signatures = MAGIC_NUMBERS[file_ext]
    content_start = content[: max(len(sig) for sig in expected_signatures)]
    if not any(content_start.startswith(sig) for sig in expected_signatures):
        logger.warning(f"File content validation failed for {filename}: got {content_start[:16].hex()}")
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match declared type: {file_ext}",
        )


def _validate_file_type(filename: str, content_type: str | None) -> None:
    """Validate file type (extension and MIME type)."""
    file_ext = Path(filename).suffix.lower()
    if file_ext and file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {file_ext} is not supported")
    if content_type:
        inferred_type, _ = mimetypes.guess_type(filename)
        if inferred_type and content_type != inferred_type:
            logger.warning(f"MIME type mismatch for {filename}: expected {inferred_type}, got {content_type}")


def get_container_path(filename: str) -> str:
    """Get the container-side path for a file (what the Agent sees)."""
    return f"{CONTAINER_UPLOADS_PATH}/{filename}"


async def _get_sandbox_handle(user_id: str):
    """Acquire a SandboxHandle for the user. Caller MUST release it."""
    from app.services.sandbox_manager import get_sandbox_handle

    return await get_sandbox_handle(user_id)


def _validate_file_upload(
    filename: str,
    content: bytes,
    content_type: str | None,
) -> tuple[str, None] | tuple[None, HTTPException]:
    """Validate file upload (size, type, content). Returns (safe_filename, None) or (None, error)."""
    if len(content) == 0:
        return None, HTTPException(status_code=400, detail="File cannot be empty")

    if len(content) > MAX_FILE_SIZE_BYTES:
        return None, HTTPException(
            status_code=413, detail=f"File size exceeds maximum allowed size ({MAX_FILE_SIZE_BYTES / 1024 / 1024}MB)"
        )

    safe_filename = sanitize_filename(filename)

    try:
        _validate_file_type(safe_filename, content_type)
    except HTTPException as e:
        return None, e

    try:
        _validate_file_content(safe_filename, content)
    except HTTPException as e:
        return None, e

    return safe_filename, None


@router.post(
    "/upload",
    response_model=BaseResponse[UploadResponse],
    summary="Upload file",
    description="Upload a file to the user's sandbox at /workspace/uploads/.",
    responses={
        400: {"description": "Invalid file type"},
        413: {"description": "File size exceeds limit"},
        401: {"description": "Unauthorized"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Failed to upload file"},
    },
)
@rate_limit(max_requests=10, window_seconds=60)
async def upload_file(
    request: Request,
    current_user: CurrentUser,
    file: UploadFile = File(..., description="File to upload"),
) -> BaseResponse[UploadResponse]:
    """Upload a file to the user's sandbox via adapter API."""
    client_ip = get_client_ip(request)
    original_filename = file.filename or "unnamed"

    try:
        content = await file.read()

        safe_filename, err = _validate_file_upload(original_filename, content, file.content_type)
        if err:
            logger.warning(f"File upload rejected: user={current_user.id}, filename={original_filename}, ip={client_ip}")
            raise err

        assert safe_filename is not None

        container_path = get_container_path(safe_filename)

        async with await _get_sandbox_handle(str(current_user.id)) as handle:
            await asyncio.to_thread(handle.adapter.mkdir, CONTAINER_UPLOADS_PATH)
            result = await asyncio.to_thread(handle.adapter.write_overwrite, container_path, content)
            if getattr(result, "error", None):
                raise HTTPException(status_code=500, detail=f"Failed to write file: {result.error}")

        logger.info(
            f"File uploaded to sandbox: user={current_user.id}, "
            f"filename={safe_filename}, size={len(content)}, path={container_path}, ip={client_ip}"
        )

        return BaseResponse(
            success=True,
            code=200,
            msg="File uploaded successfully",
            data=UploadResponse(
                filename=safe_filename,
                path=container_path,
                size=len(content),
                message=f"File {safe_filename} has been uploaded to your working directory",
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to upload file: user={current_user.id}, filename={original_filename}, ip={client_ip}, error={e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to upload file, please try again later") from e


@router.get(
    "/list",
    response_model=BaseResponse[FileListResponse],
    summary="List files",
    description="List all files in the user's sandbox upload directory.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Failed to list files"},
    },
)
async def list_files(current_user: CurrentUser) -> BaseResponse[FileListResponse]:
    """List all files in the user's sandbox upload directory via adapter API."""
    try:
        async with await _get_sandbox_handle(str(current_user.id)) as handle:
            infos = await asyncio.to_thread(handle.adapter.ls_info, CONTAINER_UPLOADS_PATH)

        files = [
            FileInfo(
                filename=Path(info["path"]).name,
                size=info.get("size", 0),
                path=info["path"],
            )
            for info in infos
            if not info.get("is_dir", False)
        ]

        return BaseResponse(
            success=True,
            code=200,
            msg="Fetched file list successfully",
            data=FileListResponse(files=files, total=len(files)),
        )
    except Exception as e:
        logger.error(f"Failed to list files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list files, please try again later") from e


@router.get(
    "/read/{filename}",
    response_model=BaseResponse[dict],
    summary="Read file content",
    description="Read the content of a file in the user's sandbox upload directory.",
    responses={
        404: {"description": "File not found"},
        500: {"description": "Failed to read file"},
    },
)
async def read_file(request: Request, filename: str, current_user: CurrentUser) -> BaseResponse[dict]:
    """Read file content from the user's sandbox via adapter API."""
    client_ip = get_client_ip(request)

    try:
        safe_filename = sanitize_filename(filename)
        container_path = get_container_path(safe_filename)

        async with await _get_sandbox_handle(str(current_user.id)) as handle:
            content = await asyncio.to_thread(handle.adapter.raw_read, container_path)

        if content.startswith("[Error:") or content.startswith("Error:"):
            raise HTTPException(status_code=404, detail="File not found")

        # raw_read returns text; for binary files it may be garbled
        is_binary = False
        try:
            content.encode("utf-8")
        except UnicodeEncodeError:
            content = base64.b64encode(content.encode("latin-1")).decode("ascii")
            is_binary = True

        logger.info(f"File read: user={current_user.id}, filename={safe_filename}, ip={client_ip}")

        return BaseResponse(
            success=True,
            code=200,
            msg="Read file successfully",
            data={"filename": safe_filename, "content": content, "is_binary": is_binary},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to read file: user={current_user.id}, filename={filename}, ip={client_ip}, error={e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to read file, please try again later") from e


@router.delete(
    "/{filename}",
    response_model=BaseResponse[dict],
    summary="Delete file",
    description="Delete a file from the user's sandbox upload directory.",
    responses={
        404: {"description": "File not found"},
        500: {"description": "Failed to delete file"},
    },
)
async def delete_file(request: Request, filename: str, current_user: CurrentUser) -> BaseResponse[dict]:
    """Delete a file from the user's sandbox via adapter API."""
    client_ip = get_client_ip(request)

    try:
        safe_filename = sanitize_filename(filename)
        container_path = get_container_path(safe_filename)

        async with await _get_sandbox_handle(str(current_user.id)) as handle:
            ok = await asyncio.to_thread(handle.adapter.delete, container_path)

        if not ok:
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")

        logger.info(f"File deleted: user={current_user.id}, filename={safe_filename}, ip={client_ip}")

        return BaseResponse(
            success=True,
            code=200,
            msg="File deleted successfully",
            data={"filename": safe_filename, "message": f"File {safe_filename} has been deleted"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to delete file: user={current_user.id}, filename={filename}, ip={client_ip}, error={e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to delete file, please try again later") from e


@router.delete(
    "",
    response_model=BaseResponse[dict],
    summary="Clear all files",
    description="Clear all files in the user's sandbox upload directory.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Failed to clear files"},
    },
)
async def clear_all_files(request: Request, current_user: CurrentUser) -> BaseResponse[dict]:
    """Clear all files in the user's sandbox upload directory via adapter API."""
    client_ip = get_client_ip(request)

    try:
        async with await _get_sandbox_handle(str(current_user.id)) as handle:
            await asyncio.to_thread(
                handle.adapter.execute, f"rm -rf {CONTAINER_UPLOADS_PATH}/*"
            )
            await asyncio.to_thread(handle.adapter.mkdir, CONTAINER_UPLOADS_PATH)

        logger.info(f"All files cleared: user={current_user.id}, ip={client_ip}")

        return BaseResponse(
            success=True,
            code=200,
            msg="Cleared files successfully",
            data={"message": "Cleared working directory"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear files: user={current_user.id}, ip={client_ip}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear files, please try again later") from e
