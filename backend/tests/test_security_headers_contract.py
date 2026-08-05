"""Security response headers must be present on API responses.

An external, browser-reachable API should send the standard hardening headers so
a response cannot be MIME-sniffed, framed for clickjacking, or leak the full
referrer. HSTS is only emitted in a secure (HTTPS) context so it never forces
https on http://localhost during development.
"""

import httpx
import pytest
from fastapi import FastAPI

from app.joysafeter_api.api.v1.middleware import SecurityHeadersMiddleware

pytestmark = pytest.mark.no_db


def _app(hsts: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)

    @app.get("/api/v1/x")
    async def x() -> dict:
        return {"ok": True}

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_core_security_headers_present():
    app = _app()
    async with _client(app) as client:
        resp = await client.get("/api/v1/x")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["X-Permitted-Cross-Domain-Policies"] == "none"


@pytest.mark.asyncio
async def test_hsts_present_only_when_enabled():
    app = _app(hsts=True)
    async with _client(app) as client:
        resp = await client.get("/api/v1/x")
    assert "max-age=" in resp.headers["Strict-Transport-Security"]


@pytest.mark.asyncio
async def test_hsts_absent_when_disabled():
    app = _app(hsts=False)
    async with _client(app) as client:
        resp = await client.get("/api/v1/x")
    assert "Strict-Transport-Security" not in resp.headers
