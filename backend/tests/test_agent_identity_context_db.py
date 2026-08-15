from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.joysafeter_api.api.v1.agent_identity_capture import prepare_agent_identity_capture
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext


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

    user = AuthUser(name="Identity User", email="identity@example.com")
    agent = JoySafeterAgent(name="identity-db-agent")
    db_session.add_all([user, agent])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(agent)

    task_one = JoySafeterTask(agent_id=agent.id, prompt="one", status="pending", user_id=user.id)
    task_two = JoySafeterTask(agent_id=agent.id, prompt="two", status="pending", user_id=user.id)
    db_session.add_all([task_one, task_two])
    await db_session.commit()
    await db_session.refresh(task_one)
    await db_session.refresh(task_two)

    auth_ctx = SimpleNamespace(user_id=user.id, project_id=None)
    request = SimpleNamespace(cookies={})
    first_hook = await prepare_agent_identity_capture(
        db_session,
        request,
        auth_ctx,
        agent,
        identity_auth_code="single-use-code",
    )
    second_hook = await prepare_agent_identity_capture(
        db_session,
        request,
        auth_ctx,
        agent,
        identity_auth_code="single-use-code",
    )
    assert first_hook is not None
    assert second_hook is not None

    await first_hook(task_one)
    with pytest.raises(IntegrityError):
        await second_hook(task_two)
    await db_session.rollback()

    count = await db_session.scalar(select(func.count()).select_from(JoySafeterTaskIdentityContext))
    assert count == 1

    await db_session.delete(task_one)
    await db_session.commit()
    count = await db_session.scalar(select(func.count()).select_from(JoySafeterTaskIdentityContext))
    assert count == 0
