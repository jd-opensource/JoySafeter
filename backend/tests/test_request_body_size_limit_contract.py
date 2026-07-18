"""Request body-size cap contract.

An external, multi-tenant API with file-upload endpoints must bound the memory a
single request can force a worker to buffer (and the size of the DB rows / Redis
fan-out a single call generates downstream). Without an outer cap, one oversized
body OOMs a worker. This pins the coarse guard: a request whose body exceeds the
configured limit is rejected with 413 before the application buffers it, whether
the size is declared via Content-Length or only revealed while streaming.
"""

import httpx
import pytest
from fastapi import FastAPI, Request

from app.joysafeter_api.api.v1.middleware import RequestBodySizeLimitMiddleware
from app.joysafeter_shared.common.exceptions import register_exception_handlers

pytestmark = pytest.mark.no_db

_LIMIT = 100


def _app(max_body_bytes: int = _LIMIT) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestBodySizeLimitMiddleware, max_body_bytes=max_body_bytes)

    @app.post("/api/v1/echo")
    async def echo(request: Request) -> dict:
        body = await request.body()
        return {"len": len(body)}

    @app.get("/api/v1/ping")
    async def ping() -> dict:
        return {"ok": True}

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_oversized_body_with_content_length_is_rejected():
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/v1/echo", content=b"x" * (_LIMIT + 1))
    assert resp.status_code == 413
    assert resp.json()["code"] == "REQUEST_BODY_TOO_LARGE"


@pytest.mark.asyncio
async def test_body_within_limit_passes():
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/v1/echo", content=b"x" * _LIMIT)
    assert resp.status_code == 200
    assert resp.json()["len"] == _LIMIT


@pytest.mark.asyncio
async def test_get_request_without_body_is_unaffected():
    app = _app()
    async with _client(app) as client:
        resp = await client.get("/api/v1/ping")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_oversized_streamed_body_without_content_length_is_rejected():
    """A chunked body (no Content-Length) that exceeds the cap while streaming
    must still be rejected — the Content-Length fast path must not be the only
    guard."""

    async def _chunks():
        for _ in range(10):
            yield b"x" * 50  # 500 bytes total, well over the 100-byte cap

    app = _app()
    async with _client(app) as client:
        resp = await client.post("/api/v1/echo", content=_chunks())
    assert resp.status_code == 413
    assert resp.json()["code"] == "REQUEST_BODY_TOO_LARGE"
