import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")

from app.models.execution import Execution, MissionExecutionStatus, ExecutionSource


def test_execution_column_defaults():
    """Verify column default callables are wired to the expected enum values."""
    status_col = Execution.__table__.c.status
    last_seq_col = Execution.__table__.c.last_seq

    assert status_col.default.arg == MissionExecutionStatus.QUEUED
    assert last_seq_col.default.arg == 0


def test_execution_explicit_values():
    e = Execution(
        workspace_id=uuid.uuid4(),
        user_id="user-1",
        source=ExecutionSource.MISSION,
        runtime_type="claude_code",
        status=MissionExecutionStatus.RUNNING,
        last_seq=42,
    )
    assert e.status == MissionExecutionStatus.RUNNING
    assert e.last_seq == 42
    assert e.source == ExecutionSource.MISSION
