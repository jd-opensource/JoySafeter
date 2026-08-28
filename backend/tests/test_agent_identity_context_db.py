import hashlib
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.joysafeter_api.api.v1.agent_identity_capture import prepare_agent_identity_capture
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext
from app.joysafeter_shared.ids import AgentId, TaskId, UserId
from app.joysafeter_shared.utils.datetime import utc_now


@pytest.mark.asyncio
async def test_auth_code_replay_is_rejected_and_task_delete_cascades(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_IDENTITY_PROVIDER", "jd")
    monkeypatch.setenv("AGENT_IDENTITY_BASE_URL", "https://identity.example.com")
    monkeypatch.setenv("AGENT_IDENTITY_ALLOWED_HOSTS", "mcp.example.com")
    monkeypatch.setenv(
        "JOYSAFETER_VAULT_ENCRYPTION_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    user = AuthUser(id=UserId.new(), name="Identity User", email="identity@example.com")
    agent = JoySafeterAgent(id=AgentId.new(), name="identity-db-agent")
    db_session.add_all([user, agent])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(agent)

    task_one = JoySafeterTask(id=TaskId.new(), agent_id=agent.id, prompt="one", status="pending", user_id=user.id)
    task_two = JoySafeterTask(id=TaskId.new(), agent_id=agent.id, prompt="two", status="pending", user_id=user.id)
    db_session.add_all([task_one, task_two])
    await db_session.commit()
    await db_session.refresh(task_one)
    await db_session.refresh(task_two)

    auth_ctx = SimpleNamespace(user_id=user.id, project_id=None)
    request = SimpleNamespace(cookies={})
    environment = {"config": {"egress_services": [{"auth_source": "agent_identity"}]}}
    auth_code = f"single-use-{uuid.uuid4()}"
    credential_fingerprint = hashlib.sha256(auth_code.encode()).hexdigest()
    first_hook = await prepare_agent_identity_capture(
        db_session,
        request,
        auth_ctx,
        agent,
        environment,
        identity_auth_code=auth_code,
    )
    second_hook = await prepare_agent_identity_capture(
        db_session,
        request,
        auth_ctx,
        agent,
        environment,
        identity_auth_code=auth_code,
    )
    assert first_hook is not None
    assert second_hook is not None

    await first_hook(task_one)
    with pytest.raises(IntegrityError):
        await second_hook(task_two)
    await db_session.rollback()

    count = await db_session.scalar(
        select(func.count())
        .select_from(JoySafeterTaskIdentityContext)
        .where(JoySafeterTaskIdentityContext.credential_fingerprint == credential_fingerprint)
    )
    assert count == 1

    await db_session.delete(task_one)
    await db_session.commit()
    count = await db_session.scalar(
        select(func.count())
        .select_from(JoySafeterTaskIdentityContext)
        .where(JoySafeterTaskIdentityContext.credential_fingerprint == credential_fingerprint)
    )
    assert count == 0


@pytest.mark.asyncio
async def test_terminal_task_transition_erases_unconsumed_identity_material(db_session) -> None:
    user = AuthUser(id=UserId.new(), name="Terminal Identity User", email=f"terminal-{uuid.uuid4()}@example.com")
    agent = JoySafeterAgent(id=AgentId.new(), name=f"terminal-agent-{uuid.uuid4()}")
    db_session.add_all([user, agent])
    await db_session.flush()
    task = JoySafeterTask(id=TaskId.new(), agent_id=agent.id, prompt="terminal", status="pending", user_id=user.id)
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        JoySafeterTaskIdentityContext(
            task_id=task.id,
            project_id=None,
            user_id=user.id,
            credential_kind="identity_token",
            encrypted_credential="enc:v1:still-secret",
            captured_at=utc_now(),
            expires_at=utc_now() + timedelta(minutes=5),
        )
    )
    await db_session.commit()

    task.status = "failed"
    await db_session.commit()
    await db_session.refresh(task)
    identity = await db_session.get(JoySafeterTaskIdentityContext, task.id)

    assert identity is not None
    assert identity.encrypted_credential is None
