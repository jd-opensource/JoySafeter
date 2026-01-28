"""
环境变量管理 API（路径 /api/v1/environment）

- /api/v1/environment/user                 获取当前用户环境变量（仅返回键名，值被掩码）
- /api/v1/environment/user (PUT)           更新当前用户环境变量
- /api/v1/environment/workspaces/{id}      获取工作空间环境变量（需 admin 及以上，掩码）
- /api/v1/environment/workspaces/{id} (PUT)更新工作空间环境变量（需 admin 及以上）
"""

from __future__ import annotations

import uuid
from typing import Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user, require_workspace_role
from app.common.exceptions import ForbiddenException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.repositories.workspace import WorkspaceMemberRepository
from app.services.environment_service import EnvironmentService

router = APIRouter(prefix="/v1/environment", tags=["Environment"])


class EnvPayload(BaseModel):
    variables: Dict[str, str] = Field(default_factory=dict)


async def _ensure_workspace_role(db: AsyncSession, workspace_id: uuid.UUID, user: User, min_role: WorkspaceMemberRole):
    repo = WorkspaceMemberRepository(db)
    member = await repo.get_member(workspace_id, user.id)
    if not member:
        raise ForbiddenException("No access to workspace environment")
    role_order = [
        WorkspaceMemberRole.viewer,
        WorkspaceMemberRole.member,
        WorkspaceMemberRole.admin,
        WorkspaceMemberRole.owner,
    ]
    if role_order.index(member.role) < role_order.index(min_role):
        raise ForbiddenException("Insufficient permission for workspace environment")


@router.get("/user")
async def get_user_environment(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EnvironmentService(db)
    # Note: EnvironmentService expects uuid.UUID but user.id and Environment.user_id are both strings.
    # Converting str to UUID for compatibility with service signature
    import uuid as uuid_lib

    user_id = uuid_lib.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id
    variables = await service.get_user_env(user_id)
    return {"success": True, "variables": service.mask_variables(variables)}


@router.put("/user")
async def update_user_environment(
    payload: EnvPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EnvironmentService(db)
    # Note: EnvironmentService expects uuid.UUID but user.id and Environment.user_id are both strings.
    # Converting str to UUID for compatibility with service signature
    import uuid as uuid_lib

    user_id = uuid_lib.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id
    variables = await service.upsert_user_env(user_id, payload.variables)
    return {"success": True, "variables": service.mask_variables(variables)}


@router.get("/workspaces/{workspace_id}")
async def get_workspace_environment(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    service = EnvironmentService(db)
    variables = await service.get_workspace_env(workspace_id)
    return {"success": True, "variables": service.mask_variables(variables)}


@router.put("/workspaces/{workspace_id}")
async def update_workspace_environment(
    workspace_id: uuid.UUID,
    payload: EnvPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_workspace_role(WorkspaceMemberRole.admin),
):
    service = EnvironmentService(db)
    variables = await service.upsert_workspace_env(workspace_id, payload.variables)
    return {"success": True, "variables": service.mask_variables(variables)}
