import httpx
import pytest

from app.joysafeter_api.api.v1 import secrets
from app.joysafeter_domain.schemas.joysafeter_secret import TestSecretRequest as SecretConnectivityRequest
from app.joysafeter_shared.common.app_errors import InvalidRequestError

pytestmark = pytest.mark.no_db


class FakeAsyncClient:
    captured: dict = {}
    response = httpx.Response(200, json={"ok": True})

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        FakeAsyncClient.captured["client_kwargs"] = self.kwargs
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, endpoint, *, headers, json):
        FakeAsyncClient.captured.update(
            {
                "endpoint": endpoint,
                "headers": headers,
                "json": json,
            }
        )
        return self.response


@pytest.mark.asyncio
async def test_secret_connectivity_openai_responses_uses_responses_endpoint(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setattr(secrets.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.captured = {}
    FakeAsyncClient.response = httpx.Response(200, json={"ok": True})

    result = await secrets._test_secret_connectivity(
        SecretConnectivityRequest(
            provider="codex",
            protocol="openai_responses",
            data={
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "http://127.0.0.1:9999/v1",
                "OPENAI_MODEL": "gpt-5.3-codex",
            },
        )
    )

    assert result.ok is True
    assert FakeAsyncClient.captured["endpoint"] == "http://127.0.0.1:9999/v1/responses"
    assert FakeAsyncClient.captured["headers"]["authorization"] == "Bearer sk-test"
    assert FakeAsyncClient.captured["json"] == {
        "model": "gpt-5.3-codex",
        "input": "ping",
        "max_output_tokens": secrets.SECRET_TEST_MAX_OUTPUT_TOKENS,
        "stream": False,
    }


@pytest.mark.asyncio
async def test_secret_connectivity_anthropic_preserves_prefix_and_uses_auth_token(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setattr(secrets.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.captured = {}
    FakeAsyncClient.response = httpx.Response(200, json={"ok": True})

    result = await secrets._test_secret_connectivity(
        SecretConnectivityRequest(
            provider="claude",
            protocol="anthropic_messages",
            data={
                "ANTHROPIC_AUTH_TOKEN": "anthropic-token",
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:9999/anthropic",
                "ANTHROPIC_MODEL": "claude-opus-4-20250514",
            },
        )
    )

    assert result.ok is True
    assert FakeAsyncClient.captured["endpoint"] == "http://127.0.0.1:9999/anthropic/v1/messages"
    assert FakeAsyncClient.captured["headers"]["authorization"] == "Bearer anthropic-token"
    assert "x-api-key" not in FakeAsyncClient.captured["headers"]
    assert FakeAsyncClient.captured["json"]["model"] == "claude-opus-4-20250514"
    assert FakeAsyncClient.captured["json"]["max_tokens"] == secrets.SECRET_TEST_MAX_OUTPUT_TOKENS


@pytest.mark.asyncio
async def test_secret_connectivity_returns_upstream_error_detail(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setattr(secrets.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.captured = {}
    FakeAsyncClient.response = httpx.Response(
        400,
        json={
            "error": {
                "message": "invalid model",
                "type": "invalid_request_error",
            }
        },
    )

    result = await secrets._test_secret_connectivity(
        SecretConnectivityRequest(
            provider="codex",
            protocol="openai_responses",
            data={
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "http://127.0.0.1:9999/v1",
                "OPENAI_MODEL": "gpt-5.5",
            },
        )
    )

    assert result.ok is False
    assert result.status == 400
    assert result.message == "invalid model"
    assert result.error_detail == '{"error":{"message":"invalid model","type":"invalid_request_error"}}'


@pytest.mark.asyncio
async def test_secret_connectivity_rejects_unallowlisted_llm_host(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "api.openai.com")

    with pytest.raises(InvalidRequestError) as exc_info:
        await secrets._test_secret_connectivity(
            SecretConnectivityRequest(
                provider="codex",
                protocol="openai_responses",
                data={
                    "OPENAI_API_KEY": "sk-test",
                    "OPENAI_BASE_URL": "https://evil.example.com/v1",
                },
            )
        )

    assert exc_info.value.code == "SECRET_TEST_BASE_URL_NOT_ALLOWED"
