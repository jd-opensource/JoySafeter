"""Folders API (versioned path: /api/v1/folders)"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.repositories.workspace_folder import WorkflowFolderRepository
from app.services.workspace_folder_service import FolderService

router = APIRouter(prefix="/v1/folders", tags=["Folders"])


class CreateFolderRequest(BaseModel):
    workspaceId: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    parentId: Optional[uuid.UUID] = None
    color: Optional[str] = Field(default=None, max_length=32)


class UpdateFolderRequest(BaseModel):
    workspaceId: Optional[uuid.UUID] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    color: Optional[str] = Field(None, max_length=32)
    isExpanded: Optional[bool] = None
    parentId: Optional[uuid.UUID] = None


class DuplicateFolderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    workspaceId: Optional[uuid.UUID] = None
    parentId: Optional[uuid.UUID] = None
    color: Optional[str] = Field(default=None, max_length=32)


def _serialize_folder(folder) -> dict:
    return {
        "id": str(folder.id),
        "name": folder.name,
        "workspaceId": str(folder.workspace_id),
        "parentId": str(folder.parent_id) if folder.parent_id else None,
        "color": folder.color,
        "isExpanded": folder.is_expanded,
        "sortOrder": folder.sort_order,
        "createdAt": folder.created_at,
        "updatedAt": folder.updated_at,
        "userId": str(folder.user_id),
    }


@router.get("")
async def list_folders(
    workspace_id: uuid.UUID = Query(..., alias="workspaceId"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = FolderService(db)
    folders = await service.list_folders(workspace_id, current_user=current_user)
    payload = [_serialize_folder(f) for f in folders]
    base = success_response(data={"folders": payload}, message="Fetched folders")
    return {**base, "folders": payload}


@router.post("")
async def create_folder(
    body: CreateFolderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = FolderService(db)
    folder = await service.create_folder(
        workspace_id=body.workspaceId,
        current_user=current_user,
        name=body.name,
        parent_id=body.parentId,
        color=body.color,
        is_expanded=False,
    )
    payload = _serialize_folder(folder)
    base = success_response(data={"folder": payload}, message="Folder created")
    return {**base, "folder": payload}


@router.put("/{folder_id}")
async def update_folder(
    folder_id: uuid.UUID,
    body: UpdateFolderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = WorkflowFolderRepository(db)
    existing = await repo.get(folder_id)
    if not existing:
        from app.common.exceptions import NotFoundException

        raise NotFoundException("Folder not found")

    workspace_id = body.workspaceId or existing.workspace_id
    service = FolderService(db)
    folder = await service.update_folder(
        folder_id,
        workspace_id=workspace_id,
        current_user=current_user,
        name=body.name,
        color=body.color,
        is_expanded=body.isExpanded,
        parent_id=body.parentId,
    )
    payload = _serialize_folder(folder)
    base = success_response(data={"folder": payload}, message="Folder updated")
    return {**base, "folder": payload}


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = WorkflowFolderRepository(db)
    existing = await repo.get(folder_id)
    if not existing:
        from app.common.exceptions import NotFoundException

        raise NotFoundException("Folder not found")

    service = FolderService(db)
    stats = await service.delete_folder_tree(
        folder_id,
        workspace_id=existing.workspace_id,
        current_user=current_user,
    )
    base = success_response(data={"deletedItems": stats}, message="Folder deleted")
    return {**base, "success": True, "deletedItems": stats}


@router.post("/{folder_id}/duplicate")
async def duplicate_folder(
    folder_id: uuid.UUID,
    body: DuplicateFolderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = WorkflowFolderRepository(db)
    source = await repo.get(folder_id)
    if not source:
        from app.common.exceptions import NotFoundException

        raise NotFoundException("Source folder not found")

    target_workspace_id = body.workspaceId or source.workspace_id

    service = FolderService(db)
    new_root = await service.duplicate_folder(
        folder_id,
        workspace_id=target_workspace_id,
        current_user=current_user,
        name=body.name,
        parent_id=body.parentId,
        color=body.color,
    )

    result = {
        "id": str(new_root.id),
        "name": new_root.name,
        "color": new_root.color,
        "workspaceId": str(new_root.workspace_id),
        "parentId": str(new_root.parent_id) if new_root.parent_id else None,
    }
    base = success_response(data=result, message="Folder duplicated", code=201)
    return {**base, **result}


@router.get("/{folder_id}/graphs")
async def list_folder_graphs(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all graphs in a folder. TODO: removed in greenfield rewrite — graphs table dropped."""
    from app.common.exceptions import NotFoundException

    repo = WorkflowFolderRepository(db)
    folder = await repo.get(folder_id)
    if not folder:
        raise NotFoundException("Folder not found")

    return {"graphs": []}
