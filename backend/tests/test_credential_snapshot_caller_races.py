from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_api.api.v1.sessions import create_session
from app.joysafeter_api.api.v1.tasks import create_task
from app.joysafeter_application.agents import compose_agent_application
from app.joysafeter_application.credentials.application_service import CredentialService
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.schemas.joysafeter_agent import JoySafeterCreateAgentRequest, JoySafeterEngineKind
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.schemas.joysafeter_environment import CreateEnvironmentRequest, EnvironmentConfig
from app.joysafeter_domain.schemas.joysafeter_session import CreateSessionRequest
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_infrastructure.credentials.snapshot_adapter import SqlAlchemyCredentialSnapshotSourceAdapter
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import CredentialId, EnvironmentId, OrganizationId, ProjectId, UserId


class _FakeRedis:
    def __init__(self) -> None:
        self.rpushed: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))


async def _project(db: AsyncSession) -> tuple[Project, JoySafeterAuthContext]:
    suffix = str(uuid.uuid4())
    organization = Organization(
        id=OrganizationId.new(),
        name=f"caller-race-org-{suffix}",
        slug=f"caller-race-org-{suffix}",
    )
    db.add(organization)
    await db.flush()
    project = Project(
        id=ProjectId.new(),
        org_id=organization.id,
        name=f"caller-race-project-{suffix}",
        slug=f"caller-race-project-{suffix}",
    )
    db.add(project)
    await db.commit()
    return project, JoySafeterAuthContext(
        user_id=UserId.new(),
        org_id=organization.id,
        project_id=project.id,
        role=JoySafeterRole.MEMBER,
    )


async def _credential(db: AsyncSession, project_id: ProjectId, *, kind: str = "model"):
    return await CredentialService(db, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind=kind,
            name=f"caller-race-credential-{uuid.uuid4()}",
            provider="anthropic" if kind == "model" else None,
            protocol="anthropic_messages" if kind == "model" else None,
            data={"API_KEY": "caller-race-secret"} if kind == "model" else {"TOKEN": "caller-race-secret"},
        ),
        project_id=project_id,
    )


async def _agent(
    db: AsyncSession,
    project_id: ProjectId,
    *,
    model_credential_id: CredentialId | None = None,
    environment_id: EnvironmentId | None = None,
):
    return await compose_agent_application(db).commands.create_agent(
        JoySafeterCreateAgentRequest(
            name=f"caller-race-agent-{uuid.uuid4()}",
            engine_kind=JoySafeterEngineKind.CLAUDE,
            model_credential_id=model_credential_id,
            environment_id=environment_id,
        ),
        project_id=project_id,
    )


async def _pause_locked_source(monkeypatch, locked: asyncio.Event, release: asyncio.Event) -> None:
    original = SqlAlchemyCredentialSnapshotSourceAdapter.load

    async def paused(self, command, *, for_update=False):
        source = await original(self, command, for_update=for_update)
        if for_update:
            locked.set()
            await release.wait()
        return source

    monkeypatch.setattr(SqlAlchemyCredentialSnapshotSourceAdapter, "load", paused)


