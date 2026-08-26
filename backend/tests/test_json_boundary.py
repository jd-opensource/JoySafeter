from datetime import date, datetime, timezone
from enum import Enum

import pytest

from app.joysafeter_shared.ids import ProjectId, UserId
from app.joysafeter_shared.json_boundary import JsonBoundaryTypeError, normalize_json_value

pytestmark = pytest.mark.no_db


class _State(str, Enum):
    READY = "ready"


def test_normalize_json_value_converts_only_supported_boundary_types() -> None:
    user_id = UserId.new()
    project_id = ProjectId.new()
    occurred_at = datetime(2026, 8, 25, 9, 30, tzinfo=timezone.utc)

    assert normalize_json_value(
        {
            "user_id": user_id,
            "nested": [project_id, _State.READY, date(2026, 8, 25), occurred_at],
        }
    ) == {
        "user_id": str(user_id),
        "nested": [str(project_id), "ready", "2026-08-25", "2026-08-25T09:30:00+00:00"],
    }


@pytest.mark.parametrize("value", [object(), {1: "non-string-key"}, float("nan"), float("inf")])
def test_normalize_json_value_rejects_unsupported_values(value: object) -> None:
    with pytest.raises(JsonBoundaryTypeError):
        normalize_json_value(value)
