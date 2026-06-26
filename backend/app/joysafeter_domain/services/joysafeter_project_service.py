import uuid
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project


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
            select(Project).where(and_(Project.org_id == org_id, Project.is_default.is_(True))).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_projects(self, org_id: str, include_archived: bool = False) -> List[Project]:
        conditions = [Project.org_id == org_id]
        if not include_archived:
            conditions.append(Project.archived_at.is_(None))
        result = await self.db.execute(
            select(Project)
            .where(and_(*conditions))
            .order_by(Project.created_at)
        )
        return list(result.scalars().all())

    async def set_default_project(self, project_id: str, org_id: str) -> Project:
        result = await self.db.execute(select(Project).where(and_(Project.org_id == org_id, Project.is_default.is_(True))))
        for project in result.scalars().all():
            project.is_default = False

        result = await self.db.execute(select(Project).where(and_(Project.id == project_id, Project.org_id == org_id)))
        project = result.scalar_one_or_none()
        if project:
            project.is_default = True
        await self.db.commit()
        return project

    async def ensure_default_project(self, org_id: str, org_name: str = "Default") -> Project:
        existing = await self.get_default_project(org_id)
        if existing:
            return existing
        return await self.create_project(org_id, "Default", "default", is_default=True)
