import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.joysafeter_application.sensitive_material_cleanup import erase_expired_repository_token_material
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo
from app.joysafeter_shared.utils.datetime import utc_now


@pytest.mark.asyncio
async def test_expired_repository_token_cleanup_is_bounded_and_preserves_future_material(db_session):
    agent = JoySafeterAgent(name=f"repo-token-cleanup-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.flush()
    now = utc_now()
    db_session.add_all(
        [
            JoySafeterSessionRepo(
                session_id=session.id,
                url=f"https://github.com/example/private-{index}.git",
                branch="main",
                mount_path=f"/workspace/private-{index}",
                mount_name=f"private-{index}",
                encrypted_token=f"enc:v1:secret-{index}",
                token_expires_at=now - timedelta(minutes=1) if index < 2 else now + timedelta(minutes=5),
                token_rotated_at=now - timedelta(minutes=10),
            )
            for index in range(3)
        ]
    )
    await db_session.commit()

    assert await erase_expired_repository_token_material(db_session, limit=1) == 1
    await db_session.commit()
    rows = (
        (await db_session.execute(select(JoySafeterSessionRepo).order_by(JoySafeterSessionRepo.token_expires_at)))
        .scalars()
        .all()
    )

    assert sum(row.encrypted_token == "" for row in rows) == 1
    assert sum(row.token_erased_at is not None for row in rows) == 1
    assert rows[-1].encrypted_token != ""
    assert rows[-1].token_erased_at is None
