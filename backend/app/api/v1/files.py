"""
Module: Files API

Overview:
- Provides file upload, read, delete, clear, and list operations within a user's sandbox
- Supports text and binary uploads via direct filesystem write to sandbox host mount
- Files are stored in the Docker sandbox host directory and accessible to the Agent
  via FilesystemMiddleware at /workspace/uploads/

Routes:
- POST /files/upload: Upload a file
- GET /files/list: List files
- GET /files/read/{filename}: Read file content
- DELETE /files/{filename}: Delete specified file
- DELETE /files: Clear all files in upload directory

Dependencies:
- Auth: CurrentUser
- Storage: Docker sandbox host mount directory
- Unified response: BaseResponse[T]

Security notes:
- Always use sanitize_filename() to avoid path traversal
- Upload directory is scoped to /tmp/sandboxes/{user_id}/uploads/

Error codes:
- 404: File not found
- 500: File upload/read/delete failed
"""

import base64
import mimetypes
import os
import shutil
import uuid
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
from app.utils.sandbox_paths import get_user_sandbox_host_dir

# Container-side path for uploaded files (what the Agent sees)
CONTAINER_UPLOADS_PATH = f"{DEFAULT_WORKING_DIR}/{SANDBOX_UPLOADS_SUBDIR}"

router = APIRouter(prefix="/v1/files", tags=["Files"])

# File upload security limits (matching frontend)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB
MAX_STORAGE_PER_USER = 5 * 1024 * 1024 * 1024  # 5GB per user
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".epub",
    ".txt",
    ".csv",
    ".md",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".py",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".json",
    ".jsx",
    ".tsx",
    ".vue",
    ".svelte",
    ".jpeg",
    ".jpg",
    ".png",
    ".gif",
    ".webp",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".apk",
}


class FileInfo(BaseModel):
    """File information"""

    filename: str
    size: int
    path: str


class FileListResponse(BaseModel):
    """File list response"""

    files: list[FileInfo]
    total: int


class UploadResponse(BaseModel):
    """Upload response"""

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
    ".doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],  # OLE2 (MS Office)
    ".docx": [b"PK\x03\x04"],  # DOCX is a ZIP file
    ".xls": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],  # OLE2
    ".xlsx": [b"PK\x03\x04"],  # XLSX is a ZIP file
    ".ppt": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],  # OLE2
    ".pptx": [b"PK\x03\x04"],  # PPTX is a ZIP file
    ".apk": [b"PK\x03\x04"],  # APK is a ZIP file
}


def validate_file_content(filename: str, content: bytes) -> None:
    """Validate file content using magic number (file signature) check."""
    if len(content) == 0:
        return

    file_ext = Path(filename).suffix.lower()
    if file_ext not in MAGIC_NUMBERS:
        return

    expected_signatures = MAGIC_NUMBERS[file_ext]
    content_start = content[: max(len(sig) for sig in expected_signatures)]
    matches = any(content_start.startswith(sig) for sig in expected_signatures)

    if not matches:
        logger.warning(
            f"File content validation failed for {filename}: "
            f"expected signature for {file_ext}, got {content_start[:16].hex()}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match declared type: {file_ext} files should contain correct file signature",
        )


def validate_file_type(filename: str, content_type: str | None) -> None:
    """Validate file type (extension and MIME type)."""
    file_ext = Path(filename).suffix.lower()

    if file_ext and file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {file_ext} is not supported")

    if content_type:
        inferred_type, _ = mimetypes.guess_type(filename)
        if inferred_type and content_type != inferred_type:
            logger.warning(f"MIME type mismatch for {filename}: expected {inferred_type}, got {content_type}")


def _get_upload_dir(user_id: uuid.UUID | str) -> Path:
    """Get the user's sandbox upload directory (host-side path). Does not create it."""
    return get_user_sandbox_host_dir(str(user_id)) / SANDBOX_UPLOADS_SUBDIR


