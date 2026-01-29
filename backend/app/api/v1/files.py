"""
Module: Files API

Overview:
- Provides file upload, read, delete, clear, and list operations within a user's working directory
- Supports text and binary uploads; binary content falls back to direct filesystem write
- Isolated via FilesystemSandboxBackend, using virtual mode by default

Routes:
- POST /files/upload: Upload a file
- GET /files/list: List files
- GET /files/read/{filename}: Read file content
- DELETE /files/{filename}: Delete specified file
- DELETE /files: Clear all files in working directory

Dependencies:
- Auth: CurrentUser
- Storage: FilesystemSandboxBackend
- Unified response: BaseResponse[T]

Requests/Responses:
- Request model: UploadFile(File)
- Response models: FileInfo, FileListResponse, UploadResponse, BaseResponse[T]

Security notes:
- Always use Path(filename).name to avoid path traversal
- Backend commands are executed via sandbox backend, isolating user directory (virtual_mode=True)

Error codes:
- 404: File not found
- 500: File upload/read/delete failed
"""

import base64
import mimetypes
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from loguru import logger
from pydantic import BaseModel

from app.common.dependencies import CurrentUser
from app.core.agent.backends import FilesystemSandboxBackend
from app.core.rate_limit import rate_limit
from app.schemas import BaseResponse
from app.utils.path_utils import sanitize_filename as _sanitize_filename

# File storage root directory (configurable via environment variable)
FILE_STORAGE_ROOT = os.getenv("FILE_STORAGE_ROOT", "/app/data/files")

