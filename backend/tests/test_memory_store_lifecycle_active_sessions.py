import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.joysafeter_api.api.v1.memory_stores import archive_memory_store, delete_memory_store
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterMemoryStore, JoySafeterSessionMemoryStore
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


async def _mounted_store(db_session):
    store = JoySafeterMemoryStore(name=f"store-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"memory-agent-{uuid.uuid4()}")
    db_session.add_all([store, agent])
    await db_session.commit()
    await db_session.refresh(store)
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    mount = JoySafeterSessionMemoryStore(
        session_id=session.id,
        store_id=store.id,
        access="read_write",
        mount_name="main",
    )
    db_session.add(mount)
    await db_session.commit()
    return store.id


@pytest.mark.asyncio
async def test_archive_memory_store_rejects_active_session_reference(db_session):
    store_id = await _mounted_store(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await archive_memory_store(store_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Memory store is referenced by one or more active sessions."

    db_session.expire_all()
    store_row = (
        await db_session.execute(select(JoySafeterMemoryStore).where(JoySafeterMemoryStore.id == store_id))
    ).scalar_one()
    assert store_row.archived_at is None


@pytest.mark.asyncio
async def test_delete_memory_store_rejects_active_session_reference(db_session):
    store_id = await _mounted_store(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await delete_memory_store(store_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Memory store is referenced by one or more active sessions."

    db_session.expire_all()
    store_row = (
        await db_session.execute(select(JoySafeterMemoryStore).where(JoySafeterMemoryStore.id == store_id))
    ).scalar_one()
    assert store_row.id == store_id
