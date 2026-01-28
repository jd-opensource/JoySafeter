"""
工作空间权限检查工具函数
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthUser
from app.models.workspace import WorkspaceMemberRole
from app.repositories.workspace import WorkspaceMemberRepository, WorkspaceRepository

# 角色权限等级（从低到高）
ROLE_HIERARCHY = [
    WorkspaceMemberRole.viewer,
    WorkspaceMemberRole.member,
    WorkspaceMemberRole.admin,
    WorkspaceMemberRole.owner,
]


def has_sufficient_role(user_role: WorkspaceMemberRole, required_role: WorkspaceMemberRole) -> bool:
    """
    检查用户角色是否满足所需角色要求

    Args:
        user_role: 用户的角色
        required_role: 所需的角色

    Returns:
        如果用户角色等级 >= 所需角色等级，返回 True
    """
    return ROLE_HIERARCHY.index(user_role) >= ROLE_HIERARCHY.index(required_role)


async def check_workspace_access(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    current_user: AuthUser,
    required_role: WorkspaceMemberRole,
) -> bool:
    """
    检查用户是否有工作空间的访问权限

    Args:
        db: 数据库会话
        workspace_id: 工作空间ID
        current_user: 当前用户
        required_role: 所需的最低角色

    Returns:
        如果有权限返回 True，否则返回 False
    """
    # 超级用户有所有权限
    if current_user.is_superuser:
        return True

    workspace_repo = WorkspaceRepository(db)
    workspace = await workspace_repo.get(workspace_id)
    if not workspace:
        return False

    # 工作空间所有者有所有权限
    if workspace.owner_id == current_user.id:
        return True

    # 检查成员角色
    member_repo = WorkspaceMemberRepository(db)
    member = await member_repo.get_member(workspace_id, current_user.id)
    if not member:
        return False

    return has_sufficient_role(member.role, required_role)