@pytest.mark.asyncio
async def test_session_api_refreshes_retained_agent_credential_state(db_session, postgres_url) -> None:
    project, auth = await _project(db_session)
    first = await _credential(db_session, project.id)
    second = await _credential(db_session, project.id)
    agent = await _agent(db_session, project.id, model_credential_id=first.id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as caller_db, factory() as mutate_db:
            retained = await compose_agent_application(caller_db).queries.get_agent(
                agent.id,
                project_id=project.id,
            )
            assert retained is not None
            await mutate_db.execute(
                update(JoySafeterAgent)
                .where(JoySafeterAgent.id == agent.id)
                .values(
                    model_credential_id=second.id,
                    version=JoySafeterAgent.version + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await mutate_db.commit()

            response = await create_session(CreateSessionRequest(agent_id=agent.id), caller_db, auth)
            persisted = await caller_db.scalar(
                select(JoySafeterSession)
                .where(JoySafeterSession.id == response.id)
                .execution_options(populate_existing=True)
            )
            assert persisted is not None
            assert persisted.agent_snapshot["model_credential_id"] == str(second.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_api_refreshes_retained_environment_credential_state(
    db_session,
    postgres_url,
    monkeypatch,
) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    project, auth = await _project(db_session)
    first = await _credential(db_session, project.id, kind="service")
    second = await _credential(db_session, project.id, kind="service")
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(
            name=f"caller-race-env-{uuid.uuid4()}",
            config=EnvironmentConfig(environment_credential_ids=[first.id]),
        ),
        project_id=project.id,
    )
    agent = await _agent(db_session, project.id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as caller_db, factory() as mutate_db:
            retained = await EnvironmentService(caller_db).get_environment(environment.id, project_id=project.id)
            assert retained is not None
            await mutate_db.execute(
                update(JoySafeterEnvironment)
                .where(JoySafeterEnvironment.id == environment.id)
                .values(
                    config={"type": "cloud", "environment_credential_ids": [str(second.id)]},
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await mutate_db.commit()

            response = await create_task(
                JoySafeterCreateTaskRequest(
                    agent_id=agent.id,
                    prompt="retained environment race",
                    environment_id=environment.id,
                ),
                caller_db,
                auth,
            )
            task = await caller_db.scalar(select(JoySafeterTask).where(JoySafeterTask.id == response.id))
            assert task is not None and task.chat_session_id is not None
            session = await caller_db.scalar(
                select(JoySafeterSession)
                .where(JoySafeterSession.id == task.chat_session_id)
                .execution_options(populate_existing=True)
            )
            assert session is not None
            assert session.environment_id == environment.id
            assert session.agent_snapshot["environment_id"] == str(environment.id)
            assert session.agent_snapshot["environment"]["environment_id"] == str(environment.id)
            assert session.agent_snapshot["environment"]["config"]["environment_credential_ids"] == [str(second.id)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_archive_waits_then_archives_new_session(
    db_session,
    postgres_url,
    monkeypatch,
) -> None:
    project, auth = await _project(db_session)
    agent = await _agent(db_session, project.id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    locked, release = asyncio.Event(), asyncio.Event()
    await _pause_locked_source(monkeypatch, locked, release)
    try:
        async with factory() as caller_db, factory() as writer_db:
            create_future = asyncio.create_task(
                create_session(CreateSessionRequest(agent_id=agent.id), caller_db, auth)
            )
            await asyncio.wait_for(locked.wait(), timeout=2)
            archive_future = asyncio.create_task(
                compose_agent_application(writer_db).lifecycle.archive_agent_with_sessions(
                    agent.id,
                    project_id=project.id,
                )
            )
            await asyncio.sleep(0.1)
            assert not archive_future.done()
            release.set()
            response, (archived, archived_session_ids) = await asyncio.gather(create_future, archive_future)

            assert archived is True
            assert response.id in archived_session_ids
            archived_session = await writer_db.scalar(
                select(JoySafeterSession)
                .where(JoySafeterSession.id == response.id)
                .execution_options(populate_existing=True)
            )
            assert archived_session is not None and archived_session.archived_at is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_environment_archive_waits_then_rechecks_session_blocker(
    db_session,
    postgres_url,
    monkeypatch,
) -> None:
    project, auth = await _project(db_session)
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"caller-race-env-{uuid.uuid4()}"),
        project_id=project.id,
    )
    agent = await _agent(db_session, project.id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    locked, release = asyncio.Event(), asyncio.Event()
    await _pause_locked_source(monkeypatch, locked, release)
    try:
        async with factory() as caller_db, factory() as writer_db:
            create_future = asyncio.create_task(
                create_session(
                    CreateSessionRequest(agent_id=agent.id, environment_id=environment.id),
                    caller_db,
                    auth,
                )
            )
            await asyncio.wait_for(locked.wait(), timeout=2)
            archive_future = asyncio.create_task(
                EnvironmentService(writer_db).archive_environment(environment.id, project_id=project.id)
            )
            await asyncio.sleep(0.1)
            assert not archive_future.done()
            release.set()
            response = await create_future
            with pytest.raises(ValueError, match="active sessions"):
                await archive_future

            assert response.id is not None
            archived_at = await writer_db.scalar(
                select(JoySafeterEnvironment.archived_at).where(JoySafeterEnvironment.id == environment.id)
            )
            assert archived_at is None
            count = await writer_db.scalar(
                select(func.count()).select_from(JoySafeterSession).where(JoySafeterSession.id == response.id)
            )
            assert count == 1
    finally:
        await engine.dispose()
