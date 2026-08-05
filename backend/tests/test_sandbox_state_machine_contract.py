from datetime import timedelta

import pytest
from sqlalchemy import update

from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.services.joysafeter_sandbox_service import (
    InvalidSandboxTransition,
    SandboxService,
)
from app.joysafeter_shared.utils.datetime import utc_now


@pytest.mark.asyncio
async def test_sandbox_state_machine_allows_creating_to_pooled_for_warm_pool(db_session):
    service = SandboxService(db_session)
    sandbox = await service.create_sandbox(
        image="joysafeter/test-pool:latest",
        provider="test",
        status="creating",
        config={"provisioning": {"stage": "pool_warm"}},
    )

    await service.update_status(sandbox.id, "pooled")

    refreshed = await service.get_sandbox(sandbox.id)
    assert refreshed is not None
    assert refreshed.status == "pooled"


@pytest.mark.asyncio
async def test_sandbox_state_machine_keeps_idle_to_pooled_disallowed(db_session):
    service = SandboxService(db_session)
    sandbox = await service.create_sandbox(
        image="joysafeter/test-pool:latest",
        provider="test",
        status="creating",
        config={"provisioning": {"stage": "pool_warm"}},
    )
    await service.update_status(sandbox.id, "idle")

    with pytest.raises(InvalidSandboxTransition):
        await service.update_status(sandbox.id, "pooled")

    refreshed = await service.get_sandbox(sandbox.id)
    assert refreshed is not None
    assert refreshed.status == "idle"


@pytest.mark.asyncio
async def test_sandbox_state_machine_allows_provisioning_to_stopping_for_cleanup(db_session):
    service = SandboxService(db_session)
    sandbox = await service.create_sandbox(
        image="joysafeter/test-provisioning-cleanup:latest",
        provider="test",
        status="creating",
    )
    await service.update_status(sandbox.id, "provisioning")

    await service.update_status(sandbox.id, "stopping")

    refreshed = await service.get_sandbox(sandbox.id)
    assert refreshed is not None
    assert refreshed.status == "stopping"


@pytest.mark.asyncio
async def test_idle_expiry_uses_idle_since_not_stale_last_used_at(db_session):
    service = SandboxService(db_session)
    sandbox = await service.create_sandbox(
        image="joysafeter/test-idle:latest",
        provider="test",
        status="creating",
    )
    stale_last_used = utc_now() - timedelta(hours=2)
    await db_session.execute(
        update(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox.id).values(last_used_at=stale_last_used)
    )
    await db_session.commit()

    await service.update_status(sandbox.id, "idle")

    expired = await service.list_idle_expired(timeout_seconds=60)
    assert sandbox.id not in {row.id for row in expired}

    refreshed = await service.get_sandbox(sandbox.id)
    assert refreshed is not None
    assert refreshed.idle_since is not None
    assert refreshed.last_used_at <= stale_last_used


@pytest.mark.asyncio
async def test_idle_expiry_selects_rows_by_idle_since(db_session):
    service = SandboxService(db_session)
    sandbox = await service.create_sandbox(
        image="joysafeter/test-idle-expired:latest",
        provider="test",
        status="creating",
    )
    await service.update_status(sandbox.id, "idle")
    stale_idle_since = utc_now() - timedelta(hours=2)
    fresh_last_used = utc_now()
    await db_session.execute(
        update(JoySafeterSandbox)
        .where(JoySafeterSandbox.id == sandbox.id)
        .values(idle_since=stale_idle_since, last_used_at=fresh_last_used)
    )
    await db_session.commit()

    expired = await service.list_idle_expired(timeout_seconds=60)
    assert sandbox.id in {row.id for row in expired}
