import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.joysafeter_api.api.v1 import oauth as oauth_api
from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_shared.common.exceptions import register_exception_handlers

pytestmark = pytest.mark.no_db


def test_federation_api_maps_facade_state_store_failure_without_leaking_detail(monkeypatch) -> None:
    class _Coordinator:
        async def begin_login(self, command, context):
            del command, context
            raise FederationError(
                code="FEDERATION_STATE_STORE_UNAVAILABLE",
                message="redis connection reset secret-host.internal",
            )

    monkeypatch.setattr(oauth_api, "build_federated_login_coordinator", lambda _db: _Coordinator(), raising=False)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(oauth_api.router, prefix="/api/v1/auth/oauth")
    app.dependency_overrides[oauth_api.get_db] = lambda: object()

    response = TestClient(app).get("/api/v1/auth/oauth/github")

    assert response.status_code == 503
    assert response.json()["code"] == "FEDERATION_STATE_STORE_UNAVAILABLE"
    assert "secret-host" not in response.text
