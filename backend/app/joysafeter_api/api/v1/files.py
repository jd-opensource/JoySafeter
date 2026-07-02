"""Files API v2 routes — upload, list, get, download, delete."""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.services import FileService
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_file import FileDeleteResponse, FileResponse
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-files"])


def _get_service() -> FileService:
    return FileService(get_storage())


def _parse_file_id(raw: str) -> uuid.UUID:
    s = raw.removeprefix("file_")
    try:
        return uuid.UUID(s)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file_id")


def _parse_session_scope(scope_id: str | None) -> uuid.UUID | None:
    if not scope_id:
        return None
    # Accept both "sesn_" (official Managed Agents prefix) and "sess_"
    # (the prefix this API emits in SessionResponse). Either round-trips.
    s = scope_id
    for prefix in ("sesn_", "sess_"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    try:
        return uuid.UUID(s)
    except ValueError:
        return None


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
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("File upload failed")
        raise HTTPException(status_code=500, detail="File upload failed")

    return FileResponse.from_model(record)


@router.get("")
async def list_files(
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    after_id: Optional[str] = Query(default=None),
    scope_id: Optional[str] = Query(default=None, description="Filter by session id (sess_xxx or sesn_xxx)"),
) -> CursorPaginatedResponse[FileResponse]:
    svc = _get_service()
    cursor = _parse_file_id(after_id) if after_id else None
    session_filter = _parse_session_scope(scope_id)

    files, has_more = await svc.list_files(
        db=db,
        project_id=auth_ctx.project_id,
        limit=limit,
        after_id=cursor,
        session_id=session_filter,
    )

    data = [FileResponse.from_model(f) for f in files]
    return CursorPaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.get("/{file_id}")
async def get_file(
    file_id: str,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    svc = _get_service()
    uid = _parse_file_id(file_id)
    record = await svc.get_metadata(db, uid, auth_ctx.project_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse.from_model(record)


@router.get("/{file_id}/content")
async def download_file(
    file_id: str,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
):
    svc = _get_service()
    uid = _parse_file_id(file_id)

    presign_url, record = await svc.get_presign_url(db, uid, auth_ctx.project_id)
    if presign_url:
        return RedirectResponse(url=presign_url, status_code=302)

    try:
        data, record = await svc.download(db, uid, auth_ctx.project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    return Response(
        content=data,
        media_type=record.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{record.filename}"',
        },
    )


@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> FileDeleteResponse:
    svc = _get_service()
    uid = _parse_file_id(file_id)
    deleted = await svc.delete(db, uid, auth_ctx.project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    return FileDeleteResponse(id=file_id)
