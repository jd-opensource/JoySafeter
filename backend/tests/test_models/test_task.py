import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")

from app.models.task import Task, TaskPriority, TaskStatus


def test_task_column_defaults():
    """Verify column default callables are wired to the expected enum values."""
    status_col = Task.__table__.c.status
    priority_col = Task.__table__.c.priority
    position_col = Task.__table__.c.position

    assert status_col.default.arg == TaskStatus.BACKLOG
    assert priority_col.default.arg == TaskPriority.NONE
    assert position_col.default.arg == 0.0


def test_task_explicit_values():
    m = Task(
        workspace_id=uuid.uuid4(),
        title="Test APK audit",
        creator_id="user-1",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        position=1.5,
    )
    assert m.status == TaskStatus.IN_PROGRESS
    assert m.priority == TaskPriority.HIGH
    assert m.position == 1.5
    assert m.title == "Test APK audit"
