import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")

from app.models.execution import Execution


def test_execution_column_defaults():
    """Verify column default callables are wired to the expected values."""
    status_col = Execution.__table__.c.status
    last_seq_col = None
    attempt_col = Execution.__table__.c.attempt_index

    assert status_col.default.arg == "pending"
    assert attempt_col.default.arg == 1


def test_execution_explicit_values():
    e = Execution(
        run_id=uuid.uuid4(),
        executor_kind="claude_code",
        status="running",
        attempt_index=2,
    )
    assert e.status == "running"
    assert e.attempt_index == 2
    assert e.executor_kind == "claude_code"
