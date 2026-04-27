from __future__ import annotations

from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.common.exceptions import (
    BadRequestException,
    ModelConfigError,
    normalize_exception,
    register_exception_handlers,
)


def test_model_config_error_serializes_to_canonical_descriptor() -> None:
    exc = ModelConfigError(
        code="NODE_MODEL_NOT_CONFIGURED",
        message='Node "JSON 抽取子智能体" has no model configured.',
        detail='Node "JSON 抽取子智能体" in agent "a-1" has no model configured.',
        source="node",
        retryable=False,
        user_action="configure_model",
        context={"node_name": "JSON 抽取子智能体", "agent_id": "a-1"},
    )

    payload = exc.to_error_descriptor(http_status=status.HTTP_400_BAD_REQUEST)

    assert payload == {
        "code": "NODE_MODEL_NOT_CONFIGURED",
        "message": 'Node "JSON 抽取子智能体" has no model configured.',
        "detail": 'Node "JSON 抽取子智能体" in agent "a-1" has no model configured.',
        "source": "node",
        "retryable": False,
        "user_action": "configure_model",
        "context": {
            "http_status": 400,
            "node_name": "JSON 抽取子智能体",
            "agent_id": "a-1",
        },
    }


def test_normalize_runtime_error_maps_to_internal_unexpected_error() -> None:
    payload = normalize_exception(RuntimeError("boom")).to_error_descriptor(http_status=500)

    assert payload["code"] == "INTERNAL_UNEXPECTED_ERROR"
    assert payload["source"] == "internal"
    assert payload["retryable"] is False
    assert payload["context"]["http_status"] == 500


def test_bad_request_exception_preserves_structured_fields() -> None:
    exc = BadRequestException(
        message="Invalid request",
        code="VALIDATION_INVALID_REQUEST",
        detail="The request body is malformed.",
        source="validation",
        retryable=False,
        user_action="fix_input",
    )

    payload = exc.to_error_descriptor(http_status=400)

    assert payload["code"] == "VALIDATION_INVALID_REQUEST"
    assert payload["user_action"] == "fix_input"
    assert payload["detail"] == "The request body is malformed."


def test_model_config_error_legacy_error_code_alias_preserves_params_and_descriptor() -> None:
    exc = ModelConfigError(
        error_code="MODEL_NOT_FOUND",
        message='Model "gpt-x" is not registered.',
        params={"model": "gpt-x", "provider": "openai"},
    )

    payload = exc.to_error_descriptor(http_status=400)

    assert exc.error_code == "MODEL_NOT_FOUND"
    assert exc.params == {"model": "gpt-x", "provider": "openai"}
    assert exc.data == {
        "error_code": "MODEL_NOT_FOUND",
        "params": {"model": "gpt-x", "provider": "openai"},
    }
    assert payload["code"] == "MODEL_NOT_FOUND"
    assert payload["context"] == {
        "http_status": 400,
        "model": "gpt-x",
        "provider": "openai",
    }


def test_app_exception_handler_returns_error_envelope() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise BadRequestException(
            message="Invalid request",
            code="VALIDATION_INVALID_REQUEST",
            detail="The request body is malformed.",
            source="validation",
            retryable=False,
            user_action="fix_input",
        )

    client = TestClient(app)
    response = client.get("/boom")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {
        "success": False,
        "error": {
            "code": "VALIDATION_INVALID_REQUEST",
            "message": "Invalid request",
            "detail": "The request body is malformed.",
            "source": "validation",
            "retryable": False,
            "user_action": "fix_input",
            "context": {"http_status": 400},
        },
    }


def test_unauthorized_exception_preserves_headers_and_canonical_envelope() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/unauthorized")
    async def unauthorized() -> None:
        from app.common.exceptions import UnauthorizedException

        raise UnauthorizedException("Authentication required")

    client = TestClient(app)
    response = client.get("/unauthorized")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {
        "success": False,
        "error": {
            "code": "401",
            "message": "Authentication required",
            "source": "auth",
            "retryable": False,
            "context": {"http_status": 401},
        },
    }


def test_plain_http_exception_429_maps_to_retryable_descriptor() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/limited")
    async def limited() -> None:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")

    client = TestClient(app)
    response = client.get("/limited")

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.json() == {
        "success": False,
        "error": {
            "code": "429",
            "message": "Too many requests",
            "source": "api",
            "retryable": True,
            "context": {"http_status": 429},
        },
    }
