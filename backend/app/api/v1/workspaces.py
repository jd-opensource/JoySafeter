"""工作空间相关 API"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user, require_workspace_role
from app.common.pagination import PaginationParams
from app.core.database import get_db
from app.models.access_control import PermissionType
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.services.user_service import UserService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/v1/workspaces", tags=["Workspaces"])


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    type: Optional[str] = Field(default="team", description="工作空间类型: personal 或 team")


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    allowPersonalApiKeys: Optional[bool] = None
    settings: Optional[dict] = None


class DeleteWorkspaceRequest(BaseModel):
    deleteTemplates: bool = Field(default=True, description="是否同时删除模板数据")


class InvitationRequest(BaseModel):
    workspaceId: uuid.UUID
    email: EmailStr
    role: str = Field(default="member", description="owner/admin/member/viewer")
    permission: PermissionType = Field(default=PermissionType.write)


class RemoveMemberRequest(BaseModel):
    workspaceId: uuid.UUID


@router.get("")
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有 workspace"""
    service = WorkspaceService(db)
    data = await service.list_workspaces(current_user)
    return {"workspaces": data}


@router.post("")
async def create_workspace(
    payload: CreateWorkspaceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新 workspace（默认创建团队工作空间）"""
    from app.models.workspace import WorkspaceType

    workspace_type = WorkspaceType.team
    if payload.type:
        try:
            workspace_type = WorkspaceType(payload.type)
        except ValueError:
            from app.common.exceptions import BadRequestException

            raise BadRequestException(f"Invalid workspace type: {payload.type}. Must be 'personal' or 'team'")

    service = WorkspaceService(db)
    workspace = await service.create_workspace(
        name=payload.name,
        description=payload.description,
        current_user=current_user,
        workspace_type=workspace_type,
    )
    return {"workspace": workspace}


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
):
    """获取单个 workspace 详情"""
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
    """更新 workspace 元数据"""
    service = WorkspaceService(db)
    workspace = await service.update_workspace(
        workspace_id,
        name=payload.name,
        description=payload.description,
        allow_personal_api_keys=payload.allowPersonalApiKeys,
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
    """对齐旧项目：PUT 别名"""
    return await update_workspace(workspace_id, payload, db, current_user)


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: uuid.UUID,
    payload: DeleteWorkspaceRequest = Body(default_factory=DeleteWorkspaceRequest),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    """删除 workspace 及其所有相关数据"""
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
    current_user: User = Depends(get_current_user),
):
    """复制工作空间"""
    service = WorkspaceService(db)
    workspace = await service.duplicate_workspace(
        workspace_id,
        name=payload.get("name"),
        current_user=current_user,
    )
    return {"workspace": workspace}


@router.get("/invitations")
async def list_invitations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户有权限查看的所有 workspace 邀请（管理员视角）"""
    service = WorkspaceService(db)
    invitations = await service.list_invitations(current_user)
    return {"invitations": invitations}


@router.get("/invitations/pending")
async def list_pending_invitations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户待处理的工作空间邀请（被邀请人视角）"""
    service = WorkspaceService(db)
    invitations = await service.list_pending_invitations_for_user(current_user)
    return {"invitations": invitations}


@router.get("/invitations/all")
async def list_all_invitations(
    pagination: PaginationParams = Depends(),
    status: Optional[str] = Query(None, description="筛选状态: pending, processed, accepted, rejected"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户所有的工作空间邀请（支持分页和状态筛选）"""
    service = WorkspaceService(db)
    result = await service.list_all_invitations_for_user_paginated(current_user, pagination, status=status)
    return result


@router.post("/invitations")
async def create_invitation(
    payload: InvitationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 workspace 邀请"""
    service = WorkspaceService(db)
    invitation = await service.create_invitation(
        workspace_id=payload.workspaceId,
        email=payload.email,
        role=payload.role,
        permission=payload.permission,
        current_user=current_user,
    )
    return {"success": True, "invitation": invitation}


@router.get("/invitations/{token}")
async def get_invitation_by_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """根据 token 获取邀请信息（无需认证）"""
    service = WorkspaceService(db)
    invitation = await service.get_invitation_by_token(token)
    return {"success": True, "invitation": invitation}


@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation(
    invitation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """接受工作空间邀请（通过邀请ID）"""
    service = WorkspaceService(db)
    result = await service.accept_invitation(invitation_id, current_user)
    return result


@router.post("/invitations/{invitation_id}/reject")
async def reject_invitation(
    invitation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """拒绝工作空间邀请"""
    service = WorkspaceService(db)
    result = await service.reject_invitation(invitation_id, current_user)
    return result


@router.post("/invitations/token/{token}/accept")
async def accept_invitation_by_token(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """接受工作空间邀请（通过token，用于邮件链接）"""
    service = WorkspaceService(db)
    result = await service.accept_invitation_by_token(token, current_user)
    return result


@router.get("/{workspace_id}/members")
async def list_members(
    workspace_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
):
    """获取工作空间成员列表（支持分页）"""
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
    获取当前用户在工作空间中的权限（轻量级，只返回当前用户权限）

    Returns:
        {
            "role": "owner" | "admin" | "member" | "viewer",
            "permissionType": "read" | "write" | "admin",
            "isOwner": boolean
        }
    """
    from app.common.exceptions import ForbiddenException
    from app.common.response import success_response

    service = WorkspaceService(db)
    role = await service.get_user_role(workspace_id, current_user)

    if not role:
        raise ForbiddenException("No access to workspace")

    # 复用前端的映射逻辑（保持一致）
    role_to_permission = {
        WorkspaceMemberRole.owner: "admin",
        WorkspaceMemberRole.admin: "admin",
        WorkspaceMemberRole.member: "write",
        WorkspaceMemberRole.viewer: "read",
    }

    workspace = await service.workspace_repo.get(workspace_id)
    is_owner = workspace.owner_id == current_user.id if workspace else False

    # 复用现有的 success_response 函数保持响应格式一致
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
    keyword: str = Query(..., min_length=1, description="搜索关键词（邮箱或姓名）"),
    limit: int = Query(10, ge=1, le=20, description="返回数量限制"),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    """搜索用户（用于邀请成员，需要管理员权限）"""
    user_service = UserService(db)
    users = await user_service.search_users(keyword, limit)

    # 序列化用户信息
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


class UpdateMemberRoleRequest(BaseModel):
    workspaceId: uuid.UUID
    role: str = Field(..., description="成员角色: owner/admin/member/viewer")


@router.patch("/members/{user_id}")
async def update_member_role(
    user_id: uuid.UUID,
    payload: UpdateMemberRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新工作空间成员角色（仅 admin 可操作）"""
    from app.models.workspace import WorkspaceMemberRole

    try:
        new_role = WorkspaceMemberRole(payload.role)
    except ValueError:
        from app.common.exceptions import BadRequestException

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
    """移除 workspace 成员（admin 可移除他人，成员可移除自己）"""
    service = WorkspaceService(db)
    await service.remove_member(
        workspace_id=payload.workspaceId,
        target_user_id=user_id,
        current_user=current_user,
    )
    return {"success": True}
