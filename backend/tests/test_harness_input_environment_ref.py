import uuid

import pytest

from app.joysafeter_api.api.v1.sessions import create_session
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_session import CreateSessionRequest
from app.joysafeter_orchestrator.kernel.harness_input_builder import build_harness_input
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


class _ExistingSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_exc_info):
        return False


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


@pytest.mark.asyncio
async def test_create_session_canonicalizes_bare_uuid_environment_ref(db_session):
    env = JoySafeterEnvironment(name=f"canonical-session-env-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(
        name=f"canonical-session-agent-{uuid.uuid4()}",
        engine_kind="claude",
        tools=[],
        mcp_configs=[],
        skills=[],
    )
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)

    response = await create_session(
        CreateSessionRequest(agent=f"agent_{agent.id}", environment_id=str(env.id)),
        db_session,
        _auth_ctx(),
    )

    assert response.environment_id == f"env_{env.id}"


@pytest.mark.asyncio
async def test_harness_input_prefers_session_environment_ref_over_agent_default(db_session, monkeypatch):
    agent_env = JoySafeterEnvironment(
        name=f"agent-default-env-{uuid.uuid4()}",
        description="",
        config={"env_vars": {"SELECTED_ENV": "agent"}, "packages": {"pip": ["agentpkg"]}},
    )
    session_env = JoySafeterEnvironment(
        name=f"session-override-env-{uuid.uuid4()}",
        description="",
        config={"env_vars": {"SELECTED_ENV": "session"}, "packages": {"pip": ["sessionpkg"]}},
    )
    db_session.add(agent_env)
    await db_session.flush()
    await db_session.refresh(agent_env)
    db_session.add(session_env)
    await db_session.flush()
    await db_session.refresh(session_env)

    agent = JoySafeterAgent(
        name=f"harness-env-agent-{uuid.uuid4()}",
        engine_kind="claude",
        model={"id": "claude-test"},
        tools=[],
        mcp_configs=[],
        skills=[],
        environment_ref=f"env_{agent_env.id}",
    )
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(
        agent_id=agent.id,
        status="idle",
        environment_ref=str(session_env.id),  # Legacy bare UUID refs must still resolve.
    )
    db_session.add(session)
    await db_session.flush()
    task = JoySafeterTask(
        agent_id=agent.id,
        prompt="run",
        status=JoySafeterTaskStatus.RUNNING.value,
        chat_session_id=session.id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(task)

    monkeypatch.setattr(
        "app.joysafeter_shared.database.AsyncSessionLocal",
        lambda: _ExistingSessionContext(db_session),
    )

    harness_input = await build_harness_input(
        task,
        agent,
        session.id,
        sandbox_external_id="sandbox-ext",
        sandbox_db_id=uuid.uuid4(),
    )

    assert harness_input.env["SELECTED_ENV"] == "session"
    assert "pip install sessionpkg" in harness_input.setup_commands
    assert "pip install agentpkg" not in harness_input.setup_commands
