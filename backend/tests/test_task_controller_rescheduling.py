import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.models.joysafeter_session import SessionStatus
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus
from app.joysafeter_domain.services import joysafeter_session_service
from app.joysafeter_orchestrator.kernel.task_controller import TaskController


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, has_active_tasks=False):
        self.has_active_tasks = has_active_tasks

    async def execute(self, *_args, **_kwargs):
        return _ScalarResult(self.has_active_tasks)


class _FakeSchedulingDb:
    def __init__(self, task_id, session_id):
        self.task_id = task_id
        self.session_id = session_id
        self._calls = 0

    async def execute(self, *_args, **_kwargs):
        self._calls += 1
        if self._calls == 1:
            return _ScalarResult(True)
        if self._calls == 2:
            return _RowsResult([(self.task_id, 2, 2, self.session_id)])
        if self._calls == 3:
            return _ScalarResult(False)
        return _ScalarResult(None)


class _FakeSessionLocal:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_args):
        return False


class _FakeTaskService:
    updated_errors = []
    task = None

    def __init__(self, _db):
        pass

    async def get_task(self, task_id):
        if self.task and self.task.id == task_id:
            return self.task
        return None

    async def update_task_error(self, task_id, reason, status):
        self.updated_errors.append((task_id, reason, status))


class _FakeSessionService:
    def __init__(self, _db):
        pass

    async def task_has_agent_output(self, *_args):
        return False


class _FakeSessionLifecycle:
    transitions = []

    def __init__(self, _db):
        pass

    async def transition_and_emit(
        self,
        session_id,
        status,
        event_type,
        payload,
        *,
        stop_reason=None,
    ):
        self.transitions.append((session_id, status, event_type, payload, stop_reason))


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch):
    _FakeTaskService.updated_errors = []
    _FakeTaskService.task = None
    _FakeSessionLifecycle.transitions = []

    from app.joysafeter_orchestrator import services

    monkeypatch.setattr(services, "TaskService", _FakeTaskService)
    monkeypatch.setattr(services, "SessionService", _FakeSessionService)
    monkeypatch.setattr(services, "JoySafeterSessionLifecycleService", _FakeSessionLifecycle)


def test_session_state_machine_allows_rescheduling_to_idle():
    assert (
        SessionStatus.RESCHEDULING.value
        in joysafeter_session_service._VALID_TRANSITIONS[SessionStatus.IDLE.value]
    )


@pytest.mark.asyncio
async def test_failover_exhausted_task_returns_rescheduling_session_to_idle(monkeypatch):
    from app.joysafeter_shared import database

    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _FakeTaskService.task = SimpleNamespace(
        id=task_id,
        status=JoySafeterTaskStatus.RUNNING.value,
        retry_count=2,
        max_retries=2,
        chat_session_id=session_id,
    )
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionLocal(_FakeDb(False)))

    result = await TaskController.failover_or_fail_task(task_id, "Failed execute_batch")

    assert result is None
    assert _FakeTaskService.updated_errors == [
        (task_id, "Failed execute_batch", JoySafeterTaskStatus.FAILED)
    ]
    assert _FakeSessionLifecycle.transitions == [
        (
            session_id,
            "idle",
            "session.status_idle",
            {"stop_reason": {"type": "sandbox_failed", "message": "Failed execute_batch"}},
            {"type": "sandbox_failed", "message": "Failed execute_batch"},
        )
    ]


@pytest.mark.asyncio
async def test_failover_exhausted_task_keeps_session_active_when_other_tasks_remain(monkeypatch):
    from app.joysafeter_shared import database

    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _FakeTaskService.task = SimpleNamespace(
        id=task_id,
        status=JoySafeterTaskStatus.RUNNING.value,
        retry_count=2,
        max_retries=2,
        chat_session_id=session_id,
    )
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _FakeSessionLocal(_FakeDb(True)))

    result = await TaskController.failover_or_fail_task(task_id, "Failed execute_batch")

    assert result is None
    assert _FakeTaskService.updated_errors == [
        (task_id, "Failed execute_batch", JoySafeterTaskStatus.FAILED)
    ]
    assert _FakeSessionLifecycle.transitions == []


@pytest.mark.asyncio
async def test_stuck_scheduling_exhausted_task_returns_session_to_idle(monkeypatch):
    from app.joysafeter_shared import database

    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    monkeypatch.setattr(
        database,
        "AsyncSessionLocal",
        lambda: _FakeSessionLocal(_FakeSchedulingDb(task_id, session_id)),
    )

    await TaskController(queue=SimpleNamespace())._check_stuck_scheduling()

    assert _FakeTaskService.updated_errors == [
        (
            task_id,
            "Retries exhausted while stuck in scheduling",
            JoySafeterTaskStatus.FAILED,
        )
    ]
    assert _FakeSessionLifecycle.transitions == [
        (
            session_id,
            "idle",
            "session.status_idle",
            {"stop_reason": {"type": "retries_exhausted"}},
            {"type": "retries_exhausted"},
        )
    ]
