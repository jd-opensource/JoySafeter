from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.exceptions import register_exception_handlers
from app.core.database import get_db
from app.models.auth import AuthUser as User


def _load_openclaw_devices_router():
    module_path = Path(__file__).resolve().parents[2] / "app/api/v1/openclaw_devices.py"
    spec = importlib.util.spec_from_file_location("openclaw_devices_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.router


router = _load_openclaw_devices_router()


async def mock_get_current_user():
    user = MagicMock(spec=User)
    user.id = "user-123"
    return user


async def mock_get_db():
    yield AsyncMock()


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.include_router(router)
    register_exception_handlers(test_app)

    from app.common.dependencies import get_current_user

    test_app.dependency_overrides[get_current_user] = mock_get_current_user
    test_app.dependency_overrides[get_db] = mock_get_db

    with TestClient(test_app) as c:
        yield c


@patch("openclaw_devices_under_test.OpenClawInstanceService")
def test_list_devices_requires_running_instance(
    mock_service_cls,
    client: TestClient,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_instance_by_user = AsyncMock(return_value=None)

    response = client.get("/v1/openclaw/devices")

    assert response.status_code == 400
    assert response.json() == {
        "success": False,
        "error": {
            "code": "OPENCLAW_INSTANCE_NOT_RUNNING",
            "message": "No running instance",
            "data": None,
        },
    }


@patch("openclaw_devices_under_test._docker_exec", new_callable=AsyncMock)
@patch("openclaw_devices_under_test.OpenClawInstanceService")
def test_list_devices_docker_failure_returns_canonical_error(
    mock_service_cls,
    mock_docker_exec,
    client: TestClient,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_instance_by_user = AsyncMock(
        return_value=SimpleNamespace(status="running", container_id="ctr-1")
    )
    mock_docker_exec.side_effect = RuntimeError("Container ctr-1 not found")

    response = client.get("/v1/openclaw/devices")

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "error": {
            "code": "OPENCLAW_DEVICE_LIST_FAILED",
            "message": "Container ctr-1 not found",
            "data": None,
        },
    }
