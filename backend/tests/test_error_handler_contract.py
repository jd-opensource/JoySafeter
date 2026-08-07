import json
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.testclient import TestClient

from app.joysafeter_shared.common.app_errors import ServiceUnavailableError
from app.joysafeter_shared.common.exceptions import app_error_handler, http_exception_handler
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.runtime.app_factory import create_app

pytestmark = pytest.mark.no_db


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/v1/tasks", "headers": []})


@pytest.mark.asyncio
async def test_structured_http_exception_survives_exception_handler():
    exc = HTTPException(
        status_code=429,
        detail={
            "code": "PROJECT_TASK_LIMIT_EXCEEDED",
            "message": "Project has reached its concurrent task limit (1).",
            "data": {"limit": 1, "active": 1, "project_id": "project-1"},
            "source": "api",
            "retryable": True,
            "user_action": "retry",
        },
        headers={"Retry-After": "5"},
    )

    response = await http_exception_handler(_request(), exc)
    payload = json.loads(response.body)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "5"
    assert payload == {
        "code": "PROJECT_TASK_LIMIT_EXCEEDED",
        "message": "Project has reached its concurrent task limit (1).",
        "data": {"limit": 1, "active": 1, "project_id": "project-1"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }


@pytest.mark.asyncio
async def test_semantic_app_error_matches_exception_handler_contract():
    exc = ServiceUnavailableError(
        code="SESSION_SANDBOX_DESTROY_FAILED",
        message="Session could not be deleted because its sandbox cleanup failed.",
        data={"session_id": "session-1", "sandbox_id": "sandbox-1"},
        source="runtime",
        retryable=True,
        user_action="retry",
    )

    response = await app_error_handler(_request(), exc)
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload == {
        "code": "SESSION_SANDBOX_DESTROY_FAILED",
        "message": "Session could not be deleted because its sandbox cleanup failed.",
        "data": {"session_id": "session-1", "sandbox_id": "sandbox-1"},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def test_unhandled_exception_500_keeps_cors_header():
    """A raw unhandled exception must still yield a CORS-headed 500.

    Regression guard: Starlette routes the catch-all Exception handler through
    ServerErrorMiddleware (outermost, above CORSMiddleware), so without the
    inner ExceptionHandlingMiddleware the 500 response has no
    Access-Control-Allow-Origin header and the browser reports a misleading
    CORS / net::ERR_FAILED error that hides the real backend failure.
    """
    origin = "http://localhost:3000"
    assert origin in settings.cors_origins

    app = create_app(lifespan=_noop_lifespan)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == origin
    payload = response.json()
    assert payload["code"] == "INTERNAL_ERROR"
