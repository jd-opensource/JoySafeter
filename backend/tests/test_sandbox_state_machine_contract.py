import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.services.joysafeter_sandbox_service import (
    InvalidSandboxTransition,
    SandboxService,
)
from app.joysafeter_shared.utils.datetime import utc_now


async def _create_session(
    db_session,
    *,
    project_id=None,
    status="idle",
    archived_at=None,
    generation=1,
):
    agent = JoySafeterAgent(name=f"sandbox-state-machine-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    session = JoySafeterSession(
        agent_id=agent.id,
        project_id=project_id,
        status=status,
        archived_at=archived_at,
        runtime_config_generation=generation,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _mark_restart_required(db_session, sandbox_id):
    required_at = utc_now()
    await db_session.execute(
        update(JoySafeterSandbox)
        .where(JoySafeterSandbox.id == sandbox_id)
        .values(
            runtime_config_status="restart_required",
            runtime_config_last_reason="credential_rotated",
            runtime_config_required_at=required_at,
        )
    )
    await db_session.commit()
    return required_at


@pytest.mark.asyncio
async def test_generic_create_rejects_session_bound_ready_write(db_session):
    # Session-bound sandbox creation is owned by the Rust orchestrator's
    # create_session_bound_sandbox_guarded; the Python domain service must
    # refuse it rather than hand-rolling the generation CAS.
    service = SandboxService(db_session)
    session = await _create_session(db_session)

    with pytest.raises(ValueError, match="create_session_bound_sandbox"):
        await service.create_sandbox(
            image="joysafeter/test-runtime-ready:latest",
            provider="test",
            chat_session_id=session.id,
        )

    count = await db_session.scalar(select(func.count()).select_from(JoySafeterSandbox))
    assert count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_status", ["pooled", "stopped"])
async def test_state_only_provisioning_transition_preserves_runtime_configuration(
    db_session,
    initial_status,
):
    service = SandboxService(db_session)
    sandbox = await service.create_sandbox(
        image=f"joysafeter/test-runtime-state-only-{initial_status}:latest",
        provider="test",
        status=initial_status,
    )
    required_at = await _mark_restart_required(db_session, sandbox.id)

    await service.update_status(sandbox.id, "provisioning")

    refreshed = await service.get_sandbox(sandbox.id)
    assert refreshed is not None
    assert refreshed.status == "provisioning"
    assert refreshed.runtime_config_status == "restart_required"
    assert refreshed.runtime_config_last_reason == "credential_rotated"
    assert refreshed.runtime_config_required_at == required_at


@pytest.mark.asyncio
async def test_running_and_idle_transitions_preserve_restart_required_runtime_configuration(db_session):
    service = SandboxService(db_session)
    sandbox = await service.create_sandbox(
        image="joysafeter/test-runtime-transitions:latest",
        provider="test",
        status="idle",
    )
    required_at = await _mark_restart_required(db_session, sandbox.id)

    await service.update_status(sandbox.id, "running")
    await service.update_status(sandbox.id, "idle")

    refreshed = await service.get_sandbox(sandbox.id)
    assert refreshed is not None
    assert refreshed.runtime_config_status == "restart_required"
    assert refreshed.runtime_config_last_reason == "credential_rotated"
    assert refreshed.runtime_config_required_at == required_at


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
