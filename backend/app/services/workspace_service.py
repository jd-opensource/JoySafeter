"""Workspace service."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.common.pagination import PageResult, PaginationParams
from app.models.auth import AuthUser as User
from app.models.workspace import Workspace, WorkspaceMemberRole, WorkspaceType
from app.repositories.workspace import (
    WorkspaceMemberRepository,
    WorkspaceRepository,
)

from .base import BaseService

ROLE_RANK = {
    WorkspaceMemberRole.viewer: 0,
    WorkspaceMemberRole.member: 1,
    WorkspaceMemberRole.admin: 2,
    WorkspaceMemberRole.owner: 3,
}


class WorkspaceService(BaseService[Workspace]):
    """Workspace business logic."""

    def __init__(self, db):
        super().__init__(db)
        self.workspace_repo = WorkspaceRepository(db)
        self.member_repo = WorkspaceMemberRepository(db)

    async def _serialize_workspace(self, workspace: Workspace, current_user: User) -> Dict:
        """Serialize workspace, aligned with legacy project camelCase field naming."""
        role = await self._get_role(workspace, current_user)
        return {
            "id": str(workspace.id),
            "name": workspace.name,
            "description": workspace.description,
            "ownerId": str(workspace.owner_id),
            "status": workspace.status.value,
            "type": workspace.type.value if hasattr(workspace.type, "value") else workspace.type,
            "settings": workspace.settings or {},
            "createdAt": workspace.created_at,
            "updatedAt": workspace.updated_at,
            "role": role.value if isinstance(role, WorkspaceMemberRole) else role,
        }

    async def _get_role(self, workspace: Workspace, current_user: User) -> WorkspaceMemberRole | str | None:
        if current_user.is_superuser:
            return WorkspaceMemberRole.owner
        if workspace.owner_id == current_user.id:
            return WorkspaceMemberRole.owner
        member = await self.member_repo.get_member(workspace.id, current_user.id)
        return member.role if member else None

    async def _ensure_member(self, workspace_id: uuid.UUID, current_user: User) -> WorkspaceMemberRole:
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")
        if current_user.is_superuser or workspace.owner_id == current_user.id:
            return WorkspaceMemberRole.owner
        member = await self.member_repo.get_member(workspace_id, current_user.id)
        if not member:
            raise ForbiddenException("No access to workspace")
        return member.role  # type: ignore

    async def get_user_role(self, workspace_id: uuid.UUID, current_user: User) -> Optional[WorkspaceMemberRole]:
        """
        Get the user's role in a workspace (reuse _ensure_member logic, but do not raise).

        Returns:
            User role, or None if the user is not a member
        """
        try:
            # reuse the existing _ensure_member method, which already handles all cases (superuser, owner, regular member)
            return await self._ensure_member(workspace_id, current_user)
        except (NotFoundException, ForbiddenException):
            # if the user is not a member, return None instead of raising (this is a query method, not a validation method)
            return None

    def _ensure_admin_role(self, role: WorkspaceMemberRole):
        if role not in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
            raise ForbiddenException("Admin permission required")

    async def list_workspaces(self, current_user: User) -> List[Dict]:
        workspaces = await self.workspace_repo.list_for_user(current_user.id)
        return [await self._serialize_workspace(ws, current_user) for ws in workspaces]

    async def ensure_personal_workspace(self, current_user: User) -> Workspace:
        """Ensure the user has a personal workspace; create one if missing."""
        workspaces = await self.workspace_repo.list_for_user(current_user.id)
        personal_workspace = None
        for ws in workspaces:
            if ws.type == WorkspaceType.personal and ws.owner_id == current_user.id:
                personal_workspace = ws
                break

        if not personal_workspace:
            personal_workspace = await self._create_personal_workspace(current_user)
            await self.commit()

        return personal_workspace

    async def _create_personal_workspace(self, current_user: User) -> Workspace:
        """Create a personal workspace."""
        ws = await self.workspace_repo.create(
            {
                "name": "Personal Space",
                "description": "Personal Space",
                "owner_id": current_user.id,
                "type": WorkspaceType.personal,
            }
        )
        await self.member_repo.create(
            {"workspace_id": ws.id, "user_id": current_user.id, "role": WorkspaceMemberRole.owner}
        )
        return ws  # type: ignore

    async def create_workspace(
        self,
        *,
        name: str,
        description: Optional[str],
        current_user: User,
        workspace_type: WorkspaceType = WorkspaceType.team,
    ) -> Dict:
        """Create a workspace (default: team workspace)."""
        workspace = await self.workspace_repo.create(
            {
                "name": name,
                "description": description,
                "owner_id": current_user.id,
                "type": workspace_type,
            }
        )
        await self.member_repo.create(
            {"workspace_id": workspace.id, "user_id": current_user.id, "role": WorkspaceMemberRole.owner}
        )

        await self.commit()
        return await self._serialize_workspace(workspace, current_user)

    async def get_workspace(self, workspace_id: uuid.UUID, current_user: User) -> Dict:
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")
        await self._ensure_member(workspace_id, current_user)
        return await self._serialize_workspace(workspace, current_user)

    async def update_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        name: Optional[str],
        description: Optional[str],
        settings: Optional[dict],
        current_user: User,
    ) -> Dict:
        role = await self._ensure_member(workspace_id, current_user)
        self._ensure_admin_role(role)

        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        update_data: Dict[str, Any] = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if settings is not None:
            merged_settings = workspace.settings or {}
            merged_settings.update(settings)
            update_data["settings"] = merged_settings

        if update_data:
            updated_workspace = await self.workspace_repo.update(workspace_id, update_data)  # type: ignore
            await self.commit()
            # refresh after commit to ensure we get the latest data from the database
            await self.db.refresh(updated_workspace)
            workspace = updated_workspace
        else:
            # if no update data, re-fetch to ensure data is current
            workspace = await self.workspace_repo.get(workspace_id)

        # ensure the latest serialized data is returned
        return await self._serialize_workspace(workspace, current_user)

    async def delete_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        delete_templates: bool,
        current_user: User,
    ) -> bool:
        role = await self._ensure_member(workspace_id, current_user)
        self._ensure_admin_role(role)

        # check if it's a personal workspace; personal workspaces cannot be deleted
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        if workspace.type == WorkspaceType.personal:
            raise BadRequestException("Personal workspace cannot be deleted")

        # Revoke all tokens bound to this workspace
        from app.services.platform_token_service import PlatformTokenService

        token_service = PlatformTokenService(self.db)
        await token_service.revoke_by_resource("graph", str(workspace_id))

        deleted = await self.workspace_repo.delete(workspace_id)
        await self.commit()
        # template deletion logic reserved; no template entity mounted in current model
        return bool(deleted) if deleted is not None else False

    async def duplicate_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        name: Optional[str],
        current_user: User,
    ) -> Dict:
        """Duplicate a workspace."""
        # get source workspace
        source_workspace = await self.workspace_repo.get(workspace_id)
        if not source_workspace:
            raise NotFoundException("Workspace not found")

        # ensure user has permission to access the source workspace
        await self._ensure_member(workspace_id, current_user)

        # check if it's a personal workspace; personal workspaces cannot be duplicated
        if source_workspace.type == WorkspaceType.personal:
            raise BadRequestException("Personal workspace cannot be duplicated")

        # generate new name
        new_name = name or f"{source_workspace.name} (Copy)"

        # create new workspace
        new_workspace = await self.workspace_repo.create(
            {
                "name": new_name,
                "description": source_workspace.description,
                "owner_id": current_user.id,
                "type": WorkspaceType.team,  # duplicated workspaces are always team workspaces
                "settings": source_workspace.settings.copy() if source_workspace.settings else None,
            }
        )

        # add current user as owner of the new workspace
        await self.member_repo.create(
            {"workspace_id": new_workspace.id, "user_id": current_user.id, "role": WorkspaceMemberRole.owner}
        )

        await self.commit()
        return await self._serialize_workspace(new_workspace, current_user)

    # ------------------------------------------------------------------ #
    # add member directly
    # ------------------------------------------------------------------ #
    async def add_member(
        self,
        *,
        workspace_id: uuid.UUID,
        email: str,
        role: str,
        current_user: User,
    ) -> Dict:
        """Add a member to the workspace directly (no invitation flow)."""
        member_role = await self._ensure_member(workspace_id, current_user)
        self._ensure_admin_role(member_role)

        if role not in WorkspaceMemberRole._value2member_map_:
            raise BadRequestException("Invalid role")

        target_role = WorkspaceMemberRole(role)

        # owner role cannot be assigned via add member
        if target_role == WorkspaceMemberRole.owner:
            raise BadRequestException("Cannot assign owner role")

        # role hierarchy protection: non-owner cannot add a role >= their own
        if member_role != WorkspaceMemberRole.owner:
            if ROLE_RANK.get(target_role, 0) >= ROLE_RANK.get(member_role, 0):
                raise ForbiddenException("Cannot add a member with a role equal to or higher than your own")

        from app.repositories.auth_user import AuthUserRepository

        user_repo = AuthUserRepository(self.db)
        target_user = await user_repo.get_by_email(email.lower())

        if not target_user:
            raise NotFoundException("User not found")

        existing_member = await self.member_repo.get_member(workspace_id, target_user.id)
        if existing_member:
            raise BadRequestException(f"User with email {email} is already a member of this workspace")

        await self.member_repo.create({"workspace_id": workspace_id, "user_id": target_user.id, "role": target_role})
        await self.commit()

        return {
            "id": str(target_user.id),
            "userId": str(target_user.id),
            "workspaceId": str(workspace_id),
            "email": target_user.email,
            "name": target_user.name,
            "role": target_role.value,
            "isOwner": False,
        }

    # ------------------------------------------------------------------ #
    # member management
    # ------------------------------------------------------------------ #
    async def list_members_paginated(
        self,
        workspace_id: uuid.UUID,
        current_user: User,
        pagination: PaginationParams,
    ) -> PageResult:
        """Get workspace member list (paginated)."""
        from app.common.pagination import PageResult

        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        await self._ensure_member(workspace_id, current_user)

        members = await self.member_repo.list_by_workspace(workspace_id)

        owner_in_members = any(m.user_id == workspace.owner_id for m in members)
        if not owner_in_members:
            from app.repositories.auth_user import AuthUserRepository

            user_repo = AuthUserRepository(self.db)
            owner = await user_repo.get_by(id=workspace.owner_id)
            if owner:

                class OwnerMember:
                    def __init__(self):
                        self.user_id = owner.id
                        self.role = WorkspaceMemberRole.owner
                        self.user = owner
                        self.created_at = workspace.created_at
                        self.updated_at = workspace.updated_at

                owner_member = OwnerMember()
                members.insert(0, owner_member)

        result = []
        for member in members:
            user = member.user if hasattr(member, "user") and member.user else None
            if not user:
                continue

            result.append(
                {
                    "id": str(member.user_id),
                    "userId": str(member.user_id),
                    "workspaceId": str(workspace_id),
                    "email": user.email,
                    "name": user.name,
                    "role": member.role.value if hasattr(member.role, "value") else member.role,
                    "isOwner": workspace.owner_id == member.user_id,
                    "createdAt": member.created_at.isoformat()
                    if hasattr(member, "created_at") and member.created_at
                    else None,
                    "updatedAt": member.updated_at.isoformat()
                    if hasattr(member, "updated_at") and member.updated_at
                    else None,
                }
            )

        total = len(result)
        pages = (total + pagination.page_size - 1) // pagination.page_size if pagination.page_size > 0 else 0
        start = pagination.offset
        end = start + pagination.page_size
        paginated_items = result[start:end]

        return PageResult(
            items=paginated_items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pages,
        )

    async def update_member_role(
        self,
        workspace_id: uuid.UUID,
        target_user_id: str,
        new_role: WorkspaceMemberRole,
        current_user: User,
    ) -> Dict:
        """Update member role."""
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        # ensure current user is admin
        current_role = await self._ensure_member(workspace_id, current_user)
        self._ensure_admin_role(current_role)

        # get target member
        target_member = await self.member_repo.get_member(workspace_id, target_user_id)
        if not target_member:
            raise NotFoundException("User not found in workspace")

        # cannot modify the owner's role
        if workspace.owner_id == target_user_id:
            raise BadRequestException("Cannot change owner role")

        # owner role cannot be assigned via role update
        if new_role == WorkspaceMemberRole.owner:
            raise BadRequestException("Cannot assign owner role")

        # role hierarchy protection: non-owner cannot modify members >= their own level
        if current_role != WorkspaceMemberRole.owner:
            if ROLE_RANK.get(target_member.role, 0) >= ROLE_RANK.get(current_role, 0):
                raise ForbiddenException("Cannot modify a member with equal or higher role")
            if ROLE_RANK.get(new_role, 0) >= ROLE_RANK.get(current_role, 0):
                raise ForbiddenException("Cannot assign a role equal to or higher than your own")

        # if modifying an admin, check if they are the last admin
        if target_member.role in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
            admin_count = await self.member_repo.count_admins(workspace_id)
            if admin_count <= 1 and new_role not in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
                raise BadRequestException("Cannot remove the last admin from a workspace")

        # update role
        updated_member = await self.member_repo.update_member_role(workspace_id, target_user_id, new_role)
        await self.commit()

        # return updated member info
        from app.repositories.auth_user import AuthUserRepository

        user_repo = AuthUserRepository(self.db)
        user = await user_repo.get_by(id=target_user_id)

        return {
            "id": str(target_user_id),
            "userId": str(target_user_id),
            "workspaceId": str(workspace_id),
            "email": user.email if user else "",
            "name": user.name if user else "",
            "role": new_role.value if hasattr(new_role, "value") else new_role,
            "isOwner": str(workspace.owner_id) == str(target_user_id),
            "createdAt": updated_member.created_at.isoformat()
            if updated_member and hasattr(updated_member, "created_at") and updated_member.created_at
            else None,
            "updatedAt": updated_member.updated_at.isoformat()
            if updated_member and hasattr(updated_member, "updated_at") and updated_member.updated_at
            else None,
        }

    async def remove_member(
        self,
        *,
        workspace_id: uuid.UUID,
        target_user_id: uuid.UUID,
        current_user: User,
    ) -> bool:
        """
        Remove a workspace member.
        Aligned with legacy project logic:
        - Admin can remove any member (unless they are the last admin)
        - Regular members can only remove themselves
        """
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        # get target user's member record
        target_member = await self.member_repo.get_member(workspace_id, str(target_user_id))
        if not target_member:
            raise NotFoundException("User not found in workspace")

        # cannot remove the workspace owner
        if str(workspace.owner_id) == str(target_user_id):
            raise BadRequestException("Cannot remove workspace owner")

        # get current user's role
        current_role = await self._get_role(workspace, current_user)
        is_admin = current_role in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}
        is_self = str(target_user_id) == current_user.id

        if not is_admin and not is_self:
            raise ForbiddenException("Insufficient permissions")

        # role hierarchy protection: non-owner cannot remove members >= their own level
        if is_admin and not is_self and current_role != WorkspaceMemberRole.owner:
            assert isinstance(current_role, WorkspaceMemberRole)
            if ROLE_RANK.get(target_member.role, 0) >= ROLE_RANK.get(current_role, 0):
                raise ForbiddenException("Cannot remove a member with equal or higher role")

        # if removing an admin/owner role member, check if they are the last admin
        if target_member.role in {WorkspaceMemberRole.owner, WorkspaceMemberRole.admin}:
            admin_count = await self.member_repo.count_admins(workspace_id)
            if admin_count <= 1:
                raise BadRequestException("Cannot remove the last admin from a workspace")

        # execute deletion
        await self.member_repo.delete_member(workspace_id, str(target_user_id))
        await self.commit()
        return True
