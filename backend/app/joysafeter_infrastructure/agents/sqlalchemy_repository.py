from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence, cast

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.agents.ports import AgentNameConflictError
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterSessionMemoryStore
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.repositories.joysafeter_skill_version import SkillVersionRepository
from app.joysafeter_shared.ids import (
    AgentId,
    AgentVersionId,
    EnvironmentId,
    OrganizationId,
    ProjectId,
    SessionId,
    SkillId,
)

_TERMINAL_TASK_STATUSES = [status.value for status in JOYSAFETER_TERMINAL_STATUSES]


def translate_agent_integrity_error(exc: IntegrityError) -> None:
    message = str(exc.orig or exc).lower()
    if (
        "uq_joysafeter_agents_project_name" in message
        or "uq_joysafeter_agents_global_name" in message
        or ("joysafeter_agents" in message and "name" in message and "unique" in message)
    ):
        raise AgentNameConflictError from exc


class SqlAlchemyAgentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, agent: JoySafeterAgent) -> None:
        self.db.add(agent)

    async def flush(self) -> None:
        try:
            await self.db.flush()
        except IntegrityError as exc:
            translate_agent_integrity_error(exc)
            raise

    async def refresh(self, instance: Any) -> None:
        await self.db.refresh(instance)

    def _conditions(self, agent_id: AgentId, project_id: ProjectId | None) -> list[Any]:
        conditions = [JoySafeterAgent.id == agent_id, JoySafeterAgent.deleted_at.is_(None)]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        return conditions

    async def get(self, agent_id: AgentId, project_id: ProjectId | None = None) -> Optional[JoySafeterAgent]:
        result = await self.db.execute(select(JoySafeterAgent).where(and_(*self._conditions(agent_id, project_id))))
        return result.scalar_one_or_none()

    async def lock(self, agent_id: AgentId, project_id: ProjectId | None = None) -> Optional[JoySafeterAgent]:
        result = await self.db.execute(
            select(JoySafeterAgent)
            .where(and_(*self._conditions(agent_id, project_id)))
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, project_id: ProjectId | None = None) -> Optional[JoySafeterAgent]:
        conditions = [JoySafeterAgent.name == name, JoySafeterAgent.deleted_at.is_(None)]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(select(JoySafeterAgent).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list(
        self,
        limit: int = 20,
        after_id: Optional[AgentId] = None,
        include_archived: bool = False,
        project_id: ProjectId | None = None,
    ) -> tuple[list[JoySafeterAgent], bool]:
        query = select(JoySafeterAgent).where(JoySafeterAgent.deleted_at.is_(None))
        if not include_archived:
            query = query.where(JoySafeterAgent.archived_at.is_(None))
        if project_id is not None:
            query = query.where(JoySafeterAgent.project_id == project_id)
        query = apply_created_at_desc_cursor(query, JoySafeterAgent, after_id).limit(limit + 1)
        result = await self.db.execute(query)
        agents = list(result.scalars().all())
        return agents[:limit], len(agents) > limit

    async def lock_environment(
        self, environment_id: EnvironmentId, project_id: ProjectId | None = None
    ) -> Optional[JoySafeterEnvironment]:
        conditions: list[Any] = [
            JoySafeterEnvironment.id == environment_id,
            JoySafeterEnvironment.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterEnvironment.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterEnvironment)
            .where(and_(*conditions))
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def skills_by_ids(self, skill_ids: Sequence[SkillId]) -> dict[SkillId, JoySafeterSkill]:
        result = await self.db.execute(select(JoySafeterSkill).where(JoySafeterSkill.id.in_(skill_ids)))
        return {skill.id: skill for skill in result.scalars().all()}

    async def project_org_ids(self, project_ids: Sequence[ProjectId]) -> dict[ProjectId, OrganizationId]:
        result = await self.db.execute(select(Project.id, Project.org_id).where(Project.id.in_(project_ids)))
        return {row.id: row.org_id for row in result.all()}

    async def skill_version_strings_by_ids(self, version_ids: Sequence[Any]) -> dict[Any, str]:
        return await SkillVersionRepository(self.db).version_strings_by_ids(list(version_ids))

    async def latest_skill_versions(self, skill_ids: Sequence[SkillId]) -> dict[SkillId, str]:
        return await SkillVersionRepository(self.db).latest_version_map(list(skill_ids))

    async def get_skill_version(self, skill_id: SkillId, version: str) -> Any | None:
        return await SkillVersionRepository(self.db).get_by_version(skill_id, version)

    async def save_version(
        self,
        version_id: AgentVersionId,
        agent: JoySafeterAgent,
        snapshot: dict[str, Any],
    ) -> None:
        self.db.add(
            JoySafeterAgentVersion(
                id=version_id,
                agent_id=agent.id,
                version=agent.version,
                snapshot=snapshot,
            )
        )
        await self.db.flush()

    async def count_active_tasks(self, agent_id: AgentId, project_id: ProjectId | None = None) -> int:
        if project_id is not None and not await self.get(agent_id, project_id=project_id):
            return 0
        result = await self.db.execute(
            select(func.count())
            .select_from(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.agent_id == agent_id,
                    JoySafeterTask.status.notin_(_TERMINAL_TASK_STATUSES),
                )
            )
        )
        return cast(int, result.scalar() or 0)

    async def list_active_tasks(self, agent_id: AgentId, project_id: ProjectId | None = None) -> list[JoySafeterTask]:
        if project_id is not None and not await self.get(agent_id, project_id=project_id):
            return []
        result = await self.db.execute(
            select(JoySafeterTask).where(
                and_(
                    JoySafeterTask.agent_id == agent_id,
                    JoySafeterTask.status.in_(["pending", "scheduling", "running"]),
                )
            )
        )
        return list(result.scalars().all())

    async def list_non_archived_session_ids(self, agent_id: AgentId) -> list[SessionId]:
        result = await self.db.execute(
            select(JoySafeterSession.id).where(
                and_(JoySafeterSession.agent_id == agent_id, JoySafeterSession.archived_at.is_(None))
            )
        )
        return list(result.scalars().all())

    async def archive_sessions_if_no_active_tasks(self, session_ids: list[SessionId], archived_at: datetime) -> bool:
        if not session_ids:
            return True
        active_task_exists = (
            select(JoySafeterTask.id)
            .where(
                and_(
                    JoySafeterTask.chat_session_id == JoySafeterSession.id,
                    JoySafeterTask.status.notin_(_TERMINAL_TASK_STATUSES),
                )
            )
            .exists()
        )
        result = await self.db.execute(
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
        return cast(Any, result).rowcount == len(session_ids)

    async def hard_delete_owned_rows(self, agent_id: AgentId) -> None:
        session_ids = list(
            (
                await self.db.execute(select(JoySafeterSession.id).where(JoySafeterSession.agent_id == agent_id))
            ).scalars()
        )
        if session_ids:
            await self.db.execute(
                delete(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id.in_(session_ids))
            )
            await self.db.execute(delete(JoySafeterTask).where(JoySafeterTask.chat_session_id.in_(session_ids)))
            await self.db.execute(
                delete(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id.in_(session_ids))
            )
            await self.db.execute(delete(JoySafeterSession).where(JoySafeterSession.agent_id == agent_id))
        await self.db.execute(delete(JoySafeterTask).where(JoySafeterTask.agent_id == agent_id))
        await self.db.execute(delete(JoySafeterTrigger).where(JoySafeterTrigger.agent_id == agent_id))
        await self.db.execute(delete(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id == agent_id))
        await self.db.execute(delete(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))

    async def list_versions(
        self,
        agent_id: AgentId,
        limit: int = 20,
        before_version: Optional[int] = None,
        project_id: ProjectId | None = None,
    ) -> tuple[list[JoySafeterAgentVersion], bool]:
        if project_id is not None and not await self.get(agent_id, project_id=project_id):
            return [], False
        query = select(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id == agent_id)
        if before_version is not None:
            query = query.where(JoySafeterAgentVersion.version < before_version)
        query = query.order_by(JoySafeterAgentVersion.version.desc()).limit(limit + 1)
        result = await self.db.execute(query)
        versions = list(result.scalars().all())
        return versions[:limit], len(versions) > limit

    async def get_version_snapshot(
        self, agent_id: AgentId, version: int, project_id: ProjectId | None = None
    ) -> Optional[dict]:
        if project_id is not None and not await self.get(agent_id, project_id=project_id):
            return None
        result = await self.db.execute(
            select(JoySafeterAgentVersion).where(
                and_(JoySafeterAgentVersion.agent_id == agent_id, JoySafeterAgentVersion.version == version)
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else row.snapshot

    async def count_delete_preview(
        self, agent_id: AgentId, project_id: ProjectId | None = None
    ) -> Optional[tuple[int, int, int, int]]:
        if not await self.get(agent_id, project_id=project_id):
            return None
        counts = []
        for model in (JoySafeterSession, JoySafeterTask, JoySafeterAgentVersion, JoySafeterTrigger):
            result = await self.db.execute(select(func.count()).select_from(model).where(model.agent_id == agent_id))
            counts.append(cast(int, result.scalar() or 0))
        return cast(tuple[int, int, int, int], tuple(counts))
