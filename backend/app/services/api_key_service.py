"""
ApiKey 服务
- 列表/创建/删除
- 权限：personal 仅本人；workspace 需 workspace admin/owner
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.api_key import ApiKey
from app.models.workspace import WorkspaceMemberRole
from app.repositories.api_key import ApiKeyRepository
from app.repositories.workspace import WorkspaceMemberRepository, WorkspaceRepository

from .base import BaseService


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return key
    return f"{key[:4]}***{key[-4:]}"


class ApiKeyService(BaseService[ApiKey]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = ApiKeyRepository(db)
        self.ws_repo = WorkspaceRepository(db)
        self.member_repo = WorkspaceMemberRepository(db)

    def _role_rank(self, role: WorkspaceMemberRole) -> int:
        order = [
            WorkspaceMemberRole.viewer,
            WorkspaceMemberRole.member,
            WorkspaceMemberRole.admin,
            WorkspaceMemberRole.owner,
        ]
        try:
            return order.index(role)
        except ValueError:
            return -1

    async def _ensure_workspace_admin(self, workspace_id: uuid.UUID, user_id: uuid.UUID):
        workspace = await self.ws_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")
        if workspace.owner_id == user_id:
            return
        member = await self.member_repo.get_member(workspace_id, user_id)
        if not member or self._role_rank(member.role) < self._role_rank(WorkspaceMemberRole.admin):
            raise ForbiddenException("Insufficient workspace permission")

    # ---------------------------- #
    # 公共方法
    # ---------------------------- #
    async def list_keys(self, *, current_user_id: uuid.UUID, workspace_id: Optional[uuid.UUID]) -> List[Dict]:
        keys: List[ApiKey] = []
        if workspace_id:
            await self._ensure_workspace_admin(workspace_id, current_user_id)
            keys = await self.repo.list_by_workspace(workspace_id)
        else:
            keys = await self.repo.list_by_user(current_user_id)

        return [
            {
                "id": str(k.id),
                "name": k.name,
                "type": k.type,
                "keyMasked": _mask(k.key),
                "workspaceId": str(k.workspace_id) if k.workspace_id else None,
                "expiresAt": k.expires_at,
                "lastUsed": k.last_used,
                "createdAt": k.created_at,
                "updatedAt": k.updated_at,
            }
            for k in keys
        ]

    async def create_key(
        self,
        *,
        current_user_id: uuid.UUID,
        name: str,
        type: str = "personal",
        workspace_id: Optional[uuid.UUID] = None,
        expires_at: Optional[datetime] = None,
    ) -> Dict:
        if type not in ("personal", "workspace"):
            raise BadRequestException("Invalid api key type")

        if type == "personal":
            workspace_id = None
        else:
            if not workspace_id:
                raise BadRequestException("workspace_id is required for workspace key")
            await self._ensure_workspace_admin(workspace_id, current_user_id)

        # 生成唯一 key
        key_str = secrets.token_urlsafe(32)
        record = ApiKey(
            name=name,
            key=key_str,
            type=type,
            user_id=current_user_id,
            workspace_id=workspace_id,
            created_by=current_user_id,
            expires_at=expires_at,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)

        return {
            "id": str(record.id),
            "name": record.name,
            "type": record.type,
            "key": record.key,  # 创建时返回明文
            "workspaceId": str(record.workspace_id) if record.workspace_id else None,
            "expiresAt": record.expires_at,
            "createdAt": record.created_at,
        }

    async def delete_key(self, *, key_id: uuid.UUID, current_user_id: uuid.UUID) -> None:
        key = await self.repo.get(key_id)
        if not key:
            raise NotFoundException("ApiKey not found")

        if key.type == "workspace":
            await self._ensure_workspace_admin(key.workspace_id, current_user_id)  # type: ignore[arg-type]
        else:
            if key.user_id != current_user_id:
                raise ForbiddenException("Cannot delete others' personal key")

        await self.repo.delete_by_id(key_id)
        await self.db.commit()
