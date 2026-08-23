from __future__ import annotations

import copy

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.ports import (
    CredentialSnapshotSession,
    CredentialSnapshotSource,
)
from app.joysafeter_domain.credentials.references import (
    build_agent_execution_snapshot,
    build_environment_execution_snapshot,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterSessionCredentialGroup
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, SessionStatus
from app.joysafeter_shared.common.app_errors import (
    NotFoundError,
    RequestValidationAppError,
    ResourceConflictError,
)
from app.joysafeter_shared.ids import CredentialGroupId as SqlCredentialGroupId
from app.joysafeter_shared.ids import EnvironmentId
from app.joysafeter_shared.utils.datetime import utc_now


class SqlAlchemyCredentialSnapshotSourceAdapter:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def load(
        self,
        command: object,
        *,
        for_update: bool = False,
    ) -> CredentialSnapshotSource:
        agent_query = (
            select(JoySafeterAgent)
            .where(
                JoySafeterAgent.id == command.agent_id,
                JoySafeterAgent.project_id == command.project_id,
                JoySafeterAgent.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if for_update:
            agent_query = agent_query.with_for_update()
        agent = (await self._db.execute(agent_query)).scalar_one_or_none()
        if agent is None:
            raise NotFoundError(
                code="SESSION_AGENT_NOT_FOUND",
                message="Agent not found",
                data={"agent_id": str(command.agent_id)},
                user_action="refresh",
            )
        if agent.archived_at is not None:
            raise ResourceConflictError(
                code="AGENT_ARCHIVED",
                message="Agent is archived and cannot create new sessions.",
                data={"agent_id": str(agent.id)},
                user_action="refresh",
            )

        version_row = None
        if command.pinned_agent_version is not None:
            version_query = (
                select(JoySafeterAgentVersion)
                .where(
                    JoySafeterAgentVersion.agent_id == agent.id,
                    JoySafeterAgentVersion.version == command.pinned_agent_version,
                )
                .execution_options(populate_existing=True)
            )
            if for_update:
                version_query = version_query.with_for_update()
            version_row = (await self._db.execute(version_query)).scalar_one_or_none()
            if version_row is None:
                raise NotFoundError(
                    code="SESSION_AGENT_VERSION_NOT_FOUND",
                    message=f"Agent version {command.pinned_agent_version} not found",
                    data={"agent_id": str(agent.id), "version": command.pinned_agent_version},
                    user_action="refresh",
                )
            snapshot = copy.deepcopy(version_row.snapshot)
            agent_version = version_row.version
        else:
            snapshot = build_agent_execution_snapshot(agent)
            agent_version = agent.version

        environment_ref = command.environment_ref or snapshot.get("environment_ref") or agent.environment_ref or None
        environment = await self._load_environment(
            environment_ref,
            project_id=command.project_id,
            caller=command.caller,
            for_update=for_update,
        )
        environment_ref = str(environment.id) if environment is not None else None
        snapshot["environment_ref"] = environment_ref
        environment_snapshot = build_environment_execution_snapshot(
            environment,
            environment_ref=environment_ref,
        )
        if environment_snapshot is not None:
            snapshot["environment"] = environment_snapshot

        overlay = copy.deepcopy(dict(command.environment_config_overlay or {}))
        mount_resources = tuple(command.environment_mount_resources or ())
        if overlay or mount_resources:
            frozen_environment = dict(snapshot.get("environment") or {})
            frozen_config = dict(frozen_environment.get("config") or {})
            frozen_config.update(overlay)
            if mount_resources:
                frozen_config["mount_resources"] = list(frozen_config.get("mount_resources") or []) + [
                    copy.deepcopy(dict(resource)) for resource in mount_resources
                ]
            frozen_environment["config"] = frozen_config
            snapshot["environment"] = frozen_environment

        return CredentialSnapshotSource(
            agent_id=agent.id,
            agent_name=str(snapshot.get("name") or agent.name),
            agent_version=agent_version,
            snapshot=snapshot,
            environment_ref=environment_ref,
            source_version_id=version_row.id if version_row is not None else None,
            environment_id=environment.id if environment is not None else None,
        )

    async def _load_environment(
        self,
        environment_ref: str | None,
        *,
        project_id: str | None,
        caller: str,
        for_update: bool,
    ) -> JoySafeterEnvironment | None:
        normalized = (environment_ref or "").strip()
        if not normalized:
            return None
        conditions = [
            JoySafeterEnvironment.project_id == project_id,
            JoySafeterEnvironment.deleted_at.is_(None),
        ]
        try:
            environment_id = EnvironmentId.from_public(normalized)
        except (TypeError, ValueError):
            conditions.append(JoySafeterEnvironment.name == normalized)
        else:
            conditions.append(JoySafeterEnvironment.id == environment_id)
        query = select(JoySafeterEnvironment).where(and_(*conditions)).execution_options(populate_existing=True)
        if for_update:
            query = query.with_for_update()
        environment = (await self._db.execute(query)).scalar_one_or_none()
        if environment is None:
            code = "TASK_ENVIRONMENT_NOT_FOUND" if caller == "task" else "SESSION_ENVIRONMENT_NOT_FOUND"
            raise RequestValidationAppError(
                code=code,
                message=f"Environment not found: {normalized}",
                data={"environment_ref": normalized},
                user_action="fix_input",
            )
        if environment.archived_at is not None:
            raise ResourceConflictError(
                code="ENVIRONMENT_ARCHIVED",
                message=f"Environment is archived: {normalized}",
                data={"environment_ref": normalized, "environment_id": str(environment.id)},
                user_action="refresh",
            )
        return environment


class SqlAlchemyCredentialSessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, request: CredentialSnapshotSession) -> JoySafeterSession:
        session = JoySafeterSession(
            agent_id=request.agent_id,
            project_id=request.project_id,
            title=request.title,
            status=SessionStatus.IDLE.value,
            metadata_=dict(request.metadata),
            environment_ref=request.environment_ref,
            agent_version=request.agent_version,
            agent_snapshot=dict(request.agent_snapshot),
            updated_at=utc_now(),
        )
        self._db.add(session)
        await self._db.flush()
        for group_id in request.credential_group_ids:
            self._db.add(
                JoySafeterSessionCredentialGroup(
                    session_id=session.id,
                    credential_group_id=SqlCredentialGroupId.from_public(str(group_id)),
                )
            )
        await self._db.flush()
        return session

    async def refresh(self, session: JoySafeterSession) -> None:
        await self._db.refresh(session)
