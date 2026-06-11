"""PlatformToken Service — create, list, revoke."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from app.joysafeter_shared.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.joysafeter_shared.common.permissions import VALID_SCOPES
from app.joysafeter_domain.models.enums import OrgRole
from app.joysafeter_domain.models.platform_token import PlatformToken
from app.joysafeter_domain.repositories.platform_token import PlatformTokenRepository
from app.joysafeter_shared.utils.string import hash_string_sha256

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
            raise InvalidRequestError(
                f"Maximum of {MAX_ACTIVE_TOKENS_PER_USER} active tokens reached",
                code="PLATFORM_TOKEN_LIMIT_EXCEEDED",
                data={"limit": MAX_ACTIVE_TOKENS_PER_USER},
            )

        # Validate scopes
        invalid = set(scopes) - set(VALID_SCOPES)
        if invalid:
            raise InvalidRequestError(
                f"Invalid scopes: {invalid}",
                code="PLATFORM_TOKEN_SCOPES_INVALID",
                data={"scopes": sorted(invalid)},
            )

        # Validate resource_type/resource_id pair
        if (resource_type is None) != (resource_id is None):
            raise InvalidRequestError(
                "resource_type and resource_id must both be provided or both be null",
                code="PLATFORM_TOKEN_RESOURCE_BINDING_INVALID",
            )
        if resource_type is not None and resource_type not in self.VALID_RESOURCE_TYPES:
            raise InvalidRequestError(
                f"Invalid resource_type: {resource_type}. Must be one of {self.VALID_RESOURCE_TYPES}",
                code="PLATFORM_TOKEN_RESOURCE_TYPE_INVALID",
                data={"resource_type": resource_type},
            )

        # Validate resource exists and user has permission
        if resource_type is not None and resource_id is not None:
            if resource_type == "skill":
                from app.joysafeter_shared.common.skill_permissions import check_skill_access
                from app.joysafeter_domain.models.skill_collaborator import CollaboratorRole
                from app.joysafeter_domain.repositories.skill import SkillRepository

                skill_repo = SkillRepository(self.db)
                skill = await skill_repo.get(resource_id)
                if not skill:
                    raise NotFoundError(
                        "Skill not found",
                        code="SKILL_NOT_FOUND",
                        data={"skill_id": str(resource_id)},
                    )
                try:
                    await check_skill_access(self.db, skill, user_id, CollaboratorRole.editor)
                except AccessDeniedError:
                    raise AccessDeniedError(
                        "No permission to create token for this skill",
                        code="PLATFORM_TOKEN_SKILL_ACCESS_DENIED",
                        data={"skill_id": str(resource_id)},
                    )
            elif resource_type == "graph":
                # @deprecated — graph tokens used workspace access; now uses project via org membership.
                # Validate via org membership on the project that owns this resource.
                from sqlalchemy import select as sa_select
                from app.joysafeter_domain.models.project import Project
                from app.joysafeter_domain.models.organization import Member as OrgMember

                project = (
                    await self.db.execute(sa_select(Project).where(Project.id == str(resource_id)).limit(1))
                ).scalar_one_or_none()
                if not project:
                    raise NotFoundError(
                        "Project not found",
                        code="PROJECT_NOT_FOUND",
                        data={"project_id": str(resource_id)},
                    )
                org_member = (
                    await self.db.execute(
                        sa_select(OrgMember).where(
                            OrgMember.organization_id == project.org_id,
                            OrgMember.user_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if not org_member or org_member.role not in {"admin", "owner"}:
                    raise AccessDeniedError(
                        "No permission to create token for this project",
                        code="PLATFORM_TOKEN_PROJECT_ACCESS_DENIED",
                        data={"project_id": str(resource_id)},
                    )
            elif resource_type == "tool":
                from app.joysafeter_domain.repositories.tool import ToolRepository

                tool_repo = ToolRepository(self.db)
                tool = await tool_repo.get(resource_id)
                if not tool:
                    raise NotFoundError(
                        "Tool not found",
                        code="TOOL_NOT_FOUND",
                        data={"tool_id": str(resource_id)},
                    )
                if tool.owner_id != user_id:
                    raise AccessDeniedError(
                        "No permission to create token for this tool",
                        code="PLATFORM_TOKEN_TOOL_ACCESS_DENIED",
                        data={"tool_id": str(resource_id)},
                    )

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
            raise NotFoundError("Token not found", code="PLATFORM_TOKEN_NOT_FOUND", data={"token_id": str(token_id)})
        if pt.user_id != user_id:
            raise AccessDeniedError(
                "You can only revoke your own tokens",
                code="PLATFORM_TOKEN_REVOKE_FORBIDDEN",
                data={"token_id": str(token_id)},
            )
        pt.is_active = False
        await self.db.commit()
