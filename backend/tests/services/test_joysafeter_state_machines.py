import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.joysafeter_domain.models.task import JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_sandbox_state_machine import (
    JoySafeterSandboxStateMachine,
    InvalidSandboxTransition,
)
from app.joysafeter_domain.services.sandbox_manager import JoySafeterSandboxService
from app.joysafeter_domain.services.task_service import JoySafeterTaskService


@pytest.mark.asyncio
async def test_joysafeter_task_service_delegates_state_transitions():
    db = AsyncMock()
    svc = JoySafeterTaskService(db)

    svc.state_machine.cancel = AsyncMock(return_value="cancelled-task")
    svc.state_machine.claim_for_scheduling = AsyncMock(return_value=True)
    svc.state_machine.claim_pending_batch = AsyncMock(return_value=[uuid.uuid4()])
    svc.state_machine.transition_to = AsyncMock(return_value=True)
    svc.state_machine.fail_with_error = AsyncMock(return_value=True)
    svc.state_machine.retry = AsyncMock(return_value=True)
    svc.state_machine.reset_sandbox_scheduling_to_pending = AsyncMock(return_value=2)
    svc.state_machine.attach_sandbox_if_scheduling = AsyncMock(return_value=True)

    task_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()
    svc.state_machine.claim_next_sandbox_task_for_running = AsyncMock(return_value=task_id)

    assert await svc.cancel_task(task_id) == "cancelled-task"
    assert await svc.claim_task_for_scheduling(task_id) is True
    claimed_batch = await svc.claim_pending_tasks_for_scheduling(10)
    assert await svc.update_task_status(task_id, JoySafeterTaskStatus.RUNNING) is True
    assert await svc.update_task_error(task_id, "boom", JoySafeterTaskStatus.FAILED) is True
    assert await svc.increment_retry(task_id) is True
    assert await svc.reset_sandbox_tasks_to_pending(sandbox_id) == 2
    assert await svc.attach_sandbox_if_scheduling(task_id, sandbox_id) is True
    assert await svc.claim_next_sandbox_task_for_running(sandbox_id) == task_id

    svc.state_machine.cancel.assert_awaited_once_with(task_id)
    svc.state_machine.claim_for_scheduling.assert_awaited_once_with(task_id)
    svc.state_machine.claim_pending_batch.assert_awaited_once_with(10)
    assert len(claimed_batch) == 1
    svc.state_machine.transition_to.assert_awaited_once_with(
        task_id, JoySafeterTaskStatus.RUNNING
    )
    svc.state_machine.fail_with_error.assert_awaited_once_with(
        task_id, "boom", JoySafeterTaskStatus.FAILED
    )
    svc.state_machine.retry.assert_awaited_once_with(task_id)
    svc.state_machine.reset_sandbox_scheduling_to_pending.assert_awaited_once_with(
        sandbox_id
    )
    svc.state_machine.attach_sandbox_if_scheduling.assert_awaited_once_with(
        task_id, sandbox_id
    )
    svc.state_machine.claim_next_sandbox_task_for_running.assert_awaited_once_with(
        sandbox_id
    )


@pytest.mark.asyncio
async def test_joysafeter_sandbox_service_delegates_state_transitions():
    db = AsyncMock()
    svc = JoySafeterSandboxService(db)

    svc.state_machine.transition = AsyncMock(return_value=True)
    svc.state_machine.complete_task = AsyncMock(return_value=True)

    sandbox_id = uuid.uuid4()
    task_id = uuid.uuid4()
    assert await svc.update_status_cas(sandbox_id, "idle", "stopping") is True
    await svc.update_status(sandbox_id, "stopped")
    await svc.mark_destroyed(sandbox_id)
    await svc.update_status_and_config(sandbox_id, "provisioning", {"stage": "boot"})
    assert await svc.complete_task(sandbox_id, task_id, "idle") is True

    svc.state_machine.transition.assert_any_await(
        sandbox_id, "stopping", expected_status="idle"
    )
    svc.state_machine.transition.assert_any_await(sandbox_id, "stopped")
    svc.state_machine.transition.assert_any_await(
        sandbox_id, "destroyed", mark_destroyed=True
    )
    svc.state_machine.transition.assert_any_await(
        sandbox_id, "provisioning", config={"stage": "boot"}, touch=True
    )
    svc.state_machine.complete_task.assert_awaited_once_with(
        sandbox_id, task_id, "idle"
    )


@pytest.mark.asyncio
async def test_sandbox_pool_claim_goes_through_state_machine():
    db = AsyncMock()
    svc = JoySafeterSandboxService(db)
    sandbox = SimpleNamespace(id=uuid.uuid4())
    session_id = uuid.uuid4()

    result_mock = Mock()
    result_mock.scalar_one_or_none.return_value = sandbox
    db.execute = AsyncMock(return_value=result_mock)
    svc.state_machine.claim_pool_for_session = AsyncMock(return_value=sandbox)

    claimed = await svc.claim_from_pool("image:latest", session_id)

    assert claimed is sandbox
    svc.state_machine.claim_pool_for_session.assert_awaited_once_with(
        sandbox, session_id
    )


@pytest.mark.asyncio
async def test_task_duration_is_recorded_by_state_machine():
    from app.joysafeter_domain.services.joysafeter_task_state_machine import JoySafeterTaskStateMachine

    started = datetime.now(timezone.utc) - timedelta(seconds=3)
    completed = datetime.now(timezone.utc)

    assert JoySafeterTaskStateMachine._duration_ms(started, completed) >= 3000
    assert JoySafeterTaskStateMachine._duration_ms(None, completed) is None


def test_sandbox_state_machine_allows_expected_lifecycle_transitions():
    allowed = [
        ("creating", "provisioning"),
        ("provisioning", "idle"),
        ("provisioning", "stopped"),
        ("idle", "running"),
        ("running", "idle"),
        ("idle", "stopping"),
        ("stopping", "idle"),
        ("stopping", "stopped"),
        ("stopping", "error"),
        ("stopped", "provisioning"),
        ("pooled", "provisioning"),
        ("error", "destroyed"),
    ]

    for from_status, to_status in allowed:
        JoySafeterSandboxStateMachine._validate_transition(from_status, to_status)


def test_sandbox_state_machine_rejects_invalid_lifecycle_transitions():
    invalid = [
        ("destroyed", "idle"),
        ("error", "idle"),
        ("stopped", "idle"),
        ("pooled", "idle"),
        ("running", "provisioning"),
    ]

    for from_status, to_status in invalid:
        with pytest.raises(InvalidSandboxTransition):
            JoySafeterSandboxStateMachine._validate_transition(from_status, to_status)
