"""
工作空间文件管理 API（版本化路径 /api/v1/workspaces）
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
    # 兼容前端直接读取 files，同时保留统一响应格式
    base = success_response(data={"files": files}, message="Fetched workspace files")
    return {**base, "files": files}


@router.post("/{workspace_id}/files")
async def upload_workspace_file(
    workspace_id: uuid.UUID,
    file: UploadFile = File(..., description="待上传文件"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
):
    # 兼容旧前端：重复文件返回 409 + isDuplicate，并使用 error 字段
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
        # 保持与旧前端一致的 error 字段，同时不破坏现有统一响应（仍返回 success=false）
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
    # 兼容旧前端：允许只判断 success
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

    # 生成绝对 downloadUrl（对齐旧项目 getBaseUrl() 的效果）
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
    token: Optional[str] = Query(default=None, description="下载签名 token"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    service = WorkspaceFileService(db)
    await service.validate_token_or_user(workspace_id, file_id, token, current_user)
    record = await service.get_file_record(workspace_id, file_id)
    file_path = service.get_file_path(record)

    if not file_path.exists():
        # 延迟校验，若文件缺失抛出一致错误
        await service.read_file_bytes(record)

    # 直接使用 FileResponse 减少内存占用
    return FileResponse(
        path=file_path,
        media_type=record.content_type or "application/octet-stream",
        filename=record.original_name,
    )
