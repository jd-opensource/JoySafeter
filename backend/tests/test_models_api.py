"""
Tests for models API — PATCH instances/{id}, GET overview, unavailable_reason.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.models import router
from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    test_app.dependency_overrides[get_current_user] = mock_get_current_user
    test_app.dependency_overrides[get_db] = mock_get_db
    with TestClient(test_app) as c:
        yield c


def _make_instance(instance_id: str | None = None) -> dict:
    return {
        "id": instance_id or str(uuid.uuid4()),
        "provider_name": "anthropic",
        "model_name": "claude-3-5-sonnet",
        "model_type": "chat",
        "model_parameters": {"temperature": 0.7},
    }


def _make_overview() -> dict:
    return {
        "total_providers": 3,
        "healthy_providers": 2,
        "unhealthy_providers": 0,
        "unconfigured_providers": 1,
        "total_models": 10,
        "available_models": 8,
        "recent_credential_failure": None,
    }


# ---------------------------------------------------------------------------
# GET /overview
# ---------------------------------------------------------------------------


@patch("app.api.v1.models.ModelService")
def test_get_overview_returns_200(mock_cls, client: TestClient):
    mock_svc = mock_cls.return_value
    mock_svc.get_overview = AsyncMock(return_value=_make_overview())

    resp = client.get("/v1/models/overview")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_providers"] == 3
    assert data["healthy_providers"] == 2


# ---------------------------------------------------------------------------
# GET / — list models with unavailable_reason
# ---------------------------------------------------------------------------


@patch("app.api.v1.models.ModelService")
def test_list_models_includes_unavailable_reason(mock_cls, client: TestClient):
    models = [
        {
            "provider_name": "anthropic",
            "provider_display_name": "Anthropic",
            "name": "claude-3-5-sonnet",
            "display_name": "Claude 3.5 Sonnet",
            "description": "",
            "is_available": False,
            "unavailable_reason": "no_credentials",
        }
    ]
    mock_svc = mock_cls.return_value
    mock_svc.get_available_models = AsyncMock(return_value=models)

    resp = client.get("/v1/models?model_type=chat")

    assert resp.status_code == 200
    item = resp.json()["data"][0]
    assert item["is_available"] is False
    assert item["unavailable_reason"] == "no_credentials"


# ---------------------------------------------------------------------------
# PATCH /instances/{id} — update model instance
# ---------------------------------------------------------------------------


@patch("app.api.v1.models.ModelService")
def test_patch_instance_updates_parameters(mock_cls, client: TestClient):
    instance_id = str(uuid.uuid4())
    updated = _make_instance(instance_id)
    updated["model_parameters"] = {"temperature": 0.9}

    mock_svc = mock_cls.return_value
    mock_svc.update_model_instance = AsyncMock(return_value=updated)

    resp = client.patch(
        f"/v1/models/instances/{instance_id}",
        json={"model_parameters": {"temperature": 0.9}},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["model_parameters"]["temperature"] == 0.9
    mock_svc.update_model_instance.assert_called_once()


@patch("app.api.v1.models.ModelService")
def test_patch_instance_not_found_returns_404(mock_cls, client: TestClient):
    from app.common.exceptions import NotFoundException

    mock_svc = mock_cls.return_value
    mock_svc.update_model_instance = AsyncMock(side_effect=NotFoundException("模型实例不存在"))

    resp = client.patch(
        f"/v1/models/instances/{uuid.uuid4()}",
        json={"model_parameters": {}},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth — no token returns 401
# ---------------------------------------------------------------------------


def test_list_models_without_auth_returns_401():
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = mock_get_db
    with TestClient(test_app, raise_server_exceptions=False) as c:
        resp = c.get("/v1/models")
    assert resp.status_code == 401


def test_get_overview_without_auth_returns_401():
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = mock_get_db
    with TestClient(test_app, raise_server_exceptions=False) as c:
        resp = c.get("/v1/models/overview")
    assert resp.status_code == 401


def test_patch_instance_without_auth_returns_401():
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = mock_get_db
    with TestClient(test_app, raise_server_exceptions=False) as c:
        resp = c.patch(f"/v1/models/instances/{uuid.uuid4()}", json={})
    assert resp.status_code == 401
