from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_file import JoySafeterFile
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterMemoryStore
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_organization_member_service import OrganizationMemberService
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError, ResourceConflictError

PROJECT_RESOURCE_BLOCKERS = (
    ("agents", JoySafeterAgent),
    ("environments", JoySafeterEnvironment),
    ("files", JoySafeterFile),
    ("memory_stores", JoySafeterMemoryStore),
    ("sandboxes", JoySafeterSandbox),
    ("credentials", JoySafeterCredential),
    ("credential_groups", JoySafeterCredentialGroup),
    ("sessions", JoySafeterSession),
    ("skills", JoySafeterSkill),
    ("tasks", JoySafeterTask),
    ("triggers", JoySafeterTrigger),
)


@dataclass(frozen=True)
class CreatedOrganization:
    organization: Organization
    owner_membership: Member
    default_project: Project


class OrganizationService:
    DEFAULT_PROJECT_NAME = "Main"
    DEFAULT_PROJECT_SLUG = "main"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def normalize_slug(value: str | None, *, fallback: str = "org") -> str:
        slug = (value or "").lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        if not slug:
            slug = fallback
        return f"{slug}-{uuid.uuid4().hex[:6]}"

    @staticmethod
    def bootstrap_organization_name(*, user_name: str | None, user_email: str | None) -> str:
        normalized_name = " ".join((user_name or "").split())
        if normalized_name and normalized_name.casefold() != "default":
            return normalized_name

        email_local_part = (user_email or "").partition("@")[0].strip()
        if email_local_part and email_local_part.casefold() != "default":
            return email_local_part
        return "Personal"

    async def add_with_owner_and_default_project(
        self,
        *,
        name: str,
        slug: str | None = None,
        owner_user_id: str,
        organization_id: str | None = None,
        owner_member_id: str | None = None,
        default_project_id: str | None = None,
    ) -> CreatedOrganization:
        if not name or not name.strip():
            raise InvalidRequestError(
                code="ORGANIZATION_NAME_REQUIRED",
                message="Organization name is required",
                data={"field": "name"},
                user_action="fix_input",
            )

        org_slug = self.normalize_slug(slug or name)
        org_kwargs = {"name": name.strip(), "slug": org_slug}
        if organization_id is not None:
            org_kwargs["id"] = organization_id
        org = Organization(**org_kwargs)
        self.db.add(org)
        await self.db.flush()

        member_kwargs = {
            "user_id": owner_user_id,
            "organization_id": org.id,
            "role": "owner",
        }
        if owner_member_id is not None:
            member_kwargs["id"] = owner_member_id
        owner_membership = Member(**member_kwargs)
        self.db.add(owner_membership)

        project_kwargs = {
            "org_id": org.id,
            "name": self.DEFAULT_PROJECT_NAME,
            "slug": self.DEFAULT_PROJECT_SLUG,
            "is_default": True,
            "created_by_user_id": owner_user_id,
        }
        if default_project_id is not None:
            project_kwargs["id"] = default_project_id
        default_project = Project(**project_kwargs)
        self.db.add(default_project)
        await self.db.flush()

        return CreatedOrganization(
            organization=org,
            owner_membership=owner_membership,
            default_project=default_project,
        )

    async def create_with_owner_and_default_project(
        self,
        *,
        name: str,
        slug: str | None = None,
        owner_user_id: str,
        organization_id: str | None = None,
        owner_member_id: str | None = None,
        default_project_id: str | None = None,
    ) -> CreatedOrganization:
        created = await self.add_with_owner_and_default_project(
            name=name,
            slug=slug,
            owner_user_id=owner_user_id,
            organization_id=organization_id,
            owner_member_id=owner_member_id,
            default_project_id=default_project_id,
        )
        await self.db.commit()
        await self.db.refresh(created.organization)
        await self.db.refresh(created.default_project)
        return created

    async def delete_organization(self, *, organization_id: str, actor_user_id: str) -> None:
        await OrganizationMemberService(self.db).require_owner(
            organization_id,
            actor_user_id,
            message="Only the organization owner can delete it",
        )

        result = await self.db.execute(select(Organization).where(Organization.id == organization_id))
        org = result.scalar_one_or_none()
        if org is None:
            raise NotFoundError(
                code="ORGANIZATION_NOT_FOUND",
                message="Organization not found",
                data={"organization_id": organization_id},
                user_action="refresh",
            )

        project_result = await self.db.execute(select(Project.id).where(Project.org_id == organization_id))
        project_ids = list(project_result.scalars().all())
        if project_ids:
            blockers = await self._project_resource_blockers(project_ids)
            if blockers:
                raise ResourceConflictError(
                    code="ORGANIZATION_PROJECT_RESOURCES_EXIST",
                    message="Organization has project resources. Delete or archive project resources before deleting the organization.",
                    data={"organization_id": organization_id, "resources": blockers},
                    user_action="delete_resources",
                )

        await self.db.execute(delete(Member).where(Member.organization_id == organization_id))
        await self.db.execute(delete(Project).where(Project.org_id == organization_id))
        await self.db.delete(org)
        await self.db.commit()

    async def _project_resource_blockers(self, project_ids: list[str]) -> list[str]:
        blockers: list[str] = []
        for resource_name, model in PROJECT_RESOURCE_BLOCKERS:
            query = select(model.id).where(model.project_id.in_(project_ids))
            result = await self.db.execute(query.limit(1))
            if result.scalar_one_or_none() is not None:
                blockers.append(resource_name)
        return blockers
