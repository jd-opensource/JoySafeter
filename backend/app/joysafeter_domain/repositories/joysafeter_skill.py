"""
Skill Repository
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterSkill,
    JoySafeterSkillFile,
    JoySafeterSkillSecurityScan,
    JoySafeterSkillVisibility,
)
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.ids import SkillId, SkillSecurityScanId

from .base import BaseRepository


class SkillRepository(BaseRepository[JoySafeterSkill]):
    def __init__(self, db: AsyncSession):
        super().__init__(JoySafeterSkill, db)

    async def list_by_user(
        self,
        org_id: str,
        user_id: str,
        include_public: bool = True,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        caller_org_role: Optional[JoySafeterRole] = None,
        limit: int = 20,
        after_id: Optional[SkillId] = None,
    ) -> tuple[List[JoySafeterSkill], bool]:
        """List skills for a user with cursor pagination.

        The filter mirrors ``check_skill_access`` so what a user can
        ``GET`` matches what they can list:

          - skills they own
          - skills they collaborate on
          - public skills (when ``include_public``)
          - ``visibility=organization`` skills in the CALLER'S ACTIVE
            org (``org_id``)
          - ``visibility=project`` skills the user is a member of the
            specific project (via the ``project_members`` table)
          - EVERY skill in the active org when the caller is an org
            super-user (owner/admin) — they are ADMIN on every skill in
            their org per ``effective_project_capability``, so listing must
            surface them even for projects the super-user has no
            ``ProjectMember`` row in (otherwise list != get).

        Strict org isolation: every skill returned must belong to a
        project in the caller's ACTIVE org (``org_id``) — even ones the
        caller owns. A user who's an owner of two orgs and switches
        context should see only the org they're currently working in.
        Public skills are the one carve-out: they cross every boundary.

        ``org_id`` is the caller's currently-active organization, taken
        from ``JoySafeterAuthContext.org_id`` at the API boundary.
        """
        query = select(JoySafeterSkill).options(selectinload(JoySafeterSkill.files))

        conditions = []

        # (b) ``organization`` tier — every project in the caller's
        # ACTIVE org they belong to. The ``Member`` join is required:
        # a user with the active org in their session header but who
        # isn't actually a member of that org gets nothing (defense
        # against forged X-Org-Id headers).
        org_project_subquery = (
            select(Project.id)
            .join(Member, Member.organization_id == Project.org_id)
            .where(
                Member.user_id == user_id,
                Project.org_id == org_id,
            )
            .scalar_subquery()
        )
        # (a) Project-membership tier — every project the caller has a
        # ProjectMember row in (any role). This is the single axis that
        # replaces the old owner/collaborator OR-clauses: membership of
        # the skill's project is what grants a listing. Constrain to projects
        # in the active org so multi-org memberships cannot leak through.
        user_project_subquery = (
            select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(ProjectMember.user_id == user_id, Project.org_id == org_id)
            .scalar_subquery()
        )

        visibility_clauses = [
            JoySafeterSkill.project_id.in_(user_project_subquery),
            and_(
                JoySafeterSkill.visibility == JoySafeterSkillVisibility.ORGANIZATION.value,
                JoySafeterSkill.project_id.in_(org_project_subquery),
            ),
        ]
        if include_public:
            visibility_clauses.append(JoySafeterSkill.visibility == JoySafeterSkillVisibility.PUBLIC.value)
        if caller_org_role is not None and caller_org_role.is_org_superuser():
            all_active_org_projects = select(Project.id).where(Project.org_id == org_id).scalar_subquery()
            visibility_clauses.append(JoySafeterSkill.project_id.in_(all_active_org_projects))
        conditions.append(or_(*visibility_clauses))

        if project_id is not None:
            # ``project_id`` is the user's CURRENT active project. It
            # narrows the listing to skills that live in this project
            # — BUT only for the project-scoped tiers. A skill with
            # ``visibility=organization`` or ``visibility=public``
            # crosses project boundaries by design; filtering them out
            # here would hide every cross-project skill the user can
            # legitimately see. So we make the project filter
            # disjunctive with the org/public visibility, not an
            # absolute AND.
            conditions.append(
                or_(
                    JoySafeterSkill.project_id == project_id,
                    JoySafeterSkill.visibility == JoySafeterSkillVisibility.ORGANIZATION.value,
                    JoySafeterSkill.visibility == JoySafeterSkillVisibility.PUBLIC.value,
                )
            )

        if tags:
            for tag in tags:
                conditions.append(JoySafeterSkill.tags.contains([tag]))

        if conditions:
            query = query.where(and_(*conditions))

        query = apply_created_at_desc_cursor(query, JoySafeterSkill, after_id).limit(limit + 1)
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        has_more = len(items) > limit
        return items[:limit], has_more

    async def get_with_files(self, skill_id: SkillId) -> Optional[JoySafeterSkill]:
        """Get a skill with its associated files."""
        query = select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id)
        query = query.options(selectinload(JoySafeterSkill.files))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def get_by_ids(self, skill_ids: List[SkillId]) -> List[JoySafeterSkill]:
        """Get multiple skills by their IDs, with files eagerly loaded."""
        if not skill_ids:
            return []
        query = (
            select(JoySafeterSkill)
            .options(selectinload(JoySafeterSkill.files))
            .where(JoySafeterSkill.id.in_(skill_ids))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_name_and_project(self, name: str, project_id: Optional[str]) -> Optional[JoySafeterSkill]:
        """Get a skill by name within a project.

        Skill names are unique per ``(project_id, name)`` — the single-axis
        identity key. ``None`` project_id can never match a real skill (the
        column is NOT NULL) and simply yields no row.
        """
        query = select(JoySafeterSkill).where(
            and_(JoySafeterSkill.name == name, JoySafeterSkill.project_id == project_id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class SkillFileRepository(BaseRepository[JoySafeterSkillFile]):
    def __init__(self, db: AsyncSession):
        super().__init__(JoySafeterSkillFile, db)

    async def list_by_skill(self, skill_id: SkillId) -> List[JoySafeterSkillFile]:
        """List all files for a skill."""
        result = await self.db.execute(select(JoySafeterSkillFile).where(JoySafeterSkillFile.skill_id == skill_id))
        return list(result.scalars().all())

    async def delete_by_skill(self, skill_id: SkillId) -> int:
        """Delete all files for a skill."""
        from sqlalchemy import delete

        stmt = delete(JoySafeterSkillFile).where(JoySafeterSkillFile.skill_id == skill_id)
        result = await self.db.execute(stmt)
        return result.rowcount if result.rowcount is not None else 0  # type: ignore


class SkillSecurityScanRepository(BaseRepository[JoySafeterSkillSecurityScan]):
    def __init__(self, db: AsyncSession):
        super().__init__(JoySafeterSkillSecurityScan, db)

    async def list_by_skill(
        self,
        skill_id: SkillId,
        limit: int = 20,
        after_id: Optional[SkillSecurityScanId] = None,
    ) -> tuple[List[JoySafeterSkillSecurityScan], bool]:
        """List scan history for a skill with cursor pagination."""
        query = select(JoySafeterSkillSecurityScan).where(JoySafeterSkillSecurityScan.skill_id == skill_id)
        query = apply_created_at_desc_cursor(query, JoySafeterSkillSecurityScan, after_id).limit(limit + 1)
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        has_more = len(items) > limit
        return items[:limit], has_more

    async def get_latest_by_skill(self, skill_id: SkillId) -> Optional[JoySafeterSkillSecurityScan]:
        """Get the latest scan for a skill."""
        query = (
            select(JoySafeterSkillSecurityScan)
            .where(JoySafeterSkillSecurityScan.skill_id == skill_id)
            .order_by(JoySafeterSkillSecurityScan.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
