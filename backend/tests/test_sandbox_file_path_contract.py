from __future__ import annotations

import pytest

from app.joysafeter_api.api.v1.sessions import _validate_sandbox_file_path
from app.joysafeter_shared.common.app_errors import InvalidRequestError


def test_sandbox_file_path_defaults_to_workspace() -> None:
    assert _validate_sandbox_file_path(None) == "/workspace"
    assert _validate_sandbox_file_path("reports/result.md") == "/workspace/reports/result.md"


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/.claude.json",
        "/workspace/.cache/token.json",
        "/workspace/artifacts/.secret",
        ".hidden",
        "artifacts/.secret",
    ],
)
def test_sandbox_file_path_rejects_hidden_entries(path: str) -> None:
    with pytest.raises(InvalidRequestError) as exc_info:
        _validate_sandbox_file_path(path)

    assert exc_info.value.code == "SANDBOX_FILE_PATH_HIDDEN"