def _ensure_upload_dir(user_id: uuid.UUID | str) -> Path:
    """Get the user's sandbox upload directory, creating it if needed."""
    upload_dir = _get_upload_dir(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def get_container_path(filename: str) -> str:
    """Get the container-side path for a file (what the Agent sees)."""
    return f"{CONTAINER_UPLOADS_PATH}/{filename}"


def _get_upload_dir_size(upload_dir: Path) -> int:
    """Calculate total size of files in the upload directory using scandir for efficiency."""
    total = 0
    try:
        for entry in os.scandir(upload_dir):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
    except FileNotFoundError:
        return 0
    except Exception as e:
        logger.warning(f"Failed to calculate storage usage: {e}")
        return 0
    return total


def validate_file_upload(
    filename: str,
    content: bytes,
    content_type: str | None,
    upload_dir: Path,
) -> tuple[str, None] | tuple[None, HTTPException]:
    """Validate file upload (size, type, content, storage quota)."""
    if len(content) == 0:
        return None, HTTPException(status_code=400, detail="File cannot be empty")

    if len(content) > MAX_FILE_SIZE_BYTES:
        return None, HTTPException(
            status_code=413, detail=f"File size exceeds maximum allowed size ({MAX_FILE_SIZE_BYTES / 1024 / 1024}MB)"
        )

    safe_filename = sanitize_filename(filename)

    try:
        validate_file_type(safe_filename, content_type)
    except HTTPException as e:
        return None, e

    try:
        validate_file_content(safe_filename, content)
    except HTTPException as e:
        return None, e

    current_usage = _get_upload_dir_size(upload_dir)
    if current_usage + len(content) > MAX_STORAGE_PER_USER:
        return None, HTTPException(
            status_code=413,
            detail=f"Storage quota exceeded. Current usage: {current_usage / 1024 / 1024 / 1024:.2f}GB, "
            f"maximum allowed: {MAX_STORAGE_PER_USER / 1024 / 1024 / 1024}GB. Please delete some files first.",
        )

    return safe_filename, None


@router.post(
    "/upload",
    response_model=BaseResponse[UploadResponse],
    summary="Upload file",
    description="Upload a file to the user's sandbox. The file will be accessible to the Agent at /workspace/uploads/.",
    responses={
        400: {"description": "Invalid file type"},
        413: {"description": "File size exceeds limit"},
        401: {"description": "Unauthorized"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Failed to upload file / Internal server error"},
    },
)
@rate_limit(max_requests=10, window_seconds=60)
async def upload_file(
    request: Request,
    current_user: CurrentUser,
    file: UploadFile = File(..., description="File to upload"),
) -> BaseResponse[UploadResponse]:
    """Upload a file to the user's sandbox upload directory."""
    client_ip = get_client_ip(request)
    original_filename = file.filename or "unnamed"

    try:
        content = await file.read()
        upload_dir = _ensure_upload_dir(current_user.id)

        safe_filename, validation_error = validate_file_upload(
            original_filename, content, file.content_type, upload_dir,
        )
        if validation_error:
            logger.warning(
                f"File upload rejected: user={current_user.id}, filename={original_filename}, ip={client_ip}"
            )
            raise validation_error

        assert safe_filename is not None

        file_path = upload_dir / safe_filename
        with open(file_path, "wb") as f:
            f.write(content)

        container_path = get_container_path(safe_filename)

        logger.info(
            f"File uploaded to sandbox: user={current_user.id}, "
            f"filename={safe_filename}, size={len(content)}, container_path={container_path}, ip={client_ip}"
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
        500: {"description": "Failed to list files / Internal server error"},
    },
)
async def list_files(current_user: CurrentUser) -> BaseResponse[FileListResponse]:
    """List all files in the user's sandbox upload directory."""
    try:
        upload_dir = _get_upload_dir(current_user.id)

        files = []
        try:
            for entry in os.scandir(upload_dir):
                if entry.is_file(follow_symlinks=False):
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        size = 0
                    files.append(
                        FileInfo(
                            filename=entry.name,
                            size=size,
                            path=get_container_path(entry.name),
                        )
                    )
        except FileNotFoundError:
            pass  # Directory doesn't exist yet — return empty list

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
        500: {"description": "Failed to read file / Internal server error"},
    },
)
async def read_file(request: Request, filename: str, current_user: CurrentUser) -> BaseResponse[dict]:
    """Read file content from the user's sandbox upload directory."""
    client_ip = get_client_ip(request)

    try:
        upload_dir = _get_upload_dir(current_user.id)
        safe_filename = sanitize_filename(filename)
        file_path = upload_dir / safe_filename

        # Open directly, catch FileNotFoundError (avoids TOCTOU race)
        try:
            with open(file_path, "rb") as f:
                content_bytes = f.read()
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")

        try:
            content = content_bytes.decode("utf-8")
            is_binary = False
        except UnicodeDecodeError:
            content = base64.b64encode(content_bytes).decode("ascii")
            is_binary = True

        logger.info(
            f"File read: user={current_user.id}, filename={safe_filename}, "
            f"size={len(content_bytes)}, ip={client_ip}"
        )

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
        500: {"description": "Failed to delete file / Internal server error"},
    },
)
async def delete_file(request: Request, filename: str, current_user: CurrentUser) -> BaseResponse[dict]:
    """Delete a file from the user's sandbox upload directory."""
    client_ip = get_client_ip(request)

    try:
        upload_dir = _get_upload_dir(current_user.id)
        safe_filename = sanitize_filename(filename)
        file_path = upload_dir / safe_filename

        # Unlink directly, catch FileNotFoundError (avoids TOCTOU race)
        try:
            file_path.unlink()
        except FileNotFoundError:
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
        500: {"description": "Failed to clear files / Internal server error"},
    },
)
async def clear_all_files(request: Request, current_user: CurrentUser) -> BaseResponse[dict]:
    """Clear all files in the user's sandbox upload directory."""
    client_ip = get_client_ip(request)

    try:
        upload_dir = _get_upload_dir(current_user.id)

        if upload_dir.exists():
            shutil.rmtree(upload_dir)

        # Recreate empty directory for future uploads
        upload_dir.mkdir(parents=True, exist_ok=True)

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
