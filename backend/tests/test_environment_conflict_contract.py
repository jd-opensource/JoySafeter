import pytest

from app.joysafeter_api.api.v1.environments import _environment_conflict_error
from app.joysafeter_domain.services.joysafeter_environment_service import (
    EnvironmentActiveSessionConflict,
    EnvironmentActiveTaskConflict,
    EnvironmentAgentReferenceConflict,
    EnvironmentTriggerReferenceConflict,
)
from app.joysafeter_shared.ids import EnvironmentId, TaskId

pytestmark = pytest.mark.no_db


def test_environment_active_task_conflict_keeps_task_identity_typed() -> None:
    environment_id = EnvironmentId.new()
    task_id = TaskId.new()
    conflict = EnvironmentActiveTaskConflict(
        task_id=task_id,
        source="agent environment_id",
        action="archiving",
    )

    assert conflict.task_id is task_id
    error = _environment_conflict_error(environment_id, conflict)
    assert error.code == "ENVIRONMENT_ACTIVE_TASK"
    assert error.data == {
        "environment_id": str(environment_id),
        "task_id": str(task_id),
        "source": "agent environment_id",
    }
    assert str(conflict) == (
        f"Environment is required by active task '{task_id}' via agent environment_id. "
        "Stop or wait for the task before archiving."
    )


@pytest.mark.parametrize(
    ("conflict", "code", "data"),
    (
        (
            EnvironmentAgentReferenceConflict("Agent One"),
            "ENVIRONMENT_AGENT_REFERENCE",
            {"agent_name": "Agent One"},
        ),
        (
            EnvironmentTriggerReferenceConflict("Nightly"),
            "ENVIRONMENT_TRIGGER_REFERENCE",
            {"trigger_name": "Nightly"},
        ),
        (
            EnvironmentActiveSessionConflict(),
            "ENVIRONMENT_ACTIVE_SESSION_REFERENCE",
            {},
        ),
    ),
)
def test_environment_reference_conflicts_are_structured(conflict, code: str, data: dict[str, str]) -> None:
    environment_id = EnvironmentId.new()

    error = _environment_conflict_error(environment_id, conflict)

    assert error.code == code
    assert error.data == {"environment_id": str(environment_id), **data}
