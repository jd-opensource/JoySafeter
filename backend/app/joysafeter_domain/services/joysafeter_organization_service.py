from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_file import JoySafeterFile
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterMemoryStore
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_schedule import JoySafeterSchedule
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_vault import JoySafeterVault
from app.joysafeter_domain.services.joysafeter_organization_member_service import OrganizationMemberService
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError, ResourceConflictError

PROJECT_RESOURCE_BLOCKERS = (
    ("agents", JoySafeterAgent),
    ("environments", JoySafeterEnvironment),
    ("files", JoySafeterFile),
    ("memory_stores", JoySafeterMemoryStore),
    ("sandboxes", JoySafeterSandbox),
    ("schedules", JoySafeterSchedule),
    ("secrets", JoySafeterSecret),
    ("sessions", JoySafeterSession),
    ("skills", JoySafeterSkill),
    ("tasks", JoySafeterTask),
    ("vaults", JoySafeterVault),
)


@dataclass(frozen=True)
class CreatedOrganization:
    organization: Organization
    default_project: Project


class OrganizationService:
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
        self.db.add(Member(**member_kwargs))

        project_kwargs = {
            "org_id": org.id,
            "name": "Default",
            "slug": "default",
            "is_default": True,
        }
        if default_project_id is not None:
            project_kwargs["id"] = default_project_id
        default_project = Project(**project_kwargs)
        self.db.add(default_project)
        await self.db.flush()
        await ProjectService(self.db).grant_project_membership(
            project_id=default_project.id,
            user_id=owner_user_id,
            role="admin",
        )

        await self.db.commit()
        await self.db.refresh(org)
        await self.db.refresh(default_project)
        return CreatedOrganization(organization=org, default_project=default_project)

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
            result = await self.db.execute(select(model.id).where(model.project_id.in_(project_ids)).limit(1))
            if result.scalar_one_or_none() is not None:
                blockers.append(resource_name)
        return blockers
