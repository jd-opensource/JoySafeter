from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_shared.common.app_errors import NotFoundError, RequestValidationAppError, ResourceConflictError
from app.joysafeter_shared.ids import AgentId, EnvironmentId, ProjectId, TriggerId


class TriggerRuntimeGate:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_runnable_target(
        self,
        *,
        agent_id: AgentId,
        project_id: ProjectId | None,
        environment_id: Optional[EnvironmentId] = None,
    ) -> tuple[JoySafeterAgent, Optional[EnvironmentId]]:
        """Resolve the agent and effective environment a trigger will run."""
        if project_id is not None:
            project_state = await self.db.execute(select(Project.archived_at).where(Project.id == project_id))
            archived_at = project_state.scalar_one_or_none()
            if archived_at is not None:
                raise ResourceConflictError(
                    code="PROJECT_ARCHIVED",
                    message="Project is archived and cannot create new triggered runs.",
                    data={"project_id": project_id},
                    user_action="refresh",
                )
        conditions = [JoySafeterAgent.id == agent_id, JoySafeterAgent.deleted_at.is_(None)]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(select(JoySafeterAgent).where(*conditions))
        agent = result.scalar_one_or_none()
        if agent is None:
            raise NotFoundError(
                code="TRIGGER_AGENT_NOT_FOUND",
                message="Agent not found",
                data={"agent_id": str(agent_id)},
                user_action="refresh",
            )
        if agent.archived_at is not None:
            raise ResourceConflictError(
                code="AGENT_ARCHIVED",
                message="Agent is archived and cannot create new triggered runs.",
                data={"agent_id": str(agent_id)},
                user_action="refresh",
            )

        effective_environment_id = environment_id or agent.environment_id
        if effective_environment_id is not None:
            env = await EnvironmentService(self.db).get_environment(
                effective_environment_id,
                project_id=project_id,
            )
            if env is None:
                raise RequestValidationAppError(
                    code="TRIGGER_ENVIRONMENT_NOT_FOUND",
                    message=f"Environment not found: {effective_environment_id}",
                    data={"environment_id": str(effective_environment_id)},
                    user_action="fix_input",
                )
            if env.archived_at is not None:
                raise ResourceConflictError(
                    code="ENVIRONMENT_ARCHIVED",
                    message=f"Environment is archived: {effective_environment_id}",
                    data={"environment_id": str(env.id)},
                    user_action="refresh",
                )
        return agent, effective_environment_id

    @staticmethod
    def live_project_filter():
        return or_(
            JoySafeterTrigger.project_id.is_(None),
            select(Project.id)
            .where(
                Project.id == JoySafeterTrigger.project_id,
                Project.archived_at.is_(None),
                Project.triggers_paused.is_(False),
            )
            .exists(),
        )

    @staticmethod
    def live_agent_filter():
        return (
            select(JoySafeterAgent.id)
            .where(
                JoySafeterAgent.id == JoySafeterTrigger.agent_id,
                JoySafeterAgent.deleted_at.is_(None),
                JoySafeterAgent.archived_at.is_(None),
            )
            .exists()
        )

    @staticmethod
    def effective_environment_id_expr():
        agent_environment_id = (
            select(JoySafeterAgent.environment_id)
            .where(JoySafeterAgent.id == JoySafeterTrigger.agent_id)
            .correlate(JoySafeterTrigger)
            .scalar_subquery()
        )
        return func.coalesce(JoySafeterTrigger.environment_id, agent_environment_id)

    @staticmethod
    def live_environment_filter():
        environment_id = TriggerRuntimeGate.effective_environment_id_expr()
        return or_(
            environment_id.is_(None),
            select(JoySafeterEnvironment.id)
            .where(
                JoySafeterEnvironment.deleted_at.is_(None),
                JoySafeterEnvironment.archived_at.is_(None),
                or_(
                    JoySafeterTrigger.project_id.is_(None),
                    JoySafeterEnvironment.project_id == JoySafeterTrigger.project_id,
                ),
                JoySafeterEnvironment.id == environment_id,
            )
            .correlate(JoySafeterTrigger)
            .exists(),
        )

    @staticmethod
    def claimable_lock_filter(stale_before: datetime):
        return or_(JoySafeterTrigger.locked_at.is_(None), JoySafeterTrigger.locked_at < stale_before)

    @staticmethod
    def lock_stmt(trigger_id: TriggerId, project_id: ProjectId | None = None):
        """`SELECT ... FOR UPDATE` for a live (non-soft-deleted) trigger row."""
        conditions = [JoySafeterTrigger.id == trigger_id, JoySafeterTrigger.deleted_at.is_(None)]
        if project_id is not None:
            conditions.append(JoySafeterTrigger.project_id == project_id)
        return select(JoySafeterTrigger).where(*conditions).execution_options(populate_existing=True).with_for_update()

    @staticmethod
    def trigger_not_found_error(trigger_id: TriggerId) -> NotFoundError:
        return NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message="Trigger not found",
            data={"trigger_id": str(trigger_id)},
            user_action="refresh",
        )

    async def project_triggers_paused(self, project_id: ProjectId | None) -> bool:
        if project_id is None:
            return False
        result = await self.db.execute(select(Project.triggers_paused).where(Project.id == project_id))
        return bool(result.scalar_one_or_none())

    async def project_trigger_block_reason(self, project_id: ProjectId | None) -> Optional[str]:
        if project_id is None:
            return None
        result = await self.db.execute(
            select(Project.archived_at, Project.triggers_paused).where(Project.id == project_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        if row.archived_at is not None:
            return "project is archived"
        if row.triggers_paused:
            return "triggers are paused for this project"
        return None

    async def trigger_runtime_block_reason(self, trigger: JoySafeterTrigger) -> Optional[str]:
        project_reason = await self.project_trigger_block_reason(trigger.project_id)
        if project_reason is not None:
            return project_reason
        agent_row = (
            await self.db.execute(
                select(JoySafeterAgent.deleted_at, JoySafeterAgent.archived_at, JoySafeterAgent.environment_id).where(
                    JoySafeterAgent.id == trigger.agent_id
                )
            )
        ).one_or_none()
        if agent_row is None:
            return "agent is missing"
        if agent_row.deleted_at is not None:
            return "agent is deleted"
        if agent_row.archived_at is not None:
            return "agent is archived"
        environment_id = trigger.environment_id or agent_row.environment_id
        if environment_id is not None:
            env = await EnvironmentService(self.db).get_environment(
                environment_id,
                project_id=trigger.project_id,
            )
            if env is None:
                return "environment is missing"
            if env.archived_at is not None:
                return "environment is archived"
        return None
