import os
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")

from app.models.mission import Mission, MissionStatus, MissionPriority


def test_mission_column_defaults():
    """Verify column default callables are wired to the expected enum values."""
    status_col = Mission.__table__.c.status
    priority_col = Mission.__table__.c.priority
    position_col = Mission.__table__.c.position

    assert status_col.default.arg == MissionStatus.BACKLOG
    assert priority_col.default.arg == MissionPriority.NONE
    assert position_col.default.arg == 0.0


def test_mission_explicit_values():
    m = Mission(
        workspace_id=uuid.uuid4(),
        title="Test APK audit",
        creator_id="user-1",
        status=MissionStatus.IN_PROGRESS,
        priority=MissionPriority.HIGH,
        position=1.5,
    )
    assert m.status == MissionStatus.IN_PROGRESS
    assert m.priority == MissionPriority.HIGH
    assert m.position == 1.5
    assert m.title == "Test APK audit"
