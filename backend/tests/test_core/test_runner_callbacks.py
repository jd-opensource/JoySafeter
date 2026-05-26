from __future__ import annotations

import uuid

import pytest

from app.core.agent.cli_backends.base import CLIResult
from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.models.execution import MissionExecutionStatus


class FakeCallbacks:
    """Minimal implementation for testing the Protocol contract."""

    def __init__(self):
        self.finalized: list[tuple] = []
        self.failed: list[tuple] = []

    async def on_execution_finalized(self, execution_id, status, result):
        self.finalized.append((execution_id, status, result))

    async def on_execution_failed(self, execution_id, error):
        self.failed.append((execution_id, error))


def test_fake_callbacks_satisfies_protocol():
    cb = FakeCallbacks()
    assert isinstance(cb, RunnerCallbacks)


@pytest.mark.asyncio
async def test_on_execution_finalized_records_call():
    cb = FakeCallbacks()
    eid = uuid.uuid4()
    result = CLIResult(status="completed", output="done", error=None, session_id="s1")
    await cb.on_execution_finalized(eid, MissionExecutionStatus.COMPLETED, result)
    assert len(cb.finalized) == 1
    assert cb.finalized[0][0] == eid


@pytest.mark.asyncio
async def test_on_execution_failed_records_call():
    cb = FakeCallbacks()
    eid = uuid.uuid4()
    await cb.on_execution_failed(eid, "OOM killed")
    assert len(cb.failed) == 1
    assert cb.failed[0] == (eid, "OOM killed")


def test_none_satisfies_optional_pattern():
    """Runner accepts callbacks=None for standalone executions."""
    cb = None
    assert cb is None or isinstance(cb, RunnerCallbacks)
