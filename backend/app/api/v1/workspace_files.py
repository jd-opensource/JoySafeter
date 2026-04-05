"""
Workspace file management API (versioned path: /api/v1/workspaces)
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user_optional, require_workspace_role
from app.common.exceptions import AppException, ConflictException
from app.common.response import success_response
from app.core.database import get_db
from app.core.settings import settings
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.services.workspace_file_service import WorkspaceFileService

router = APIRouter(prefix="/v1/workspaces", tags=["WorkspaceFiles"])


@router.get("/{workspace_id}/files")
async def list_workspace_files(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
):
    service = WorkspaceFileService(db)
    files = await service.list_files(workspace_id, current_user)
    # compatible with frontend reading files directly, while preserving unified response format
    base = success_response(data={"files": files}, message="Fetched workspace files")
    return {**base, "files": files}


@router.post("/{workspace_id}/files")
async def upload_workspace_file(
    workspace_id: uuid.UUID,
    file: UploadFile = File(..., description="File to upload"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
):
    # Duplicate file returns 409 + isDuplicate with error field for frontend
    try:
        service = WorkspaceFileService(db)
        record = await service.upload_file(workspace_id, file, current_user)
        base = success_response(data={"file": record}, message="File uploaded")
        return {**base, "file": record}
    except ConflictException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": str(exc.detail),
                "isDuplicate": True,
            },
        )
    except AppException as exc:
        # Return error field alongside unified response (success=false) for frontend compatibility
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": str(exc.detail),
            },
        )


@router.delete("/{workspace_id}/files/{file_id}")
async def delete_workspace_file(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
):
    service = WorkspaceFileService(db)
    await service.delete_file(workspace_id, file_id, current_user)
    # Include top-level success field for frontend compatibility
    base = success_response(message="File deleted", data={"fileId": str(file_id)})
    return {**base, "success": True}


@router.post("/{workspace_id}/files/{file_id}/download")
async def generate_workspace_file_download_url(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
):
    service = WorkspaceFileService(db)
    url = await service.generate_download_url(workspace_id, file_id, current_user)
    record = await service.get_file_record(workspace_id, file_id)

    # Generate absolute downloadUrl from the request base URL
    base_url = str(request.base_url).rstrip("/")
    download_url = f"{base_url}{url}"
    viewer_url = f"{settings.frontend_url.rstrip('/')}/workspace/{workspace_id}/files/{file_id}/view"

    payload = {
        "downloadUrl": download_url,
        "viewerUrl": viewer_url,
        "fileName": record.original_name,
        "expiresIn": None,
    }

    base = success_response(data=payload, message="Download URL generated")
    return {**base, "success": True, **payload}


@router.get("/{workspace_id}/files/{file_id}/serve")
async def serve_workspace_file(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    token: Optional[str] = Query(default=None, description="Download signature token"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    service = WorkspaceFileService(db)
    await service.validate_token_or_user(workspace_id, file_id, token, current_user)
    record = await service.get_file_record(workspace_id, file_id)
    file_path = service.get_file_path(record)

    if not file_path.exists():
        # deferred validation: raise a consistent error if the file is missing
        await service.read_file_bytes(record)

    # use FileResponse directly to reduce memory usage
    return FileResponse(
        path=file_path,
        media_type=record.content_type or "application/octet-stream",
        filename=record.original_name,
    )
