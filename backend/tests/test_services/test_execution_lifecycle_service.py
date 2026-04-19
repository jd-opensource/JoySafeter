# backend/tests/test_services/test_execution_lifecycle_service.py
from __future__ import annotations

from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.services.execution_lifecycle_service import ExecutionLifecycleService


def test_lifecycle_service_satisfies_runner_callbacks_protocol():
    """ExecutionLifecycleService must implement RunnerCallbacks."""
    from unittest.mock import MagicMock

    db = MagicMock()
    svc = ExecutionLifecycleService(db)
    assert isinstance(svc, RunnerCallbacks)
