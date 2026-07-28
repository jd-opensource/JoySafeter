import logging
import re
import uuid
from typing import Any, List, Optional, cast

from sqlalchemy import CursorResult, and_, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask
from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService
from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.app_errors import InvalidRequestError, ResourceConflictError, ServiceUnavailableError
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.common.joysafeter_auth.context import (
    JoySafeterRole,
    ProjectRole,
    default_project_role_for_org_role,
)
from app.joysafeter_shared.orchestrator_bridge.runtime_commands import relay_sandbox_destroy_via_redis
from app.joysafeter_shared.utils.datetime import utc_now

logger = logging.getLogger(__name__)

PROJECT_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,253}[a-z0-9])?$")
TERMINAL_TASK_STATUSES = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def normalize_slug(value: str | None) -> str:
        slug = (value or "").lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug

    @staticmethod
    def _validate_name(name: str | None) -> str:
        normalized = (name or "").strip()
        if not normalized:
            raise InvalidRequestError(
                code="PROJECT_NAME_REQUIRED",
                message="Project name is required",
                data={"field": "name"},
                user_action="fix_input",
            )
        if len(normalized) > 255:
            raise InvalidRequestError(
                code="PROJECT_NAME_TOO_LONG",
                message="Project name must be 255 characters or fewer",
                data={"field": "name", "max_length": 255},
                user_action="fix_input",
            )
        return normalized

    @classmethod
    def _validate_slug(cls, slug: str | None) -> str:
        normalized = cls.normalize_slug(slug)
        if not normalized:
            raise InvalidRequestError(
                code="PROJECT_SLUG_REQUIRED",
                message="Project slug is required",
                data={"field": "slug"},
                user_action="fix_input",
            )
        if len(normalized) > 255:
            raise InvalidRequestError(
                code="PROJECT_SLUG_TOO_LONG",
                message="Project slug must be 255 characters or fewer",
                data={"field": "slug", "max_length": 255},
                user_action="fix_input",
            )
        if not PROJECT_SLUG_PATTERN.match(normalized):
            raise InvalidRequestError(
                code="PROJECT_SLUG_INVALID",
                message="Project slug must contain only lowercase letters, numbers, and hyphens",
                data={"field": "slug"},
                user_action="fix_input",
            )
        return normalized

    @staticmethod
    def _slug_conflict_error(org_id: str, slug: str) -> ResourceConflictError:
        return ResourceConflictError(
            code="PROJECT_SLUG_CONFLICT",
            message="Project slug already exists in this organization",
            data={"organization_id": org_id, "slug": slug},
            user_action="fix_input",
        )

    @staticmethod
    def _is_project_slug_integrity_error(exc: IntegrityError) -> bool:
        message = str(exc.orig or exc).lower()
        return "uq_joysafeter_organization_projects_org_slug" in message or (
            "joysafeter_organization_projects.org_id" in message and "joysafeter_organization_projects.slug" in message
        )

    async def _project_slug_exists(self, org_id: str, slug: str, *, exclude_project_id: str | None = None) -> bool:
        conditions = [Project.org_id == org_id, Project.slug == slug]
        if exclude_project_id is not None:
            conditions.append(Project.id != exclude_project_id)
        result = await self.db.execute(select(Project.id).where(and_(*conditions)).limit(1))
        return result.scalar_one_or_none() is not None

    @staticmethod
    def role_has_org_wide_project_access(role: str | JoySafeterRole) -> bool:
        return JoySafeterRole.normalize(role.value if isinstance(role, JoySafeterRole) else role).can_manage_projects()

    async def _load_project_member(self, project_id: str, user_id: str) -> ProjectMember | None:
        result = await self.db.execute(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def grant_project_membership(
        self,
        *,
        project_id: str,
        user_id: str,
        role: str = "viewer",
        commit: bool = False,
    ) -> ProjectMember:
        normalized = ProjectRole.normalize(role) or ProjectRole.VIEWER
        project_role = normalized.value

        existing = await self._load_project_member(project_id, user_id)
        if existing is not None:
            if existing.role != project_role:
                existing.role = project_role
                if commit:
                    await self.db.commit()
                    await self.db.refresh(existing)
                else:
                    await self.db.flush()
            return existing

        membership = ProjectMember(project_id=project_id, user_id=user_id, role=project_role)
        self.db.add(membership)
        if not commit:
            await self.db.flush()
            return membership
        try:
            await self.db.commit()
        except IntegrityError:
            # A concurrent grant inserted the same (project_id, user_id) first.
            # This method is an idempotent upsert, so converge on the winning row
            # and apply the requested role instead of surfacing a 500.
            await self.db.rollback()
            winner = await self._load_project_member(project_id, user_id)
            if winner is None:
                raise
            if winner.role != project_role:
                winner.role = project_role
            membership = winner
            await self.db.commit()
        await self.db.refresh(membership)
        return membership

    async def grant_default_project_membership(
        self,
        *,
        org_id: str,
        user_id: str,
        role: str = "viewer",
    ) -> ProjectMember | None:
        project = await self.get_default_project(org_id)
        if project is None:
            result = await self.db.execute(
                select(Project)
                .where(Project.org_id == org_id, Project.archived_at.is_(None))
                .order_by(Project.created_at)
                .limit(1)
            )
            project = result.scalar_one_or_none()
        if project is None:
            return None
        project_role = default_project_role_for_org_role(role).value
        return await self.grant_project_membership(project_id=project.id, user_id=user_id, role=project_role)

    async def revoke_org_project_memberships(self, *, org_id: str, user_id: str) -> None:
        project_ids = select(Project.id).where(Project.org_id == org_id)
        await self.db.execute(
            delete(ProjectMember).where(
                ProjectMember.user_id == user_id,
                ProjectMember.project_id.in_(project_ids),
            )
        )

    async def list_project_members(self, project_id: str) -> list[ProjectMember]:
        result = await self.db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id))
        return list(result.scalars().all())

    async def list_project_members_page(
        self,
        project_id: str,
        *,
        limit: int,
        after_id: str | None = None,
    ) -> tuple[list[ProjectMember], bool]:
        query = select(ProjectMember).where(ProjectMember.project_id == project_id)
        query = apply_created_at_desc_cursor(query, ProjectMember, after_id).limit(limit + 1)
        result = await self.db.execute(query)
        rows = list(result.scalars().all())
        return rows[:limit], len(rows) > limit

    async def get_project_member_role(self, project_id: str, user_id: str) -> str | None:
        """The caller's explicit ProjectMember role for a project, or None if no row.

        Feeds JoySafeterAuthContext.project_role; capability is then derived via
        effective_project_capability. Org super-users normally have no row (None).
        """
        result = await self.db.execute(
            select(ProjectMember.role)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def revoke_project_membership(self, *, project_id: str, user_id: str, commit: bool = False) -> bool:
        result = await self.db.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if commit:
            await self.db.commit()
        return cast(CursorResult[Any], result).rowcount > 0

    async def user_has_project_access(
        self,
        *,
        project_id: str,
        user_id: str,
        org_role: str | JoySafeterRole,
    ) -> bool:
        if self.role_has_org_wide_project_access(org_role):
            return True
        result = await self.db.execute(
            select(ProjectMember.id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_accessible_projects(
        self,
        *,
        org_id: str,
        user_id: str,
        org_role: str | JoySafeterRole,
        include_archived: bool = False,
    ) -> list[Project]:
        conditions = [Project.org_id == org_id]
        if not include_archived:
            conditions.append(Project.archived_at.is_(None))
        if not self.role_has_org_wide_project_access(org_role):
            member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
            conditions.append(Project.id.in_(member_project_ids))
        result = await self.db.execute(select(Project).where(and_(*conditions)).order_by(Project.created_at))
        return list(result.scalars().all())

    async def list_accessible_projects_page(
        self,
        *,
        org_id: str,
        user_id: str,
        org_role: str | JoySafeterRole,
        include_archived: bool = False,
        limit: int,
        after_id: str | None = None,
    ) -> tuple[list[Project], bool]:
        conditions = [Project.org_id == org_id]
        if not include_archived:
            conditions.append(Project.archived_at.is_(None))
        if not self.role_has_org_wide_project_access(org_role):
            member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
            conditions.append(Project.id.in_(member_project_ids))
        query = select(Project).where(and_(*conditions))
        query = apply_created_at_desc_cursor(query, Project, after_id).limit(limit + 1)
        result = await self.db.execute(query)
        rows = list(result.scalars().all())
        return rows[:limit], len(rows) > limit

    async def get_accessible_project(
        self,
        *,
        project_id: str,
        org_id: str,
        user_id: str,
        org_role: str | JoySafeterRole,
        allow_archived: bool = True,
    ) -> Project | None:
        conditions = [Project.id == project_id, Project.org_id == org_id]
        if not allow_archived:
            conditions.append(Project.archived_at.is_(None))
        if not self.role_has_org_wide_project_access(org_role):
            member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
            conditions.append(Project.id.in_(member_project_ids))
        result = await self.db.execute(select(Project).where(and_(*conditions)).limit(1))
        return result.scalar_one_or_none()

    async def create_project(
        self,
        org_id: str,
        name: str,
        slug: str,
        is_default: bool = False,
        created_by_user_id: str | None = None,
    ) -> Project:
        project_name = self._validate_name(name)
        project_slug = self._validate_slug(slug)
        if await self._project_slug_exists(org_id, project_slug):
            raise self._slug_conflict_error(org_id, project_slug)

        project = Project(
            id=str(uuid.uuid4()),
            org_id=org_id,
            name=project_name,
            slug=project_slug,
            is_default=is_default,
        )
        self.db.add(project)
        if created_by_user_id is not None:
            await self.grant_project_membership(project_id=project.id, user_id=created_by_user_id, role="admin")
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if self._is_project_slug_integrity_error(exc):
                raise self._slug_conflict_error(org_id, project_slug) from None
            raise
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

    async def update_project(
        self,
        project_id: str,
        org_id: str,
        *,
        name: str | None = None,
        slug: str | None = None,
    ) -> Project:
        project = await self.get_project(project_id, org_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found for org {org_id}")
        if project.archived_at is not None:
            raise ResourceConflictError(
                code="PROJECT_ARCHIVED",
                message="Cannot update an archived project",
                data={"project_id": project_id, "organization_id": org_id},
                user_action="refresh",
            )

        if name is not None:
            project.name = self._validate_name(name)
        if slug is not None:
            project_slug = self._validate_slug(slug)
            if project_slug != project.slug and await self._project_slug_exists(
                org_id,
                project_slug,
                exclude_project_id=project_id,
            ):
                raise self._slug_conflict_error(org_id, project_slug)
            project.slug = project_slug

        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if slug is not None and self._is_project_slug_integrity_error(exc):
                raise self._slug_conflict_error(org_id, self._validate_slug(slug)) from None
            raise
        await self.db.refresh(project)
        return project

    async def _cleanup_sessions_for_archive(
        self,
        project_id: str,
        session_ids: Optional[list[uuid.UUID]] = None,
    ) -> None:
        if session_ids is None:
            result = await self.db.execute(
                select(JoySafeterSession.id).where(
                    JoySafeterSession.project_id == project_id,
                    JoySafeterSession.archived_at.is_(None),
                )
            )
            session_ids = list(result.scalars().all())
        if not session_ids:
            return

        sandbox_svc = SandboxService(self.db)

        for session_id in session_ids:
            sandbox = await sandbox_svc.find_by_session(session_id)
            if not sandbox or sandbox.status == "destroyed":
                continue

            expected_external_id = str(sandbox.external_id or "") or None
            destroy_relayed = await relay_sandbox_destroy_via_redis(
                sandbox.id,
                reason="project archived",
                boundary="project_service",
                operation="archive_project_destroy_sandbox",
                failure_code="PROJECT_ARCHIVE_REDIS_DESTROY_FAILED",
                failure_message="Redis sandbox destroy relay command failed",
                external_id=expected_external_id,
                data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
            )
            if not destroy_relayed:
                raise ServiceUnavailableError(
                    code="PROJECT_ARCHIVE_REDIS_DESTROY_FAILED",
                    message="Failed to destroy project session sandbox runtime.",
                    data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                )

            try:
                destroyed = await sandbox_svc.mark_destroyed_after_runtime_ack(
                    sandbox.id,
                    sandbox.status,
                    expected_external_id,
                )
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="project_service",
                    code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
                    message="Failed to mark sandbox destroyed during project archive",
                    operation="archive_project_mark_sandbox_destroyed",
                    error=exc,
                    data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                    source="api",
                )
                raise ServiceUnavailableError(
                    code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
                    message="Project could not be archived because sandbox state sync failed.",
                    data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                    source="api",
                    retryable=True,
                    user_action="retry",
                ) from None
            if not destroyed:
                log_boundary_failure(
                    logger,
                    boundary="project_service",
                    code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
                    message="Failed to mark sandbox destroyed during project archive",
                    operation="archive_project_mark_sandbox_destroyed",
                    data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                    source="api",
                )
                raise ServiceUnavailableError(
                    code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
                    message="Project could not be archived because sandbox state sync failed.",
                    data={"project_id": project_id, "session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                    source="api",
                    retryable=True,
                    user_action="retry",
                )

    async def _count_active_tasks_for_sessions(self, session_ids: list[uuid.UUID]) -> int:
        if not session_ids:
            return 0
        result = await self.db.execute(
            select(JoySafeterTask.id).where(
                and_(
                    JoySafeterTask.chat_session_id.in_(session_ids),
                    JoySafeterTask.status.notin_(TERMINAL_TASK_STATUSES),
                )
            )
        )
        return len(result.scalars().all())

    async def archive_project(self, project_id: str, org_id: str) -> None:
        result = await self.db.execute(select(Project).where(and_(Project.id == project_id, Project.org_id == org_id)))
        project = result.scalar_one_or_none()
        if project is None:
            raise ValueError(f"Project {project_id} not found for org {org_id}")
        if project.is_default:
            raise InvalidRequestError(
                code="PROJECT_DEFAULT_ARCHIVE_FORBIDDEN",
                message="Cannot archive the default project",
                data={"project_id": project_id, "organization_id": org_id},
                user_action="fix_input",
            )

        active_tasks = await JoySafeterTaskService(self.db).count_active_tasks_for_project(project_id)
        if active_tasks > 0:
            raise ResourceConflictError(
                code="PROJECT_ACTIVE_TASKS",
                message="Project has active tasks. Stop or wait for them before archiving.",
                data={"project_id": project_id, "active": active_tasks},
                retryable=True,
                user_action="retry",
            )

        archived_at = utc_now()
        session_ids_result = await self.db.execute(
            select(JoySafeterSession.id).where(
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.archived_at.is_(None),
            )
        )
        session_ids = list(session_ids_result.scalars().all())
        if await self._count_active_tasks_for_sessions(session_ids) > 0:
            raise ResourceConflictError(
                code="PROJECT_ACTIVE_TASKS",
                message="Project has active tasks. Stop or wait for them before archiving.",
                data={"project_id": project_id, "active": 1},
                retryable=True,
                user_action="retry",
            )

        await self._cleanup_sessions_for_archive(project_id, session_ids)

        active_task_exists = (
            select(JoySafeterTask.id)
            .where(
                and_(
                    JoySafeterTask.chat_session_id == JoySafeterSession.id,
                    JoySafeterTask.status.notin_(TERMINAL_TASK_STATUSES),
                )
            )
            .exists()
        )
        archive_result = await self.db.execute(
            update(JoySafeterSession)
            .where(
                and_(
                    JoySafeterSession.id.in_(session_ids),
                    JoySafeterSession.archived_at.is_(None),
                    ~active_task_exists,
                )
            )
            .values(archived_at=archived_at, status="terminated")
        )
        if cast(CursorResult[Any], archive_result).rowcount != len(session_ids):
            await self.db.rollback()
            raise ResourceConflictError(
                code="PROJECT_ACTIVE_TASKS",
                message="Project has active tasks. Stop or wait for them before archiving.",
                data={"project_id": project_id, "active": 1},
                retryable=True,
                user_action="retry",
            )

        await JoySafeterScheduleService(self.db).pause_for_project_archive(project_id)
        project.archived_at = archived_at
        await self.db.commit()

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
        slug_result = await self.db.execute(
            select(Project.id).where(and_(Project.org_id == org_id, Project.slug == slug))
        )
        if slug_result.scalar_one_or_none() is not None:
            slug = f"default-{uuid.uuid4().hex[:8]}"
        return await self.create_project(org_id, "Default", slug, is_default=True)
