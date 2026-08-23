import asyncio
import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_api.api.v1.agents import create_agent, update_agent
from app.joysafeter_application.agents.command_service import AgentCommandService
from app.joysafeter_domain.agents import AgentConfigurationPolicy
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
    McpServerConfig,
    McpToolsetTool,
)
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_infrastructure.agents import SqlAlchemyAgentRepository
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import CredentialId
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


@pytest.mark.asyncio
async def test_create_agent_rejects_missing_environment_ref(db_session):
    missing_ref = f"missing-env-{uuid.uuid4()}"
    req = JoySafeterCreateAgentRequest(
        name=f"env-ref-agent-{uuid.uuid4()}",
        engine_kind="claude",
        environment_ref=missing_ref,
    )

    with pytest.raises(AppError) as exc_info:
        await create_agent(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AGENT_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {missing_ref}",
        "data": {"environment_ref": missing_ref},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    count = (
        await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.name == req.name))
    ).scalar_one_or_none()
    assert count is None


@pytest.mark.asyncio
async def test_create_agent_rejects_archived_environment_ref(db_session):
    env = JoySafeterEnvironment(
        name=f"archived-env-{uuid.uuid4()}",
        description="",
        archived_at=utc_now(),
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    environment_id = env.id
    req = JoySafeterCreateAgentRequest(
        name=f"archived-env-agent-{uuid.uuid4()}",
        engine_kind="claude",
        environment_ref=str(environment_id),
    )

    with pytest.raises(AppError) as exc_info:
        await create_agent(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: {environment_id}",
        "data": {"environment_ref": str(environment_id), "environment_id": str(environment_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    row = (
        await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.name == req.name))
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_update_agent_rejects_missing_environment_ref_without_partial_update(db_session):
    agent = JoySafeterAgent(name=f"update-env-agent-{uuid.uuid4()}", version=1)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    agent_id = agent.id
    missing_ref = f"missing-env-{uuid.uuid4()}"
    req = JoySafeterUpdateAgentRequest(version=1, environment_ref=missing_ref)

    with pytest.raises(AppError) as exc_info:
        await update_agent(req, agent.id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AGENT_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {missing_ref}",
        "data": {"environment_ref": missing_ref},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    assert row.environment_ref is None
    assert row.version == 1


@pytest.mark.asyncio
async def test_update_agent_rejects_environment_ref_change_with_active_task(db_session):
    env = JoySafeterEnvironment(name=f"active-update-env-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"active-env-agent-{uuid.uuid4()}", version=1)
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    agent_id = agent.id
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()
    task_id = task.id
    req = JoySafeterUpdateAgentRequest(version=1, environment_ref=str(env.id))

    with pytest.raises(AppError) as exc_info:
        await update_agent(req, agent_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ACTIVE_TASKS",
        "message": "Agent has active tasks. Stop or wait for them before changing model_credential_id or environment_ref.",
        "data": {"agent_id": str(agent_id), "active_task_ids": [str(task_id)]},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    assert row.environment_ref is None
    assert row.version == 1


@pytest.mark.asyncio
async def test_update_agent_rejects_archived_agent_with_structured_error(db_session):
    agent = JoySafeterAgent(name=f"archived-agent-{uuid.uuid4()}", version=1, archived_at=utc_now())
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    agent_id = agent.id
    original_name = agent.name

    req = JoySafeterUpdateAgentRequest(version=1, name=f"renamed-agent-{uuid.uuid4()}")
    with pytest.raises(AppError) as exc_info:
        await update_agent(req, agent_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and read-only. Updates are not allowed.",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    assert row.name == original_name
    assert row.version == 1


@pytest.mark.asyncio
async def test_update_agent_rejects_version_conflict_with_structured_error(db_session):
    agent = JoySafeterAgent(name=f"version-agent-{uuid.uuid4()}", version=2)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    agent_id = agent.id
    original_name = agent.name

    req = JoySafeterUpdateAgentRequest(version=1, name=f"renamed-agent-{uuid.uuid4()}")
    with pytest.raises(AppError) as exc_info:
        await update_agent(req, agent_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_VERSION_CONFLICT",
        "message": "Version conflict: expected 1, got 2",
        "data": {"agent_id": str(agent_id), "expected_version": 1, "actual_version": 2},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    assert row.name == original_name
    assert row.version == 2


@pytest.mark.asyncio
async def test_create_agent_name_conflict_is_structured_and_rolls_back(db_session):
    name = f"duplicate-agent-{uuid.uuid4()}"
    first = JoySafeterCreateAgentRequest(name=name, engine_kind="claude")
    duplicate = JoySafeterCreateAgentRequest(name=name, engine_kind="claude")
    await create_agent(first, db_session, _auth_ctx())

    with pytest.raises(AppError) as exc_info:
        await create_agent(duplicate, db_session, _auth_ctx())

    assert exc_info.value.code == "AGENT_NAME_CONFLICT"
    count = await db_session.scalar(
        select(func.count()).select_from(JoySafeterAgent).where(JoySafeterAgent.name == name)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_update_agent_name_conflict_is_structured_and_rolls_back(db_session):
    first = await create_agent(
        JoySafeterCreateAgentRequest(name=f"first-agent-{uuid.uuid4()}", engine_kind="claude"),
        db_session,
        _auth_ctx(),
    )
    second = await create_agent(
        JoySafeterCreateAgentRequest(name=f"second-agent-{uuid.uuid4()}", engine_kind="claude"),
        db_session,
        _auth_ctx(),
    )

    with pytest.raises(AppError) as exc_info:
        await update_agent(
            JoySafeterUpdateAgentRequest(version=second.version, name=first.name),
            second.id,
            db_session,
            _auth_ctx(),
        )

    assert exc_info.value.code == "AGENT_NAME_CONFLICT"
    db_session.expire_all()
    row = await db_session.get(JoySafeterAgent, second.id)
    assert row is not None
    assert row.name == second.name
    assert row.version == second.version


@pytest.mark.asyncio
async def test_noop_update_does_not_increment_version_or_add_snapshot(db_session):
    created = await create_agent(
        JoySafeterCreateAgentRequest(name=f"noop-agent-{uuid.uuid4()}", engine_kind="claude"),
        db_session,
        _auth_ctx(),
    )

    updated = await update_agent(
        JoySafeterUpdateAgentRequest(version=created.version),
        created.id,
        db_session,
        _auth_ctx(),
    )

    assert updated.version == created.version == 1
    version_count = await db_session.scalar(
        select(func.count()).select_from(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id == created.id)
    )
    assert version_count == 1


@pytest.mark.asyncio
async def test_noop_update_releases_agent_lock_before_return(db_session, postgres_url):
    agent = JoySafeterAgent(name=f"noop-lock-agent-{uuid.uuid4()}", version=1)
    db_session.add(agent)
    await db_session.commit()
    agent_id = agent.id
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as update_db, factory() as observer_db:
            await update_agent(
                JoySafeterUpdateAgentRequest(version=1),
                agent_id,
                update_db,
                _auth_ctx(),
            )
            locked = await asyncio.wait_for(
                SqlAlchemyAgentRepository(observer_db).lock(agent_id),
                timeout=0.5,
            )
            assert locked is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_environment_archive_serializes_with_agent_create(db_session, postgres_url, monkeypatch):
    environment = JoySafeterEnvironment(name=f"locked-env-{uuid.uuid4()}", description="")
    db_session.add(environment)
    await db_session.commit()
    environment_id = environment.id
    environment_ref = str(environment.id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    environment_locked = asyncio.Event()
    release_create = asyncio.Event()
    original_validate = AgentCommandService._validate_skill_refs

    async def pause_after_environment_lock(self, skills, project_id):
        environment_locked.set()
        await release_create.wait()
        return await original_validate(self, skills, project_id)

    monkeypatch.setattr(AgentCommandService, "_validate_skill_refs", pause_after_environment_lock)
    try:
        async with factory() as create_db, factory() as archive_db:
            create_future = asyncio.create_task(
                create_agent(
                    JoySafeterCreateAgentRequest(
                        name=f"environment-lock-agent-{uuid.uuid4()}",
                        engine_kind="claude",
                        environment_ref=environment_ref,
                    ),
                    create_db,
                    _auth_ctx(),
                )
            )
            await asyncio.wait_for(environment_locked.wait(), timeout=2)
            archive_future = asyncio.create_task(EnvironmentService(archive_db).archive_environment(environment_id))
            await asyncio.sleep(0.1)
            assert not archive_future.done()
            release_create.set()
            created, archive_result = await asyncio.gather(
                create_future,
                archive_future,
                return_exceptions=True,
            )

            assert not isinstance(created, Exception)
            assert isinstance(archive_result, ValueError)
            assert "referenced by agent" in str(archive_result)
    finally:
        release_create.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_environment_archive_serializes_with_agent_update(db_session, postgres_url, monkeypatch):
    environment = JoySafeterEnvironment(name=f"update-locked-env-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"environment-update-agent-{uuid.uuid4()}", version=1)
    db_session.add_all([environment, agent])
    await db_session.commit()
    environment_id = environment.id
    environment_ref = str(environment.id)
    agent_id = agent.id
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    environment_locked = asyncio.Event()
    release_update = asyncio.Event()
    original_list = SqlAlchemyAgentRepository.list_active_tasks

    async def pause_after_environment_lock(repository, candidate_agent_id, project_id=None):
        if repository.db is update_db:
            environment_locked.set()
            await release_update.wait()
        return await original_list(repository, candidate_agent_id, project_id=project_id)

    try:
        async with factory() as update_db, factory() as archive_db:
            monkeypatch.setattr(SqlAlchemyAgentRepository, "list_active_tasks", pause_after_environment_lock)
            update_future = asyncio.create_task(
                update_agent(
                    JoySafeterUpdateAgentRequest(version=1, environment_ref=environment_ref),
                    agent_id,
                    update_db,
                    _auth_ctx(),
                )
            )
            await asyncio.wait_for(environment_locked.wait(), timeout=2)
            archive_future = asyncio.create_task(EnvironmentService(archive_db).archive_environment(environment_id))
            await asyncio.sleep(0.1)
            assert not archive_future.done()
            release_update.set()
            updated, archive_result = await asyncio.gather(
                update_future,
                archive_future,
                return_exceptions=True,
            )

            assert not isinstance(updated, Exception)
            assert isinstance(archive_result, ValueError)
            assert "referenced by agent" in str(archive_result)
    finally:
        release_update.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_agent_create_releases_environment_lock(db_session, postgres_url):
    environment = JoySafeterEnvironment(name=f"failed-create-env-{uuid.uuid4()}", description="")
    db_session.add(environment)
    await db_session.commit()
    environment_id = environment.id
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as create_db, factory() as archive_db:
            with pytest.raises(AppError) as exc_info:
                await create_agent(
                    JoySafeterCreateAgentRequest(
                        name=f"failed-create-agent-{uuid.uuid4()}",
                        engine_kind="claude",
                        environment_ref=str(environment_id),
                        model_credential_id=CredentialId.new(),
                    ),
                    create_db,
                    _auth_ctx(),
                )
            assert exc_info.value.code == "CREDENTIAL_NOT_FOUND"

            archived = await asyncio.wait_for(
                EnvironmentService(archive_db).archive_environment(environment_id),
                timeout=0.5,
            )
            assert archived is True
    finally:
        await engine.dispose()


@pytest.mark.no_db
def test_mcp_server_validation_allows_http_urls_by_default(monkeypatch):
    monkeypatch.delenv("JOYSAFETER_MCP_REQUIRE_HTTPS", raising=False)
    for url in (
        "http://10.1.2.3:8080/mcp",
        "http://mcp-service.default.svc.cluster.local:8080/mcp",
        "http://pre-cc.jd.com/mcp",
        "HTTP://example.com/mcp",
    ):
        AgentConfigurationPolicy.validate_mcp_servers(
            [{"type": "url", "name": "tools", "url": url}],
            require_https=False,
        )


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_mcp_server_validation_can_require_https_for_non_local_http_urls(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_MCP_REQUIRE_HTTPS", "true")
    url = "HTTP://example.com/mcp"

    with pytest.raises(AppError) as exc_info:
        AgentConfigurationPolicy.validate_mcp_servers(
            [{"type": "url", "name": "tools", "url": url}],
            require_https=True,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AGENT_MCP_URL_SCHEME_INVALID",
        "message": f"MCP server URL must use HTTPS: {url}",
        "data": {"url": url, "host": "example.com"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    AgentConfigurationPolicy.validate_mcp_servers(
        [{"type": "url", "name": "tools", "url": "http://localhost:8080/mcp"}],
        require_https=True,
    )


@pytest.mark.asyncio
async def test_create_agent_rejects_duplicate_mcp_server_name_with_structured_error(db_session):
    req = JoySafeterCreateAgentRequest(
        name=f"duplicate-mcp-agent-{uuid.uuid4()}",
        engine_kind="claude",
        mcp_servers=[
            McpServerConfig(name="tools", url="https://example.com/a"),
            McpServerConfig(name="tools", url="https://example.com/b"),
        ],
    )

    with pytest.raises(AppError) as exc_info:
        await create_agent(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AGENT_MCP_SERVER_NAME_DUPLICATE",
        "message": "Duplicate MCP server name: tools",
        "data": {"mcp_server_name": "tools"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_agent_rejects_undeclared_mcp_tool_server_with_structured_error(db_session):
    req = JoySafeterCreateAgentRequest(
        name=f"undeclared-mcp-agent-{uuid.uuid4()}",
        engine_kind="claude",
        mcp_servers=[McpServerConfig(name="declared", url="https://example.com/mcp")],
        tools=[McpToolsetTool(mcp_server_name="missing")],
    )

    with pytest.raises(AppError) as exc_info:
        await create_agent(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AGENT_TOOL_MCP_SERVER_UNDECLARED",
        "message": "Tool references undeclared MCP server: missing",
        "data": {"mcp_server_name": "missing", "declared_mcp_server_names": ["declared"]},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
