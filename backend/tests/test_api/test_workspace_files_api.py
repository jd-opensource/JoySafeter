from __future__ import annotations

import importlib.util
import io
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.exceptions import register_exception_handlers
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole


def _load_workspace_files_router():
    module_path = Path(__file__).resolve().parents[2] / "app/api/v1/workspace_files.py"
    spec = importlib.util.spec_from_file_location("workspace_files_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workspace_files_module = _load_workspace_files_router()
router = workspace_files_module.router


async def mock_get_db():
    yield AsyncMock()


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.include_router(router)
    register_exception_handlers(test_app)
    test_app.dependency_overrides[get_db] = mock_get_db

    from app.common.dependencies import get_current_user_optional

    async def current_user_optional_override():
        return None

    test_app.dependency_overrides[get_current_user_optional] = current_user_optional_override

    for route in test_app.routes:
        dependency = getattr(route, "dependant", None)
        if dependency is None:
            continue
        for dep in dependency.dependencies:
            call = getattr(dep, "call", None)
            if callable(call) and getattr(call, "__name__", "") == "checker":
                async def workspace_user_override() -> User:
                    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=False)
                    return user  # type: ignore[return-value]

                test_app.dependency_overrides[call] = workspace_user_override

    with TestClient(test_app) as c:
        yield c


@pytest.mark.parametrize(
    ("filename", "expected_status", "expected_error"),
    [
        (
            "report.txt",
            409,
            {
                "code": "WORKSPACE_FILE_DUPLICATE",
                "message": 'A file named "report.txt" already exists in this workspace',
                "data": {"file_name": "report.txt"},
            },
        ),
        (
            "empty.txt",
            400,
            {
                "code": "WORKSPACE_FILE_EMPTY",
                "message": "File is empty",
                "data": None,
            },
        ),
    ],
)
def test_upload_workspace_file_returns_canonical_error_contract(
    client: TestClient,
    filename: str,
    expected_status: int,
    expected_error: dict[str, object],
) -> None:
    service = AsyncMock()
    if filename == "report.txt":
        from app.common.app_errors import ResourceConflictError

        service.upload_file.side_effect = ResourceConflictError(
            'A file named "report.txt" already exists in this workspace',
            code="WORKSPACE_FILE_DUPLICATE",
            data={"file_name": "report.txt"},
        )
    else:
        from app.common.app_errors import InvalidRequestError

        service.upload_file.side_effect = InvalidRequestError("File is empty", code="WORKSPACE_FILE_EMPTY")

    workspace_files_module.WorkspaceFileService = MagicMock(return_value=service)

    response = client.post(
        f"/v1/workspaces/{uuid.uuid4()}/files",
        files={"file": (filename, io.BytesIO(b"content" if filename == "report.txt" else b""), "text/plain")},
    )

    assert response.status_code == expected_status
    assert response.json() == {
        "success": False,
        "error": expected_error,
    }


def test_serve_workspace_file_requires_auth_or_valid_token(client: TestClient) -> None:
    service = AsyncMock()
    from app.common.app_errors import AuthenticationError

    service.validate_token_or_user.side_effect = AuthenticationError(
        "Authentication required",
        code="AUTH_REQUIRED",
    )
    workspace_files_module.WorkspaceFileService = MagicMock(return_value=service)

    response = client.get(f"/v1/workspaces/{uuid.uuid4()}/files/{uuid.uuid4()}/serve")

    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "Authentication required",
            "data": None,
        },
    }
