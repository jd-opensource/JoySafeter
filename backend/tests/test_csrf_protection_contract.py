"""CSRF protection contract for cookie-authenticated mutations.

The backend mints a ``csrf_token`` (double-submit cookie, non-HttpOnly) on
login/refresh, and the frontend echoes it back in the ``X-CSRF-Token`` header
on every authenticated request. Historically the backend NEVER verified it, so
any cookie-authenticated state-changing request was protected only by SameSite.
These tests pin the verification behaviour: a mutation that rides an ambient
session cookie must carry a valid, matching CSRF token or be rejected.
"""

import httpx
import pytest
from fastapi import FastAPI

from app.joysafeter_api.api.v1.middleware import CsrfProtectionMiddleware
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.security import create_csrf_token

pytestmark = pytest.mark.no_db


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CsrfProtectionMiddleware)

    @app.post("/api/v1/agents")
    async def create_agent() -> dict:
        return {"ok": True}

    @app.get("/api/v1/agents")
    async def list_agents() -> dict:
        return {"ok": True}

    @app.post("/api/v1/auth/sign-in/email")
    async def sign_in() -> dict:
        return {"ok": True}

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_cookie_authed_mutation_without_csrf_header_is_rejected():
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/v1/agents", cookies={settings.cookie_name: "session-value"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "CSRF_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_cookie_authed_mutation_with_matching_valid_csrf_passes():
    app = _app()
    token = create_csrf_token("user-1")
    async with _client(app) as client:
        resp = await client.post(
            "/api/v1/agents",
            cookies={settings.cookie_name: "session-value", "csrf_token": token},
            headers={"X-CSRF-Token": token},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_csrf_header_not_matching_cookie_is_rejected():
    app = _app()
    async with _client(app) as client:
        resp = await client.post(
            "/api/v1/agents",
            cookies={settings.cookie_name: "session-value", "csrf_token": create_csrf_token("user-1")},
            headers={"X-CSRF-Token": create_csrf_token("user-2")},  # different subject → different token
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_csrf_header_that_is_not_a_csrf_jwt_is_rejected():
    app = _app()
    # An attacker-controlled string equal in header+cookie must still fail the
    # signed-token check, so a mere cookie write on a sibling origin is not enough.
    async with _client(app) as client:
        resp = await client.post(
            "/api/v1/agents",
            cookies={settings.cookie_name: "session-value", "csrf_token": "not-a-jwt"},
            headers={"X-CSRF-Token": "not-a-jwt"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_header_authenticated_request_is_not_csrf_checked():
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/v1/agents", headers={"X-Api-Key": "jsk_live_whatever"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_safe_method_is_never_csrf_checked():
    app = _app()
    async with _client(app) as client:
        resp = await client.get("/api/v1/agents", cookies={settings.cookie_name: "session-value"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_anonymous_request_without_session_cookie_passes_through():
    # No ambient session → nothing to forge; downstream auth returns 401, not us.
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/v1/agents")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_session_bootstrap_endpoint_is_exempt():
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/v1/auth/sign-in/email", cookies={settings.cookie_name: "session-value"})
    assert resp.status_code == 200
