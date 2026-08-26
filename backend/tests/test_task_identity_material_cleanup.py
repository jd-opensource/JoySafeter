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
    assert rows[-1].encrypted_credential is not None
