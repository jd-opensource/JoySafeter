"""PlatformToken Service — create, list, revoke."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.common.permissions import VALID_SCOPES
from app.models.platform_token import PlatformToken
from app.repositories.platform_token import PlatformTokenRepository
from app.utils.string import hash_string_sha256

from .base import BaseService

MAX_ACTIVE_TOKENS_PER_USER = 50
TOKEN_PREFIX = "sk_"


class PlatformTokenService(BaseService[PlatformToken]):
    VALID_RESOURCE_TYPES = {"skill", "graph", "tool"}

    def __init__(self, db):
        super().__init__(db)
        self.repo: PlatformTokenRepository = PlatformTokenRepository(db)

    async def create_token(
        self,
        user_id: str,
        name: str,
        scopes: List[str],
        resource_type: Optional[str] = None,
        resource_id: Optional[uuid.UUID] = None,
        expires_at: Optional[datetime] = None,
    ) -> Tuple[PlatformToken, str]:
        """Create a new token. Returns (token_record, plaintext_token)."""
        # Check limit
        active_count = await self.repo.count_active_by_user(user_id)
        if active_count >= MAX_ACTIVE_TOKENS_PER_USER:
            raise BadRequestException(f"Maximum of {MAX_ACTIVE_TOKENS_PER_USER} active tokens reached")

        # Validate scopes
        invalid = set(scopes) - set(VALID_SCOPES)
        if invalid:
            raise BadRequestException(f"Invalid scopes: {invalid}")

        # Validate resource_type/resource_id pair
        if (resource_type is None) != (resource_id is None):
            raise BadRequestException("resource_type and resource_id must both be provided or both be null")
        if resource_type is not None and resource_type not in self.VALID_RESOURCE_TYPES:
            raise BadRequestException(
                f"Invalid resource_type: {resource_type}. Must be one of {self.VALID_RESOURCE_TYPES}"
            )

        # Validate resource exists and user has permission
        if resource_type is not None and resource_id is not None:
            if resource_type == "skill":
                from app.repositories.skill import SkillRepository
                from app.models.skill_collaborator import CollaboratorRole
                from app.common.skill_permissions import check_skill_access
                skill_repo = SkillRepository(self.db)
                skill = await skill_repo.get(resource_id)
                if not skill:
                    raise NotFoundException(f"Skill {resource_id} not found")
                try:
                    await check_skill_access(self.db, skill, user_id, CollaboratorRole.editor)
                except ForbiddenException:
                    raise ForbiddenException("No permission to create token for this skill")
            elif resource_type == "graph":
                from app.repositories.workspace import WorkspaceRepository, WorkspaceMemberRepository
                workspace_repo = WorkspaceRepository(self.db)
                member_repo = WorkspaceMemberRepository(self.db)
                workspace = await workspace_repo.get(resource_id)
                if not workspace:
                    raise NotFoundException(f"Workspace {resource_id} not found")
                if workspace.owner_id != user_id:
                    member = await member_repo.get_member(resource_id, user_id)
                    if not member or member.role not in {"admin", "owner"}:
                        raise ForbiddenException("No permission to create token for this workspace")
            elif resource_type == "tool":
                from app.repositories.tool import ToolRepository
                tool_repo = ToolRepository(self.db)
                tool = await tool_repo.get(resource_id)
                if not tool:
                    raise NotFoundException(f"Tool {resource_id} not found")
                if tool.owner_id != user_id:
                    raise ForbiddenException("No permission to create token for this tool")

        # Generate token
        raw_secret = secrets.token_urlsafe(36)
        plaintext = f"{TOKEN_PREFIX}{raw_secret}"
        token_hash = hash_string_sha256(plaintext)
        token_prefix = plaintext[:12]

        pt = PlatformToken(
            user_id=user_id,
            name=name,
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=scopes,
            resource_type=resource_type,
            resource_id=resource_id,
            expires_at=expires_at,
            is_active=True,
        )
        self.db.add(pt)
        await self.db.commit()
        await self.db.refresh(pt)
        return pt, plaintext

    async def list_tokens(
        self,
        user_id: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[uuid.UUID] = None,
    ) -> List[PlatformToken]:
        return await self.repo.list_by_user_and_resource(user_id, resource_type, resource_id)

    async def revoke_by_resource(self, resource_type: str, resource_id: str) -> int:
        """Soft-delete all tokens bound to a resource"""
        return await self.repo.deactivate_by_resource(resource_type, resource_id)

    async def revoke_token(
        self,
        token_id: uuid.UUID,
        user_id: str,
    ) -> None:
        pt = await self.repo.get(token_id)
        if not pt:
            raise NotFoundException("Token not found")
        if pt.user_id != user_id:
            raise ForbiddenException("You can only revoke your own tokens")
        pt.is_active = False
        await self.db.commit()
