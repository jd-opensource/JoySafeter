import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.joysafeter_application.sensitive_material_cleanup import erase_expired_task_identity_material
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext
from app.joysafeter_shared.ids import AgentId, TaskId, UserId
from app.joysafeter_shared.utils.datetime import utc_now


@pytest.mark.asyncio
async def test_expired_task_identity_cleanup_is_bounded_and_preserves_future_material(db_session):
    user = AuthUser(id=UserId.new(), name="Cleanup User", email=f"cleanup-{uuid.uuid4()}@example.com")
    agent = JoySafeterAgent(id=AgentId.new(), name=f"cleanup-agent-{uuid.uuid4()}")
    db_session.add_all([user, agent])
    await db_session.flush()
    tasks = [
        JoySafeterTask(id=TaskId.new(), agent_id=agent.id, prompt=str(index), status="pending", user_id=user.id)
        for index in range(3)
    ]
    db_session.add_all(tasks)
    await db_session.flush()
    now = utc_now()
    db_session.add_all(
        [
            JoySafeterTaskIdentityContext(
                task_id=tasks[index].id,
                user_id=user.id,
                credential_kind="identity_token",
                encrypted_credential=f"enc:v1:secret-{index}",
                captured_at=now - timedelta(minutes=10),
                expires_at=now - timedelta(minutes=1) if index < 2 else now + timedelta(minutes=5),
            )
            for index in range(3)
        ]
    )
    await db_session.commit()

    assert await erase_expired_task_identity_material(db_session, limit=1) == 1
    await db_session.commit()
    rows = (
        (
            await db_session.execute(
                select(JoySafeterTaskIdentityContext).order_by(JoySafeterTaskIdentityContext.expires_at)
            )
        )
        .scalars()
        .all()
    )

    assert sum(row.encrypted_credential is None for row in rows) == 1
    assert sum(row.state == "expired" for row in rows) == 1
    assert rows[-1].state == "captured"
    assert rows[-1].encrypted_credential is not None


@pytest.mark.asyncio
async def test_cleanup_preserves_active_claim_and_expires_stale_claim(db_session):
    user = AuthUser(id=UserId.new(), name="Claim Cleanup User", email=f"claim-{uuid.uuid4()}@example.com")
    agent = JoySafeterAgent(id=AgentId.new(), name=f"claim-agent-{uuid.uuid4()}")
    db_session.add_all([user, agent])
    await db_session.flush()
    active_task = JoySafeterTask(id=TaskId.new(), agent_id=agent.id, prompt="active", status="pending", user_id=user.id)
    stale_task = JoySafeterTask(id=TaskId.new(), agent_id=agent.id, prompt="stale", status="pending", user_id=user.id)
    db_session.add_all([active_task, stale_task])
    await db_session.flush()
    now = utc_now()
    active_resolution_id = uuid.uuid4()
    stale_resolution_id = uuid.uuid4()
    db_session.add_all(
        [
            JoySafeterTaskIdentityContext(
                task_id=active_task.id,
                user_id=user.id,
                credential_kind="identity_token",
                encrypted_credential="enc:v1:active-claim",
                captured_at=now - timedelta(minutes=10),
                expires_at=now - timedelta(minutes=1),
                state="resolving",
                resolution_id=active_resolution_id,
                resolution_expires_at=now + timedelta(minutes=1),
            ),
            JoySafeterTaskIdentityContext(
                task_id=stale_task.id,
                user_id=user.id,
                credential_kind="identity_token",
                encrypted_credential="enc:v1:stale-claim",
                captured_at=now - timedelta(minutes=10),
                expires_at=now - timedelta(minutes=1),
                state="resolving",
                resolution_id=stale_resolution_id,
                resolution_expires_at=now - timedelta(seconds=1),
            ),
        ]
    )
    await db_session.commit()

    assert await erase_expired_task_identity_material(db_session, limit=10) == 1
    await db_session.commit()
    active = await db_session.get(JoySafeterTaskIdentityContext, active_task.id)
    stale = await db_session.get(JoySafeterTaskIdentityContext, stale_task.id)

    assert active is not None
    assert active.state == "resolving"
    assert active.resolution_id == active_resolution_id
    assert active.encrypted_credential is not None
    assert stale is not None
    assert stale.state == "expired"
    assert stale.resolution_id is None
    assert stale.resolution_expires_at is None
    assert stale.encrypted_credential is None
