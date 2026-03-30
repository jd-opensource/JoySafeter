"""
Tests for model_providers API — PATCH defaults, auth, 404 handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.model_providers import router
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


def _make_provider(name: str = "anthropic") -> dict:
    return {
        "provider_name": name,
        "display_name": "Anthropic",
        "supported_model_types": ["chat"],
        "credential_schema": {},
        "config_schemas": {},
        "model_count": 3,
        "default_parameters": {"temperature": 0.7},
        "is_template": False,
        "provider_type": "system",
        "template_name": None,
        "is_enabled": True,
    }


# ---------------------------------------------------------------------------
# GET / — list providers
# ---------------------------------------------------------------------------


@patch("app.api.v1.model_providers.ModelProviderService")
def test_list_providers_returns_200(mock_cls, client: TestClient):
    mock_svc = mock_cls.return_value
    mock_svc.get_all_providers = AsyncMock(return_value=[_make_provider()])

    resp = client.get("/v1/model-providers")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["provider_name"] == "anthropic"
    assert data[0]["default_parameters"] == {"temperature": 0.7}


# ---------------------------------------------------------------------------
# GET /{name} — get single provider
# ---------------------------------------------------------------------------


@patch("app.api.v1.model_providers.ModelProviderService")
def test_get_provider_returns_200(mock_cls, client: TestClient):
    mock_svc = mock_cls.return_value
    mock_svc.get_provider = AsyncMock(return_value=_make_provider())

    resp = client.get("/v1/model-providers/anthropic")

    assert resp.status_code == 200
    assert resp.json()["data"]["provider_name"] == "anthropic"


@patch("app.api.v1.model_providers.ModelProviderService")
def test_get_provider_not_found_returns_404(mock_cls, client: TestClient):
    mock_svc = mock_cls.return_value
    mock_svc.get_provider = AsyncMock(return_value=None)

    resp = client.get("/v1/model-providers/nonexistent")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /{name}/defaults — update default parameters
# ---------------------------------------------------------------------------


@patch("app.api.v1.model_providers.ModelProviderService")
def test_patch_defaults_returns_updated_provider(mock_cls, client: TestClient):
    updated = _make_provider()
    updated["default_parameters"] = {"temperature": 0.9, "max_tokens": 4096}

    mock_svc = mock_cls.return_value
    mock_svc.update_provider_defaults = AsyncMock(return_value=updated)

    resp = client.patch(
        "/v1/model-providers/anthropic/defaults",
        json={"default_parameters": {"temperature": 0.9, "max_tokens": 4096}},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["default_parameters"]["temperature"] == 0.9
    assert data["default_parameters"]["max_tokens"] == 4096
    mock_svc.update_provider_defaults.assert_called_once_with(
        "anthropic", {"temperature": 0.9, "max_tokens": 4096}
    )


@patch("app.api.v1.model_providers.ModelProviderService")
def test_patch_defaults_provider_not_found_returns_404(mock_cls, client: TestClient):
    from app.common.exceptions import NotFoundException

    mock_svc = mock_cls.return_value
    mock_svc.update_provider_defaults = AsyncMock(
        side_effect=NotFoundException("供应商不存在: nonexistent")
    )

    resp = client.patch(
        "/v1/model-providers/nonexistent/defaults",
        json={"default_parameters": {"temperature": 0.5}},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth — no token returns 401
# ---------------------------------------------------------------------------


def test_list_providers_without_auth_returns_401():
    test_app = FastAPI()
    test_app.include_router(router)
    # No dependency override — real auth dependency will reject missing token
    test_app.dependency_overrides[get_db] = mock_get_db
    with TestClient(test_app, raise_server_exceptions=False) as c:
        resp = c.get("/v1/model-providers")
    assert resp.status_code == 401


def test_patch_defaults_without_auth_returns_401():
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = mock_get_db
    with TestClient(test_app, raise_server_exceptions=False) as c:
        resp = c.patch(
            "/v1/model-providers/anthropic/defaults",
            json={"default_parameters": {}},
        )
    assert resp.status_code == 401
