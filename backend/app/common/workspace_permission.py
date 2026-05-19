"""
Workspace permission check utilities.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthUser
from app.models.workspace import WorkspaceMemberRole
from app.repositories.workspace import WorkspaceMemberRepository, WorkspaceRepository

# role privilege hierarchy (low to high)
ROLE_HIERARCHY = [
    WorkspaceMemberRole.viewer,
    WorkspaceMemberRole.member,
    WorkspaceMemberRole.admin,
    WorkspaceMemberRole.owner,
]


def has_sufficient_role(user_role: WorkspaceMemberRole, required_role: WorkspaceMemberRole) -> bool:
    """
    Check whether the user's role meets the required role.

    Args:
        user_role: the user's role
        required_role: the required role

    Returns:
        True if the user's role level >= the required role level
    """
    return ROLE_HIERARCHY.index(user_role) >= ROLE_HIERARCHY.index(required_role)


async def check_workspace_access(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    current_user: AuthUser,
    required_role: WorkspaceMemberRole,
) -> bool:
    """
    Check whether the user has access to the workspace.

    Args:
        db: database session
        workspace_id: workspace ID
        current_user: current user
        required_role: minimum required role

    Returns:
        True if authorized, False otherwise
    """
    # superuser has all permissions
    if current_user.is_superuser:
        return True

    workspace_repo = WorkspaceRepository(db)
    workspace = await workspace_repo.get(workspace_id)
    if not workspace:
        return False

    # workspace owner has all permissions
    if workspace.owner_id == current_user.id:
        return True

    # check member role
    member_repo = WorkspaceMemberRepository(db)
    member = await member_repo.get_member(workspace_id, current_user.id)
    if not member:
        return False

    return has_sufficient_role(member.role, required_role)