router = APIRouter(prefix="/files", tags=["Files"])

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


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing dangerous characters.

    Args:
        filename: Original filename

    Returns:
        str: Sanitized filename
    """
    return _sanitize_filename(filename)


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
    """
    Validate file content using magic number (file signature) check.
    This helps prevent file type spoofing by checking actual file content.

    Args:
        filename: Filename with extension
        content: File content bytes

    Raises:
        HTTPException: If file content doesn't match expected signature
    """
    if len(content) == 0:
        return  # Empty files are handled elsewhere

    file_ext = Path(filename).suffix.lower()

    # Only validate binary file types that have magic numbers
    if file_ext not in MAGIC_NUMBERS:
        # For text files and other types without magic numbers, skip validation
        # (they can be validated by extension and content analysis)
        return

    # Get expected magic numbers for this file type
    expected_signatures = MAGIC_NUMBERS[file_ext]

    # Check if content starts with any expected signature
    content_start = content[: max(len(sig) for sig in expected_signatures)]
    matches = any(content_start.startswith(sig) for sig in expected_signatures)

    if not matches:
        logger.warning(
            f"File content validation failed for {filename}: "
            f"expected signature for {file_ext}, got {content_start[:16].hex()}"
        )
        # For security, reject files that don't match their declared type
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match declared type: {file_ext} files should contain correct file signature",
        )


def validate_file_type(filename: str, content_type: str | None) -> None:
    """
    Validate file type (extension and MIME type).

    Args:
        filename: Filename with extension
        content_type: MIME type from upload request (optional)

    Raises:
        HTTPException: If file type is not allowed
    """
    file_ext = Path(filename).suffix.lower()

    # Validate extension
    if file_ext and file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {file_ext} is not supported")

    # Validate MIME type if provided (log warning if mismatch but allow, as some clients may be inaccurate)
    if content_type:
        inferred_type, _ = mimetypes.guess_type(filename)
        if inferred_type and content_type != inferred_type:
            logger.warning(f"MIME type mismatch for {filename}: expected {inferred_type}, got {content_type}")


def get_user_storage_usage(backend: FilesystemSandboxBackend) -> int:
    """
    Get the current storage usage for a user's backend directory.

    Args:
        backend: The user's filesystem backend

    Returns:
        int: Current storage usage in bytes
    """
    try:
        # Use 'du' command to calculate directory size
        result = backend.execute("du -sb . 2>/dev/null | cut -f1")
        if result.exit_code == 0 and result.output.strip():
            return int(result.output.strip())
    except (ValueError, Exception) as e:
        logger.warning(f"Failed to calculate storage usage: {e}")
    return 0


def validate_file_upload(
    filename: str,
    content: bytes,
    content_type: str | None,
    backend: FilesystemSandboxBackend,
    current_user_id: uuid.UUID | str,
    client_ip: str,
) -> tuple[str, None] | tuple[None, HTTPException]:
    """
    Validate file upload (size, type, content, storage quota).

    Args:
        filename: Original filename
        content: File content bytes
        content_type: MIME type from upload request
        backend: User's filesystem backend
        current_user_id: Current user ID
        client_ip: Client IP address

    Returns:
        Tuple of (safe_filename, None) if valid, or (None, HTTPException) if invalid
    """
    # Check for empty file
    if len(content) == 0:
        logger.warning(
            f"File upload rejected - empty file: user={current_user_id}, filename={filename}, ip={client_ip}"
        )
        return None, HTTPException(status_code=400, detail="File cannot be empty")

    # Validate file size
    if len(content) > MAX_FILE_SIZE_BYTES:
        logger.warning(
            f"File upload rejected - size exceeded: user={current_user_id}, "
            f"filename={filename}, size={len(content)}, "
            f"limit={MAX_FILE_SIZE_BYTES}, ip={client_ip}"
        )
        return None, HTTPException(
            status_code=413, detail=f"File size exceeds maximum allowed size ({MAX_FILE_SIZE_BYTES / 1024 / 1024}MB)"
        )

    # Sanitize filename
    safe_filename = sanitize_filename(filename)

    # Validate file type (extension and MIME type)
    try:
        validate_file_type(safe_filename, content_type)
    except HTTPException as e:
        return None, e

    # Validate file content (magic number check)
    try:
        validate_file_content(safe_filename, content)
    except HTTPException as e:
        return None, e

    # Check storage quota
    current_usage = get_user_storage_usage(backend)
    if current_usage + len(content) > MAX_STORAGE_PER_USER:
        logger.warning(
            f"File upload rejected - storage quota exceeded: user={current_user_id}, "
            f"filename={filename}, current_usage={current_usage}, "
            f"file_size={len(content)}, limit={MAX_STORAGE_PER_USER}, ip={client_ip}"
        )
        return None, HTTPException(
            status_code=413,
            detail=f"Storage quota exceeded. Current usage: {current_usage / 1024 / 1024 / 1024:.2f}GB, "
            f"maximum allowed: {MAX_STORAGE_PER_USER / 1024 / 1024 / 1024}GB. Please delete some files first.",
        )

    return safe_filename, None


def write_file_to_backend(
    backend: FilesystemSandboxBackend,
    filename: str,
    content: bytes,
    is_text: bool = False,
) -> Path:
    """
    Write file to backend directory (unified for both text and binary files).

    Args:
        backend: User's filesystem backend
        filename: Safe filename
        content: File content bytes
        is_text: Whether the file is text (can be decoded as UTF-8)

    Returns:
        Path: Path to the written file
    """
    file_path = Path(backend.cwd) / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if is_text:
        # For text files, try to use backend.write() if possible
        # Otherwise, write directly
        try:
            text_content = content.decode("utf-8")
            backend.write(filename, text_content)
            return file_path
        except Exception:
            # Fallback to direct write if backend.write fails
            pass

    # Write directly to filesystem (for binary files or as fallback)
    with open(file_path, "wb") as f:
        f.write(content)

    return file_path


def get_user_backend(user_id: uuid.UUID | str | None = None) -> FilesystemSandboxBackend:
    """
    Get the user's filesystem backend

    Args:
        user_id: User ID (optional, if None uses default user ID)

    Returns:
        FilesystemSandboxBackend: User's filesystem backend
    """
    # 如果 user_id 为 None，使用 "default"
    user_id = user_id or "default"

    # 使用环境变量配置的存储根目录，支持 Docker volume 映射
    # 默认使用 /tmp（开发环境），生产环境通过环境变量配置为 /app/data/files 等
    root_dir = Path(FILE_STORAGE_ROOT) / str(user_id)

    # 确保目录存在
    root_dir.mkdir(parents=True, exist_ok=True)

    return FilesystemSandboxBackend(
        root_dir=str(root_dir),
        virtual_mode=True,  # Use virtual mode, consistent with Agent
    )


@router.post(
    "/upload",
    response_model=BaseResponse[UploadResponse],
    summary="Upload file",
    description="Upload a file to the user's working directory. Supports text and binary content.",
    responses={
        400: {"description": "Invalid file type"},
        413: {"description": "File size exceeds limit"},
        401: {"description": "Unauthorized"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Failed to upload file / Internal server error"},
    },
)
@rate_limit(max_requests=10, window_seconds=60)  # 限制：每分钟最多10次上传
async def upload_file(
    request: Request,
    current_user: CurrentUser,
    file: UploadFile = File(..., description="File to upload"),
) -> BaseResponse[UploadResponse]:
    """
    Upload a file to the user's working directory

    Args:
        request: FastAPI request object (for rate limiting)
        file: File to upload
        current_user: Current authenticated user

    Returns:
        BaseResponse[UploadResponse]: Upload result
    """
    # Get client IP for logging
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    original_filename = file.filename or "unnamed"

    try:
        # Read file content
        content = await file.read()

        # Get user's backend
        backend = get_user_backend(current_user.id)

        # Validate file upload (size, type, content, storage quota)
        safe_filename, validation_error = validate_file_upload(
            original_filename,
            content,
            file.content_type,
            backend,
            current_user.id,
            client_ip,
        )
        if validation_error:
            raise validation_error

        # Type narrowing: safe_filename is guaranteed to be str after validation
        assert safe_filename is not None, "safe_filename should not be None after validation"

        # Determine if file is text (can be decoded as UTF-8)
        is_text = False
        try:
            content.decode("utf-8")
            is_text = True
        except UnicodeDecodeError:
            is_text = False

        # Write file (unified for both text and binary)
        file_path = write_file_to_backend(backend, safe_filename, content, is_text=is_text)

        # Enhanced logging with security context
        file_type = "text" if is_text else "binary"
        logger.info(
            f"{file_type.capitalize()} file uploaded successfully: user={current_user.id}, "
            f"original_filename={original_filename}, safe_filename={safe_filename}, "
            f"size={len(content)}, content_type={file.content_type}, ip={client_ip}"
        )

        return BaseResponse(
            success=True,
            code=200,
            msg="File uploaded successfully",
            data=UploadResponse(
                filename=safe_filename,
                path=str(file_path),
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
    description="List all files in the user's working directory.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Failed to list files / Internal server error"},
    },
)
async def list_files(current_user: CurrentUser) -> BaseResponse[FileListResponse]:
    """
    List all files in the user's working directory

    Args:
        current_user: Current authenticated user

    Returns:
        BaseResponse[FileListResponse]: File list
    """
    try:
        backend = get_user_backend(current_user.id)

        # Use backend.execute to list files
        result = backend.execute("find . -type f -exec ls -lh {} \\;")

        if result.exit_code != 0:
            logger.warning(f"Failed to list files for user {current_user.id}: {result.output}")
            return BaseResponse(
                success=True,
                code=200,
                msg="Fetched file list successfully",
                data=FileListResponse(files=[], total=0),
            )

        # Parse file list
        files = []
        for line in result.output.strip().split("\n"):
            if not line or line == "(no output)":
                continue

            parts = line.split()
            if len(parts) >= 9:
                size_str = parts[4]
                filename = " ".join(parts[8:])

                # Convert file size
                try:
                    if size_str.endswith("K"):
                        size = int(float(size_str[:-1]) * 1024)
                    elif size_str.endswith("M"):
                        size = int(float(size_str[:-1]) * 1024 * 1024)
                    elif size_str.endswith("G"):
                        size = int(float(size_str[:-1]) * 1024 * 1024 * 1024)
                    else:
                        size = int(size_str)
                except (ValueError, IndexError):
                    size = 0

                files.append(
                    FileInfo(
                        filename=Path(filename).name,
                        size=size,
                        path=filename,
                    )
                )

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
    description="Read the content of a file in the user's working directory.",
    responses={
        404: {"description": "File not found"},
        500: {"description": "Failed to read file / Internal server error"},
    },
)
async def read_file(request: Request, filename: str, current_user: CurrentUser) -> BaseResponse[dict]:
    """
    Read file content from the user's working directory

    Args:
        request: FastAPI request object (for logging)
        filename: Filename
        current_user: Current authenticated user

    Returns:
        BaseResponse[dict]: File content
    """
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    try:
        backend = get_user_backend(current_user.id)

        # Sanitize filename
        safe_filename = sanitize_filename(filename)

        # Read file - try as binary first, then fallback to text
        file_path = Path(backend.cwd) / safe_filename

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {safe_filename}")

        # Try to read as binary first to handle both text and binary files
        try:
            with open(file_path, "rb") as f:
                content_bytes = f.read()

            # Try to decode as UTF-8 for text files
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                # For binary files, return as base64 encoded string
                content = base64.b64encode(content_bytes).decode("ascii")
                # Mark as binary in response
                return BaseResponse(
                    success=True,
                    code=200,
                    msg="Read file successfully",
                    data={
                        "filename": safe_filename,
                        "content": content,
                        "is_binary": True,
                    },
                )
        except Exception as e:
            # Fallback to backend.read() for text files
            try:
                content = backend.read(safe_filename)
            except Exception:
                raise FileNotFoundError(f"Failed to read file: {safe_filename}") from e

        content_size = len(content.encode("utf-8")) if isinstance(content, str) else len(content)

        logger.info(f"File read: user={current_user.id}, filename={safe_filename}, size={content_size}, ip={client_ip}")

        return BaseResponse(
            success=True,
            code=200,
            msg="Read file successfully",
            data={"filename": safe_filename, "content": content, "is_binary": False},
        )
    except FileNotFoundError as e:
        logger.warning(f"File read failed - not found: user={current_user.id}, filename={filename}, ip={client_ip}")
        raise HTTPException(status_code=404, detail="File not found") from e
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
    description="Delete a file from the user's working directory.",
    responses={
        404: {"description": "File not found"},
        500: {"description": "Failed to delete file / Internal server error"},
    },
)
async def delete_file(request: Request, filename: str, current_user: CurrentUser) -> BaseResponse[dict]:
    """
    Delete a file from the user's working directory

    Args:
        request: FastAPI request object (for logging)
        filename: Filename
        current_user: Current authenticated user

    Returns:
        BaseResponse[dict]: Delete result
    """
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    try:
        backend = get_user_backend(current_user.id)

        # Sanitize filename
        safe_filename = sanitize_filename(filename)

        # Delete file using Python file operations instead of shell command (prevents command injection)
        file_path = Path(backend.cwd) / safe_filename

        if not file_path.exists():
            logger.warning(
                f"File delete failed - not found: user={current_user.id}, filename={filename}, ip={client_ip}"
            )
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")

        # Get file size before deletion for logging
        file_size = file_path.stat().st_size if file_path.exists() else 0

        try:
            file_path.unlink()
        except OSError as e:
            logger.error(
                f"Failed to delete file: user={current_user.id}, filename={safe_filename}, ip={client_ip}, error={e}",
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Failed to delete file, please try again later") from e

        logger.info(f"File deleted: user={current_user.id}, filename={safe_filename}, size={file_size}, ip={client_ip}")

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
    description="Clear all files in the user's working directory.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Failed to clear files / Internal server error"},
    },
)
async def clear_all_files(request: Request, current_user: CurrentUser) -> BaseResponse[dict]:
    """
    Clear all files in the user's working directory

    Args:
        request: FastAPI request object (for logging)
        current_user: Current authenticated user

    Returns:
        BaseResponse[dict]: Clear result
    """
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    try:
        backend = get_user_backend(current_user.id)

        # List all files
        result_before = backend.execute("ls -1")
        files_before = result_before.output.strip().split("\n") if result_before.output.strip() else []
        file_count = len([f for f in files_before if f and f != "(no output)"])

        # Delete all files (not directories)
        result = backend.execute("find . -type f -delete")

        if result.exit_code != 0:
            logger.error(f"Failed to clear files: user={current_user.id}, error={result.output}, ip={client_ip}")
            raise HTTPException(status_code=500, detail="Failed to clear files, please try again later")

        logger.info(f"All files cleared: user={current_user.id}, deleted_count={file_count}, ip={client_ip}")

        return BaseResponse(
            success=True,
            code=200,
            msg="Cleared files successfully",
            data={
                "message": f"Cleared working directory, deleted {file_count} files",
                "deleted_count": file_count,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear files: user={current_user.id}, ip={client_ip}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear files, please try again later") from e
