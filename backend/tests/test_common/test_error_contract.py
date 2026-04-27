from __future__ import annotations

from fastapi import FastAPI, Query, status
from fastapi.testclient import TestClient

from app.common.app_errors import AuthenticationError, DomainError
from app.common.exceptions import normalize_exception, register_exception_handlers


def test_domain_error_becomes_canonical_http_error() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise DomainError(
            code="USER_NOT_FOUND",
            message="用户不存在",
            data={"user_id": "u-1"},
        )

    client = TestClient(app)
    response = client.get("/boom")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {
        "success": False,
        "error": {
            "code": "USER_NOT_FOUND",
            "message": "用户不存在",
            "data": {"user_id": "u-1"},
        },
    }


def test_auth_error_preserves_headers_with_canonical_payload() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/auth")
    async def auth() -> None:
        raise AuthenticationError(message="认证已失效", code="AUTH_REQUIRED")

    client = TestClient(app)
    response = client.get("/auth")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {
        "success": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "认证已失效",
            "data": None,
        },
    }


def test_authentication_error_codes_are_preserved_without_transport_rewrite() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/missing")
    async def missing() -> None:
        raise AuthenticationError(message="缺少凭证", code="MISSING_CREDENTIALS")

    client = TestClient(app)
    response = client.get("/missing")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {
        "success": False,
        "error": {
            "code": "MISSING_CREDENTIALS",
            "message": "缺少凭证",
            "data": None,
        },
    }


def test_request_validation_exception_becomes_canonical_payload() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/validate")
    async def validate(count: int = Query(...)) -> None:
        _ = count

    client = TestClient(app)
    response = client.get("/validate", params={"count": "bad"})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert response.json()["error"]["message"] == "请求参数校验失败"
    assert response.json()["error"]["data"]["errors"][0]["field"] == "query.count"


def test_normalize_exception_maps_runtime_error_to_internal_error() -> None:
    payload = normalize_exception(RuntimeError("boom")).to_payload()

    assert payload == {
        "code": "INTERNAL_ERROR",
        "message": "内部错误",
        "data": None,
    }
