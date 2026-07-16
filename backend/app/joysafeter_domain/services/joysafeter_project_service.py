import uuid
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_shared.common.app_errors import ResourceConflictError


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_project(self, org_id: str, name: str, slug: str, is_default: bool = False) -> Project:
        project = Project(id=str(uuid.uuid4()), org_id=org_id, name=name, slug=slug, is_default=is_default)
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def get_project(self, project_id: str, org_id: str) -> Optional[Project]:
        result = await self.db.execute(select(Project).where(and_(Project.id == project_id, Project.org_id == org_id)))
        return result.scalar_one_or_none()

    async def get_default_project(self, org_id: str) -> Optional[Project]:
        result = await self.db.execute(
            select(Project)
            .where(
                and_(
                    Project.org_id == org_id,
                    Project.is_default.is_(True),
                    Project.archived_at.is_(None),
                )
            )
            .order_by(Project.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_projects(self, org_id: str, include_archived: bool = False) -> List[Project]:
        conditions = [Project.org_id == org_id]
        if not include_archived:
            conditions.append(Project.archived_at.is_(None))
        result = await self.db.execute(select(Project).where(and_(*conditions)).order_by(Project.created_at))
        return list(result.scalars().all())

    async def set_default_project(self, project_id: str, org_id: str) -> Project:
        result = await self.db.execute(select(Project).where(and_(Project.id == project_id, Project.org_id == org_id)))
        target = result.scalar_one_or_none()
        if target is None:
            raise ValueError(f"Project {project_id} not found for org {org_id}")
        if target.archived_at is not None:
            raise ResourceConflictError(
                code="PROJECT_ARCHIVED",
                message="Cannot set an archived project as default",
                data={"project_id": project_id, "organization_id": org_id},
                user_action="refresh",
            )

        result = await self.db.execute(
            select(Project).where(and_(Project.org_id == org_id, Project.is_default.is_(True)))
        )
        for project in result.scalars().all():
            project.is_default = False

        target.is_default = True
        await self.db.commit()
        await self.db.refresh(target)
        return target

    async def restore_project(self, project_id: str, org_id: str) -> Project:
        result = await self.db.execute(select(Project).where(and_(Project.id == project_id, Project.org_id == org_id)))
        target = result.scalar_one_or_none()
        if target is None:
            raise ValueError(f"Project {project_id} not found for org {org_id}")
        if target.archived_at is None:
            return target

        if target.is_default:
            active_default_result = await self.db.execute(
                select(Project.id)
                .where(
                    and_(
                        Project.org_id == org_id,
                        Project.id != project_id,
                        Project.is_default.is_(True),
                        Project.archived_at.is_(None),
                    )
                )
                .limit(1)
            )
            if active_default_result.scalar_one_or_none() is not None:
                target.is_default = False

        target.archived_at = None
        await JoySafeterScheduleService(self.db).resume_after_project_restore(project_id)
        await self.db.commit()
        await self.db.refresh(target)
        return target

    async def ensure_default_project(self, org_id: str, org_name: str = "Default") -> Project:
        existing = await self.get_default_project(org_id)
        if existing:
            return existing

        active_result = await self.db.execute(
            select(Project)
            .where(and_(Project.org_id == org_id, Project.archived_at.is_(None)))
            .order_by(Project.created_at)
            .limit(1)
        )
        active_project = active_result.scalar_one_or_none()
        if active_project:
            return await self.set_default_project(active_project.id, org_id)

        slug = "default"
        slug_result = await self.db.execute(select(Project.id).where(and_(Project.org_id == org_id, Project.slug == slug)))
        if slug_result.scalar_one_or_none() is not None:
            slug = f"default-{uuid.uuid4().hex[:8]}"
        return await self.create_project(org_id, "Default", slug, is_default=True)
