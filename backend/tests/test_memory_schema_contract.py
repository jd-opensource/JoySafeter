import pytest
from pydantic import ValidationError

from app.joysafeter_domain.schemas.joysafeter_memory import UpdateMemoryRequest

pytestmark = pytest.mark.no_db


def test_update_memory_accepts_structured_precondition() -> None:
    request = UpdateMemoryRequest(content="updated", precondition={"content_sha256": "abc"})

    assert request.precondition == {"content_sha256": "abc"}


def test_update_memory_rejects_removed_if_sha256_field() -> None:
    with pytest.raises(ValidationError):
        UpdateMemoryRequest(content="updated", if_sha256="abc")
