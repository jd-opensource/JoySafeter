"""Files API v2 routes — upload, list, get, download, delete."""

import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.schemas.base import CursorPaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_file import FileDeleteResponse, FileResponse
from app.joysafeter_domain.services.joysafeter_file_service import FileService
from app.joysafeter_shared.common.app_errors import AppError, InternalServiceError, InvalidRequestError, NotFoundError
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import FileId, SessionId
from app.joysafeter_shared.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-files"])


def _get_service() -> FileService:
    return FileService(get_storage())


def _file_not_found_error(file_id: FileId) -> AppError:
    return NotFoundError(
        code="FILE_NOT_FOUND",
        message="File not found",
        data={"file_id": str(file_id)},
        user_action="refresh",
    )


def _parse_session_scope(scope_id: str | None) -> SessionId | None:
    if not scope_id:
        return None
    try:
        return SessionId.from_public(scope_id)
    except ValueError:
        raise InvalidRequestError(
            code="SESSION_ID_INVALID",
            message="Invalid session_id",
            data={"session_id": scope_id},
            user_action="fix_input",
        )


def _file_upload_validation_error(*, exc: ValueError, filename: str) -> AppError:
    message = str(exc)
    data: dict[str, object] = {"filename": filename}
    code = "FILE_UPLOAD_INVALID"
    if message == "File cannot be empty":
        code = "FILE_EMPTY"
    elif message.startswith("File size exceeds maximum"):
        code = "FILE_TOO_LARGE"
    elif message.startswith("File type ") and message.endswith(" is not supported"):
        code = "FILE_TYPE_UNSUPPORTED"
        data["extension"] = message.removeprefix("File type ").removesuffix(" is not supported")
    return InvalidRequestError(
        code=code,
        message=message,
        data=data,
        user_action="fix_input",
    )


def _safe_content_disposition(filename: str) -> str:
    """Build a header-injection-safe Content-Disposition for a user filename.

    Emits a sanitized ASCII ``filename="..."`` fallback (control chars, quotes
    and backslashes removed) plus an RFC 5987 ``filename*=UTF-8''`` with the real
    name percent-encoded. The result is always well-formed and latin-1 encodable,
    so a filename containing a quote/CRLF cannot break out of the header and a
    non-ASCII name cannot trigger a header-encoding 500.
    """
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii")
    for ch in ('"', "\\", "\r", "\n"):
        ascii_fallback = ascii_fallback.replace(ch, "")
    ascii_fallback = ascii_fallback.strip() or "download"
    utf8_encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_encoded}"


@router.post("", status_code=201)
async def upload_file(
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="File to upload"),
) -> FileResponse:
    svc = _get_service()
    data = await file.read()
    filename = file.filename or "unnamed"

    try:
        record = await svc.upload(
            db=db,
            project_id=auth_ctx.project_id,
            filename=filename,
            data=data,
            content_type=file.content_type,
        )
    except ValueError as e:
        raise _file_upload_validation_error(exc=e, filename=filename) from e
    except Exception as exc:
        log_boundary_failure(
            logger,
            boundary="file_api",
            code="FILE_UPLOAD_FAILED",
            message="File upload failed",
            operation="upload_file",
            error=exc,
            data={"filename": filename, "content_type": file.content_type or ""},
        )
        raise InternalServiceError(
            code="FILE_UPLOAD_FAILED",
            message="File upload failed",
            data={"filename": filename},
            retryable=True,
            user_action="retry",
        ) from None

    return FileResponse.from_model(record)


@router.get("")
async def list_files(
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    after_id: Optional[FileId] = Query(default=None),
    scope_id: Optional[str] = Query(default=None, description="Filter by session id (sess_xxx)"),
) -> CursorPaginatedResponse[FileResponse]:
    svc = _get_service()
    session_filter = _parse_session_scope(scope_id)

    files, has_more = await svc.list_files(
        db=db,
        project_id=auth_ctx.project_id,
        limit=limit,
        after_id=after_id,
        session_id=session_filter,
    )

    data = [FileResponse.from_model(f) for f in files]
    return CursorPaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{file_id}")
async def get_file(
    file_id: FileId,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    svc = _get_service()
    record = await svc.get_metadata(db, file_id, auth_ctx.project_id)
    if not record:
        raise _file_not_found_error(file_id)
    return FileResponse.from_model(record)


@router.get("/{file_id}/content")
async def download_file(
    file_id: FileId,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
):
    svc = _get_service()
    try:
        presign_url, record = await svc.get_presign_url(db, file_id, auth_ctx.project_id)
        if presign_url:
            return RedirectResponse(url=presign_url, status_code=302)
        data, record = await svc.download(db, file_id, auth_ctx.project_id)
    except FileNotFoundError:
        raise _file_not_found_error(file_id)

    return Response(
        content=data,
        media_type=record.content_type,
        headers={
            "Content-Disposition": _safe_content_disposition(record.filename),
        },
    )


@router.delete("/{file_id}")
async def delete_file(
    file_id: FileId,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> FileDeleteResponse:
    svc = _get_service()
    deleted = await svc.delete(db, file_id, auth_ctx.project_id)
    if not deleted:
        raise _file_not_found_error(file_id)
    return FileDeleteResponse(id=file_id)
