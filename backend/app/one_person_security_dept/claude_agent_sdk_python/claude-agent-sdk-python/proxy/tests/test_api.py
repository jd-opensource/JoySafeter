from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from fastapi.testclient import TestClient

from proxy.app import create_app
from proxy.config import ProxySettings


def _make_app_with_handler(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    settings_overrides: dict[str, Any] | None = None,
):
    settings_overrides = settings_overrides or {}
    settings_kwargs = {
        "openai_base_url": "https://mock.openai",
        "model_map": {"claude-sonnet-4-6": "Kimi-K2.5"},
        "fallback_models": [],
        "default_max_tokens": 4096,
        "upstream_timeout_seconds": 10,
        "log_level": "DEBUG",
    }
    settings_kwargs.update(settings_overrides)
    settings = ProxySettings(
        **settings_kwargs,
    )
    transport = httpx.MockTransport(handler)
    return create_app(settings=settings, upstream_transport=transport)


def test_messages_non_streaming_end_to_end() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        captured["authorization"] = request.headers.get("authorization")
        payload = json.loads(request.content.decode("utf-8"))
        captured["payload"] = payload
        return httpx.Response(
            status_code=200,
            json={
                "id": "chatcmpl-1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "pong"},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    app = _make_app_with_handler(handler)
    client = TestClient(app)

    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "sk-test"},
        json={
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Reply pong"}],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "message"
    assert data["stop_reason"] == "end_turn"
    assert data["usage"] == {"input_tokens": 4, "output_tokens": 2}
    assert captured["authorization"] == "Bearer sk-test"
    assert captured["payload"]["model"] == "Kimi-K2.5"


def test_messages_streaming_end_to_end() -> None:
    stream_body = "".join(
        [
            'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}\n\n',
            'data: {"choices":[{"delta":{"content":"pong"},"finish_reason":null}]}\n\n',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n',
            "data: [DONE]\n\n",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            text=stream_body,
        )

    app = _make_app_with_handler(handler)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/messages",
        headers={"x-api-key": "sk-stream"},
        json={
            "model": "claude-sonnet-4-6",
            "stream": True,
            "messages": [{"role": "user", "content": "Reply pong"}],
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: message_start" in body
    assert "event: message_delta" in body
    assert "event: message_stop" in body
    assert '"stop_reason": "end_turn"' in body


def test_models_endpoint_converts_and_uses_bearer_token() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {"id": "Kimi-K2.5", "object": "model", "created": 1700000000},
                    {"id": "Kimi-Vision", "object": "model", "created": 1700000010},
                ]
            },
        )

    app = _make_app_with_handler(handler)
    client = TestClient(app)

    response = client.get("/v1/models", headers={"authorization": "Bearer sk-models"})

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2
    assert data["data"][0]["id"] == "Kimi-K2.5"
    assert data["data"][0]["display_name"] == "Kimi-K2.5"
    assert captured["authorization"] == "Bearer sk-models"


def test_upstream_error_is_mapped_to_anthropic_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=401, json={"error": {"message": "invalid key"}})

    app = _make_app_with_handler(handler)
    client = TestClient(app)

    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "sk-bad"},
        json={
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["type"] == "error"
    assert payload["error"]["type"] == "api_error"
    assert payload["error"]["message"] == "invalid key"


def test_models_endpoint_uses_fallback_models_on_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=400, json={"error": {"message": "参数解析失败"}})

    fallback_models = [
        {"id": "Kimi-K2.5", "type": "model", "display_name": "Kimi-K2.5"},
        {"id": "Kimi-Vision", "type": "model", "display_name": "Kimi-Vision"},
    ]

    app = _make_app_with_handler(
        handler,
        settings_overrides={"fallback_models": fallback_models},
    )
    client = TestClient(app)

    response = client.get("/v1/models", headers={"x-api-key": "sk-fallback"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_more"] is False
    assert payload["data"] == fallback_models
