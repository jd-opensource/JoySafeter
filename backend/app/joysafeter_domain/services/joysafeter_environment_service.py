import logging
import uuid
from typing import Any, Optional

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAuditEntry
from app.joysafeter_domain.credentials.bindings import (
    EgressInjectKind,
    EgressInjectPolicy,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
)
from app.joysafeter_domain.credentials.dependencies import CredentialImpact, DependencyDisposition
from app.joysafeter_domain.credentials.references import CredentialReferenceCodec
from app.joysafeter_domain.credentials.types import (
    CredentialFieldName,
    CredentialUsage,
    NormalizedEndpoint,
    ProjectId,
)
from app.joysafeter_domain.credentials.types import CredentialId as DomainCredentialId
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    UpdateEnvironmentRequest,
)
from app.joysafeter_shared.ids import EnvironmentId, TaskId, registered_entity_id_prefix
from app.joysafeter_shared.utils.datetime import utc_now

logger = logging.getLogger(__name__)
_IMPACT_SURFACE_PROJECT_ID = ProjectId("environment-impact-surface")
_REFERENCE_CODEC = CredentialReferenceCodec()


def _credential_binding_surfaces(config: dict[str, Any] | None) -> dict[CredentialUsage, frozenset[object]]:
    decoded = _REFERENCE_CODEC.decode_environment(config or {})
    direct = frozenset(
        EnvironmentInjectionBinding(
            project_id=_IMPACT_SURFACE_PROJECT_ID,
            credential_id=DomainCredentialId(str(credential_id)),
        )
        for credential_id in decoded.direct_credential_ids
    )
    egress_bindings = {
        HttpEgressBinding(
            project_id=_IMPACT_SURFACE_PROJECT_ID,
            credential_id=reference.credential_id,
            endpoint=NormalizedEndpoint(reference.endpoint),
            inject=EgressInjectPolicy(
                kind=EgressInjectKind(reference.inject_kind),
                credential_field=CredentialFieldName(reference.credential_field),
                header=reference.header,
                cookie_name=reference.cookie_name,
            ),
        )
        for reference in decoded.http_egress
    }
    return {
        CredentialUsage.ENVIRONMENT_INJECTION: direct,
        CredentialUsage.HTTP_EGRESS: frozenset(egress_bindings),
    }


def _changed_credential_binding_usages(
    old_config: dict[str, Any] | None,
    new_config: dict[str, Any] | None,
) -> tuple[CredentialUsage, ...]:
    old_surfaces = _credential_binding_surfaces(old_config)
    new_surfaces = _credential_binding_surfaces(new_config)
    return tuple(usage for usage in CredentialUsage if old_surfaces.get(usage) != new_surfaces.get(usage))


def _environment_ref_matches(ref: object, env_name: str, env_id: EnvironmentId) -> bool:
    if ref is None:
        return False
    normalized = str(ref).strip()
    return normalized == env_name or normalized == str(env_id)


class EnvironmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_environment(
        self,
        req: CreateEnvironmentRequest,
        project_id: Optional[str] = None,
        *,
        commit: bool = True,
    ) -> JoySafeterEnvironment:
        purge_conditions: list[ColumnElement[bool]] = [
            JoySafeterEnvironment.name == req.name,
            JoySafeterEnvironment.deleted_at.is_not(None),
        ]
        if project_id is not None:
            purge_conditions.append(JoySafeterEnvironment.project_id == project_id)
        else:
            purge_conditions.append(JoySafeterEnvironment.project_id.is_(None))
        await self.db.execute(delete(JoySafeterEnvironment).where(and_(*purge_conditions)))
        kwargs = dict(
            name=req.name,
            description=req.description,
            metadata_=req.metadata,
            # ``mode="json"`` serializes typed CredentialId refs (egress
            # service_credential_id / secret_refs) to plain strings for JSONB.
            config=_REFERENCE_CODEC.encode_environment(req.config.model_dump(mode="json"), version="v1"),
        )
        if project_id is not None:
            kwargs["project_id"] = project_id
        env = JoySafeterEnvironment(**kwargs)
        self.db.add(env)
        if commit:
            await self.db.commit()
            await self.db.refresh(env)
        else:
            await self.db.flush()
        return env

    async def commit_update(
        self,
        env: JoySafeterEnvironment,
        *,
        project_id: str,
        old_config: dict[str, Any] | None,
        new_config: dict[str, Any] | None,
    ) -> None:
        application = compose_credential_application(self.db, auto_commit=False)
        changed_usages = _changed_credential_binding_usages(old_config, new_config)
        if changed_usages:
            await application.uow.audit.append(
                CredentialAuditEntry(
                    action="environment.credentials.updated",
                    project_id=project_id,
                    target_type="environment",
                    target_id=str(env.id),
                    details={"environment_id": str(env.id)},
                )
            )
        for usage in changed_usages:
            await application.uow.impacts.mark_pending(
                CredentialImpact(
                    usage=usage,
                    source="environment",
                    source_id=str(env.id),
                    reason="environment.updated",
                    project_id=ProjectId(project_id),
                    affected_sandbox_ids=frozenset(),
                    affected_session_ids=frozenset(),
                    dispositions=frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY}),
                )
            )
        await application.uow.commit()
        await self.db.refresh(env)
        if changed_usages:
            try:
                await application.uow.impacts.nudge_after_commit()
            except Exception:
                logger.warning("environment credential impact nudge failed after commit", exc_info=True)

    async def get_environment(
        self, env_id: EnvironmentId, project_id: Optional[str] = None
    ) -> Optional[JoySafeterEnvironment]:
        conditions = [
            JoySafeterEnvironment.id == env_id,
            JoySafeterEnvironment.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterEnvironment.project_id == project_id)
        result = await self.db.execute(select(JoySafeterEnvironment).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def lock_environment(
        self, env_id: EnvironmentId, project_id: Optional[str] = None
    ) -> Optional[JoySafeterEnvironment]:
        conditions = [
            JoySafeterEnvironment.id == env_id,
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

    async def get_environment_by_ref(
        self, ref: str, project_id: Optional[str] = None
    ) -> Optional[JoySafeterEnvironment]:
        """Resolve an ``env_<uuid>`` reference or environment name."""
        normalized = ref.strip()
        if not normalized:
            return None
        prefix = registered_entity_id_prefix(normalized)
        if prefix is not None:
            if prefix != EnvironmentId.prefix:
                return None
            try:
                env_id = EnvironmentId.from_public(normalized)
                return await self.get_environment(env_id, project_id=project_id)
            except (TypeError, ValueError):
                return None
        try:
            uuid.UUID(normalized)
        except ValueError:
            pass
        else:
            return None
        # Fall back to name lookup
        conditions = [
            JoySafeterEnvironment.name == normalized,
            JoySafeterEnvironment.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterEnvironment.project_id == project_id)
        result = await self.db.execute(select(JoySafeterEnvironment).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_environments(
        self,
        limit: int = 20,
        after_id: Optional[EnvironmentId] = None,
        include_archived: bool = False,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterEnvironment], bool]:
        q = select(JoySafeterEnvironment).where(JoySafeterEnvironment.deleted_at.is_(None))
        if not include_archived:
            q = q.where(JoySafeterEnvironment.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterEnvironment.project_id == project_id)
        q = apply_created_at_desc_cursor(q, JoySafeterEnvironment, after_id).limit(limit + 1)
        result = await self.db.execute(q)
        envs = list(result.scalars().all())
        has_more = len(envs) > limit
        return envs[:limit], has_more

    async def update_environment(
        self,
        env_id: EnvironmentId,
        req: UpdateEnvironmentRequest,
        project_id: Optional[str] = None,
        *,
        commit: bool = True,
    ) -> Optional[JoySafeterEnvironment]:
        env = await self.lock_environment(env_id, project_id=project_id)
        if not env:
            return None
        next_config = (
            _REFERENCE_CODEC.encode_environment(req.config.model_dump(mode="json"), version="v1")
            if req.config is not None
            else None
        )
        name_changed = req.name is not None and req.name != env.name
        config_changed = next_config is not None and next_config != (env.config or {})
        if name_changed or config_changed:
            active_dependency = await self.active_task_environment_dependency(env.name, env.id, project_id=project_id)
            if active_dependency:
                task_id, source = active_dependency
                action = "config" if config_changed else "name"
                raise ValueError(
                    f"Environment is required by active task '{task_id}' via {source}. "
                    f"Stop or wait for the task before updating {action}."
                )
        if name_changed:
            agent_name = await self.environment_is_referenced_by_agent(env.name, env.id, project_id=project_id)
            if agent_name:
                raise ValueError(f"Environment is referenced by agent '{agent_name}'.")
            blocking_trigger = await self.environment_is_referenced_by_trigger(env.name, env.id, project_id=project_id)
            if blocking_trigger:
                raise ValueError(f"Environment is referenced by cron trigger '{blocking_trigger}'.")
            if await self.environment_is_referenced_by_sessions(env.name, env.id, project_id=project_id):
                raise ValueError("Environment is referenced by one or more active sessions.")
        if req.name is not None:
            env.name = req.name
        if req.description is not None:
            env.description = req.description
        if req.metadata is not None:
            env.metadata_ = req.metadata
        if next_config is not None:
            env.config = next_config
        env.updated_at = utc_now()
        if commit:
            await self.db.commit()
            await self.db.refresh(env)
        else:
            await self.db.flush()
        return env

    async def delete_environment(self, env_id: EnvironmentId, project_id: Optional[str] = None) -> bool:
        env = await self.lock_environment(env_id, project_id=project_id)
        if not env:
            return False
        active_dependency = await self.active_task_environment_dependency(env.name, env.id, project_id=project_id)
        if active_dependency:
            task_id, source = active_dependency
            raise ValueError(
                f"Environment is required by active task '{task_id}' via {source}. "
                "Stop or wait for the task before deleting."
            )
        agent_name = await self.environment_is_referenced_by_agent(env.name, env.id, project_id=project_id)
        if agent_name:
            raise ValueError(f"Environment is referenced by agent '{agent_name}'.")
        blocking_trigger = await self.environment_is_referenced_by_trigger(env.name, env.id, project_id=project_id)
        if blocking_trigger:
            raise ValueError(f"Environment is referenced by cron trigger '{blocking_trigger}'.")
        if await self.environment_is_referenced_by_sessions(env.name, env.id, project_id=project_id):
            raise ValueError("Environment is referenced by one or more active sessions.")
        env.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_environment(self, env_id: EnvironmentId, project_id: Optional[str] = None) -> bool:
        env = await self.lock_environment(env_id, project_id=project_id)
        if not env:
            return False
        if env.archived_at:
            return True
        active_dependency = await self.active_task_environment_dependency(env.name, env.id, project_id=project_id)
        if active_dependency:
            task_id, source = active_dependency
            raise ValueError(
                f"Environment is required by active task '{task_id}' via {source}. "
                "Stop or wait for the task before archiving."
            )
        agent_name = await self.environment_is_referenced_by_agent(env.name, env.id, project_id=project_id)
        if agent_name:
            raise ValueError(f"Environment is referenced by agent '{agent_name}'.")
        blocking_trigger = await self.environment_is_referenced_by_trigger(env.name, env.id, project_id=project_id)
        if blocking_trigger:
            raise ValueError(f"Environment is referenced by cron trigger '{blocking_trigger}'.")
        if await self.environment_is_referenced_by_sessions(env.name, env.id, project_id=project_id):
            raise ValueError("Environment is referenced by one or more active sessions.")
        env.archived_at = utc_now()
        await self.db.commit()
        return True

    async def environment_is_referenced_by_sessions(
        self,
        env_name: str,
        env_id: EnvironmentId,
        project_id: Optional[str] = None,
    ) -> bool:
        """Check active sessions for the environment name or ``env_<uuid>`` ref."""
        env_prefixed = str(env_id)
        conditions = [
            or_(
                JoySafeterSession.environment_ref == env_name,
                JoySafeterSession.environment_ref == env_prefixed,
            ),
            JoySafeterSession.archived_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterSession.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSession.id).where(and_(*conditions)).limit(1))
        return result.scalar_one_or_none() is not None

    async def environment_is_referenced_by_agent(
        self,
        env_name: str,
        env_id: EnvironmentId,
        project_id: Optional[str] = None,
    ) -> Optional[str]:
        conditions: list[ColumnElement[bool]] = [
            JoySafeterAgent.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterAgent.name, JoySafeterAgent.environment_ref).where(and_(*conditions))
        )
        for agent_name, environment_ref in result.all():
            if _environment_ref_matches(environment_ref, env_name, env_id):
                return str(agent_name)
        return None

    async def environment_is_referenced_by_trigger(
        self,
        env_name: str,
        env_id: EnvironmentId,
        project_id: Optional[str] = None,
    ) -> Optional[str]:
        # Scope to type='cron' so the "referenced by cron trigger '<name>'" message
        # stays accurate (a webhook trigger does not pin a runtime environment the
        # same way a scheduled cron trigger does).
        conditions: list[ColumnElement[bool]] = [
            JoySafeterTrigger.environment_ref.is_not(None),
            JoySafeterTrigger.type == "cron",
            JoySafeterTrigger.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterTrigger.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterTrigger.name, JoySafeterTrigger.environment_ref).where(and_(*conditions))
        )
        for trigger_name, environment_ref in result.all():
            if _environment_ref_matches(environment_ref, env_name, env_id):
                return str(trigger_name)
        return None

    async def active_task_environment_dependency(
        self,
        env_name: str,
        env_id: EnvironmentId,
        project_id: Optional[str] = None,
    ) -> Optional[tuple[TaskId, str]]:
        terminal_values = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]
        conditions: list[ColumnElement[bool]] = [JoySafeterTask.status.notin_(terminal_values)]
        if project_id is not None:
            conditions.append(JoySafeterTask.project_id == project_id)
        result = await self.db.execute(
            select(
                JoySafeterTask.id,
                JoySafeterAgent.environment_ref,
                JoySafeterSession.environment_ref,
            )
            .join(JoySafeterAgent, JoySafeterTask.agent_id == JoySafeterAgent.id)
            .outerjoin(JoySafeterSession, JoySafeterTask.chat_session_id == JoySafeterSession.id)
            .where(and_(*conditions))
            .order_by(JoySafeterTask.created_at.asc())
        )
        for task_id, agent_env_ref, session_env_ref in result.all():
            if _environment_ref_matches(session_env_ref, env_name, env_id):
                return task_id, "session environment_ref"
            if _environment_ref_matches(agent_env_ref, env_name, env_id):
                return task_id, "agent environment_ref"
        return None
