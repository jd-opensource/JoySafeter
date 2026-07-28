from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_shared.common.app_errors import NotFoundError, RequestValidationAppError, ResourceConflictError


class TriggerRuntimeGate:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_runnable_target(
        self,
        *,
        agent_id: uuid.UUID,
        project_id: Optional[str],
        environment_ref: Optional[str] = None,
    ) -> tuple[JoySafeterAgent, Optional[str]]:
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

        effective_environment_ref = environment_ref or agent.environment_ref
        if effective_environment_ref:
            env = await EnvironmentService(self.db).get_environment_by_ref(
                effective_environment_ref,
                project_id=project_id,
            )
            if env is None:
                raise RequestValidationAppError(
                    code="TRIGGER_ENVIRONMENT_NOT_FOUND",
                    message=f"Environment not found: {effective_environment_ref}",
                    data={"environment_ref": effective_environment_ref},
                    user_action="fix_input",
                )
            if env.archived_at is not None:
                raise ResourceConflictError(
                    code="ENVIRONMENT_ARCHIVED",
                    message=f"Environment is archived: {effective_environment_ref}",
                    data={"environment_ref": effective_environment_ref, "environment_id": str(env.id)},
                    user_action="refresh",
                )
        return agent, effective_environment_ref

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
    def effective_environment_ref_expr():
        agent_environment_ref = (
            select(JoySafeterAgent.environment_ref)
            .where(JoySafeterAgent.id == JoySafeterTrigger.agent_id)
            .correlate(JoySafeterTrigger)
            .scalar_subquery()
        )
        trigger_environment_ref = func.nullif(func.trim(JoySafeterTrigger.environment_ref), "")
        inherited_environment_ref = func.nullif(func.trim(agent_environment_ref), "")
        return func.coalesce(trigger_environment_ref, inherited_environment_ref)

    @staticmethod
    def live_environment_filter():
        environment_ref = TriggerRuntimeGate.effective_environment_ref_expr()
        environment_id = cast(JoySafeterEnvironment.id, String)
        prefixed_environment_id = literal("env_") + environment_id
        return or_(
            environment_ref.is_(None),
            select(JoySafeterEnvironment.id)
            .where(
                JoySafeterEnvironment.deleted_at.is_(None),
                JoySafeterEnvironment.archived_at.is_(None),
                or_(
                    JoySafeterTrigger.project_id.is_(None),
                    JoySafeterEnvironment.project_id == JoySafeterTrigger.project_id,
                ),
                or_(
                    JoySafeterEnvironment.name == environment_ref,
                    environment_id == environment_ref,
                    prefixed_environment_id == environment_ref,
                ),
            )
            .correlate(JoySafeterTrigger)
            .exists(),
        )

    @staticmethod
    def claimable_lock_filter(stale_before: datetime):
        return or_(JoySafeterTrigger.locked_at.is_(None), JoySafeterTrigger.locked_at < stale_before)

    async def project_triggers_paused(self, project_id: Optional[str]) -> bool:
        if project_id is None:
            return False
        result = await self.db.execute(select(Project.triggers_paused).where(Project.id == project_id))
        return bool(result.scalar_one_or_none())

    async def project_trigger_block_reason(self, project_id: Optional[str]) -> Optional[str]:
        if project_id is None:
            return None
        result = await self.db.execute(select(Project.archived_at, Project.triggers_paused).where(Project.id == project_id))
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
                select(JoySafeterAgent.deleted_at, JoySafeterAgent.archived_at, JoySafeterAgent.environment_ref).where(
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
        environment_ref = trigger.environment_ref or agent_row.environment_ref
        if environment_ref:
            env = await EnvironmentService(self.db).get_environment_by_ref(
                environment_ref,
                project_id=trigger.project_id,
            )
            if env is None:
                return "environment is missing"
            if env.archived_at is not None:
                return "environment is archived"
        return None
