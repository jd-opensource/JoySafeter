"""Workspace API."""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user, require_workspace_role
from app.common.exceptions import BadRequestException, ForbiddenException
from app.common.pagination import PaginationParams
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.services.user_service import UserService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/v1/workspaces", tags=["Workspaces"])


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    type: Optional[str] = Field(default="team", description="Workspace type: personal or team")


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    settings: Optional[dict] = None


class DeleteWorkspaceRequest(BaseModel):
    deleteTemplates: bool = Field(default=True, description="Whether to also delete template data")


class AddMemberRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="member", description="Member role: admin/member/viewer")


class RemoveMemberRequest(BaseModel):
    workspaceId: uuid.UUID


class UpdateMemberRoleRequest(BaseModel):
    workspaceId: uuid.UUID
    role: str = Field(..., description="Member role: owner/admin/member/viewer")


@router.get("")
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all workspaces for the current user."""
    service = WorkspaceService(db)
    data = await service.list_workspaces(current_user)
    return {"workspaces": data}


@router.post("")
async def create_workspace(
    payload: CreateWorkspaceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new workspace (defaults to team workspace)."""
    from app.models.workspace import WorkspaceType

    workspace_type = WorkspaceType.team
    if payload.type:
        try:
            workspace_type = WorkspaceType(payload.type)
        except ValueError:
            raise BadRequestException(f"Invalid workspace type: {payload.type}. Must be 'personal' or 'team'")

    service = WorkspaceService(db)
    workspace = await service.create_workspace(
        name=payload.name,
        description=payload.description,
        current_user=current_user,
        workspace_type=workspace_type,
    )
    return {"workspace": workspace}


# ------------------------------------------------------------------ #
# Dynamic /{workspace_id} routes
# ------------------------------------------------------------------ #


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
):
    """Get a single workspace's details."""
    service = WorkspaceService(db)
    workspace = await service.get_workspace(workspace_id, current_user)
    return {"workspace": workspace}


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: uuid.UUID,
    payload: UpdateWorkspaceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    """Update workspace metadata."""
    service = WorkspaceService(db)
    workspace = await service.update_workspace(
        workspace_id,
        name=payload.name,
        description=payload.description,
        settings=payload.settings,
        current_user=current_user,
    )
    return {"workspace": workspace}


@router.put("/{workspace_id}")
async def update_workspace_put(
    workspace_id: uuid.UUID,
    payload: UpdateWorkspaceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    """Legacy compatibility: PUT alias."""
    return await update_workspace(workspace_id, payload, db, current_user)


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: uuid.UUID,
    payload: DeleteWorkspaceRequest = Body(default_factory=DeleteWorkspaceRequest),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.owner),
):
    """Delete a workspace and all related data."""
    service = WorkspaceService(db)
    await service.delete_workspace(
        workspace_id,
        delete_templates=payload.deleteTemplates,
        current_user=current_user,
    )
    return {"success": True}


@router.post("/{workspace_id}/duplicate")
async def duplicate_workspace(
    workspace_id: uuid.UUID,
    payload: dict = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
):
    """Duplicate a workspace."""
    service = WorkspaceService(db)
    workspace = await service.duplicate_workspace(
        workspace_id,
        name=payload.get("name"),
        current_user=current_user,
    )
    return {"workspace": workspace}


@router.post("/{workspace_id}/members")
async def add_member(
    workspace_id: uuid.UUID,
    payload: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    """Add a member to the workspace directly."""
    service = WorkspaceService(db)
    member = await service.add_member(
        workspace_id=workspace_id,
        email=payload.email,
        role=payload.role,
        current_user=current_user,
    )
    return {"member": member}


@router.get("/{workspace_id}/members")
async def list_members(
    workspace_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
):
    """List workspace members (paginated)."""
    service = WorkspaceService(db)
    result = await service.list_members_paginated(workspace_id, current_user, pagination)
    return result


@router.get("/{workspace_id}/my-permission")
async def get_my_permission(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the current user's permission in the workspace (lightweight, returns only the current user's permission).

    Returns:
        {
            "role": "owner" | "admin" | "member" | "viewer",
            "permissionType": "read" | "write" | "admin",
            "isOwner": boolean
        }
    """
    from app.common.response import success_response

    service = WorkspaceService(db)
    role = await service.get_user_role(workspace_id, current_user)

    if not role:
        raise ForbiddenException("No access to workspace")

    # reuse the frontend's role-to-permission mapping for consistency
    role_to_permission = {
        WorkspaceMemberRole.owner: "admin",
        WorkspaceMemberRole.admin: "admin",
        WorkspaceMemberRole.member: "write",
        WorkspaceMemberRole.viewer: "read",
    }

    workspace = await service.workspace_repo.get(workspace_id)
    is_owner = workspace.owner_id == current_user.id if workspace else False

    # reuse the existing success_response helper for consistent response format
    return success_response(
        data={
            "role": role.value,
            "permissionType": role_to_permission.get(role, "read"),
            "isOwner": is_owner,
        },
        message="Permission retrieved successfully",
    )


@router.get("/{workspace_id}/search-users")
async def search_users_for_invitation(
    workspace_id: uuid.UUID,
    keyword: str = Query(..., min_length=1, description="Search keyword (email or name)"),
    limit: int = Query(10, ge=1, le=20, description="Result limit"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    """Search users (for adding members, requires admin permission)."""
    user_service = UserService(db)
    users = await user_service.search_users(keyword, limit)

    # serialize user info
    result = []
    for user in users:
        result.append(
            {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "image": user.image,
            }
        )

    return {"users": result}


# ------------------------------------------------------------------ #
# Member management routes (/members/* won't be shadowed by /{workspace_id})
# ------------------------------------------------------------------ #


@router.patch("/members/{user_id}")
async def update_member_role(
    user_id: uuid.UUID,
    payload: UpdateMemberRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a workspace member's role (admin only)."""
    from app.services.workspace_permission import check_workspace_access

    has_access = await check_workspace_access(
        db,
        payload.workspaceId,
        current_user,
        WorkspaceMemberRole.admin,
    )
    if not has_access:
        raise ForbiddenException("Insufficient workspace permission")

    try:
        new_role = WorkspaceMemberRole(payload.role)
    except ValueError:
        raise BadRequestException(f"Invalid role: {payload.role}")

    service = WorkspaceService(db)
    member = await service.update_member_role(
        workspace_id=payload.workspaceId,
        target_user_id=str(user_id),
        new_role=new_role,
        current_user=current_user,
    )
    return {"member": member}


@router.delete("/members/{user_id}")
async def remove_member(
    user_id: uuid.UUID,
    payload: RemoveMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a workspace member (admin can remove others, members can remove themselves)."""
    # Allow self-removal without admin check; otherwise require admin role
    if str(user_id) != str(current_user.id):
        from app.services.workspace_permission import check_workspace_access

        has_access = await check_workspace_access(
            db,
            payload.workspaceId,
            current_user,
            WorkspaceMemberRole.admin,
        )
        if not has_access:
            raise ForbiddenException("Insufficient workspace permission")

    service = WorkspaceService(db)
    await service.remove_member(
        workspace_id=payload.workspaceId,
        target_user_id=user_id,
        current_user=current_user,
    )
    return {"success": True}
