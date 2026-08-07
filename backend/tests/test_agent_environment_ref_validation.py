import uuid

import pytest
from credential_test_helpers import encrypted_secret_data
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.agents import create_agent, update_agent
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
    McpServerConfig,
    McpToolsetTool,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
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
    req = JoySafeterCreateAgentRequest(
        name=f"archived-env-agent-{uuid.uuid4()}",
        engine_kind="claude",
        environment_ref=str(env.id),
    )

    with pytest.raises(AppError) as exc_info:
        await create_agent(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: {env.id}",
        "data": {"environment_ref": str(env.id), "environment_id": str(env.id)},
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
    req = JoySafeterUpdateAgentRequest(version=1, environment_ref=str(env.id))

    with pytest.raises(AppError) as exc_info:
        await update_agent(req, agent_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ACTIVE_TASKS",
        "message": "Agent has active tasks. Stop or wait for them before changing secret_ref or environment_ref.",
        "data": {"agent_id": str(agent_id), "active_task_ids": [str(task.id)]},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    assert row.environment_ref is None
    assert row.version == 1


@pytest.mark.asyncio
async def test_update_agent_rejects_secret_ref_change_with_active_task(db_session):
    secret = JoySafeterSecret(
        name=f"active-secret-{uuid.uuid4()}",
        kind="llm",
        provider="anthropic",
        protocol="anthropic_messages",
        data=encrypted_secret_data({"ANTHROPIC_API_KEY": "value"}),
    )
    agent = JoySafeterAgent(name=f"active-secret-agent-{uuid.uuid4()}", version=1)
    db_session.add_all([secret, agent])
    await db_session.commit()
    await db_session.refresh(secret)
    await db_session.refresh(agent)
    agent_id = agent.id
    task = JoySafeterTask(
        agent_id=agent_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
    )
    db_session.add(task)
    await db_session.commit()
    req = JoySafeterUpdateAgentRequest(version=1, secret_ref=secret.name)

    with pytest.raises(AppError) as exc_info:
        await update_agent(req, agent_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ACTIVE_TASKS",
        "message": "Agent has active tasks. Stop or wait for them before changing secret_ref or environment_ref.",
        "data": {"agent_id": str(agent_id), "active_task_ids": [str(task.id)]},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))).scalar_one()
    assert row.secret_ref is None
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
async def test_create_agent_rejects_missing_secret_ref_with_structured_error(db_session):
    missing_ref = f"missing-secret-{uuid.uuid4()}"
    req = JoySafeterCreateAgentRequest(
        name=f"secret-ref-agent-{uuid.uuid4()}",
        engine_kind="claude",
        secret_ref=missing_ref,
    )

    with pytest.raises(AppError) as exc_info:
        await create_agent(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AGENT_SECRET_NOT_FOUND",
        "message": f"Secret not found: {missing_ref}",
        "data": {"secret_ref": missing_ref, "engine_kind": "claude"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }

    row = (
        await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.name == req.name))
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_create_agent_rejects_secret_engine_mismatch_with_structured_error(db_session):
    secret = JoySafeterSecret(
        name=f"openai-secret-{uuid.uuid4()}",
        kind="llm",
        provider="openai",
        protocol="openai_responses",
        data=encrypted_secret_data({"OPENAI_API_KEY": "value"}),
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    req = JoySafeterCreateAgentRequest(
        name=f"secret-mismatch-agent-{uuid.uuid4()}",
        engine_kind="claude",
        secret_ref=secret.name,
    )
    with pytest.raises(AppError) as exc_info:
        await create_agent(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AGENT_SECRET_INCOMPATIBLE",
        "message": f"Secret '{secret.name}' is not compatible with engine_kind 'claude'",
        "data": {
                "secret_ref": secret.name,
                "engine_kind": "claude",
                "kind": "llm",
                "provider": "openai",
            "protocol": "openai_responses",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_native_agent_accepts_openai_secret_and_resolves_model(db_session):
    secret = JoySafeterSecret(
        name=f"native-openai-secret-{uuid.uuid4()}",
        kind="llm",
        provider="openai",
        protocol="openai_responses",
        data=encrypted_secret_data({"OPENAI_API_KEY": "value", "OPENAI_MODEL": "gpt-5-native"}),
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    req = JoySafeterCreateAgentRequest(
        name=f"native-openai-agent-{uuid.uuid4()}",
        engine_kind="native",
        secret_ref=secret.name,
    )

    response = await create_agent(req, db_session, _auth_ctx())

    assert response.engine_kind == "native"
    assert response.secret_ref == secret.name
    assert response.model is not None
    assert response.model.id == "gpt-5-native"

    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.name == req.name))).scalar_one()
    assert row.engine_kind == "native"
    assert row.secret_ref == secret.name


@pytest.mark.asyncio
async def test_create_agent_accepts_pi_engine_kind(db_session):
    secret = JoySafeterSecret(
        name=f"pi-secret-{uuid.uuid4()}",
        kind="llm",
        provider="anthropic",
        protocol="anthropic_messages",
        data=encrypted_secret_data({"ANTHROPIC_API_KEY": "value", "ANTHROPIC_MODEL": "pi-model"}),
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    req = JoySafeterCreateAgentRequest(
        name=f"pi-agent-{uuid.uuid4()}",
        engine_kind="pi",
        secret_ref=secret.name,
    )

    response = await create_agent(req, db_session, _auth_ctx())

    assert response.engine_kind == "pi"
    assert response.secret_ref == secret.name
    assert response.model is not None
    assert response.model.id == "pi-model"

    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.name == req.name))).scalar_one()
    assert row.engine_kind == "pi"
    assert row.secret_ref == secret.name


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
