from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


@dataclass
class _Secret:
    id: str
    updated_at: datetime
    data: dict[str, str]


class _SecretService:
    secret: _Secret | None = None

    def __init__(self, db):
        self.db = db

    async def get_default_secret(self, project_id: str | None = None):
        self.project_id = project_id
        return self.secret

    def get_secret_data(self, secret):
        return dict(secret.data)


@pytest.fixture
def project_llm(monkeypatch):
    from app.everos.component.llm import project

    project.clear_project_llm_client_cache()
    _SecretService.secret = None
    monkeypatch.setattr(project, "AsyncSessionLocal", lambda: _SessionContext())
    monkeypatch.setattr(project, "SecretService", _SecretService)
    yield project
    project.clear_project_llm_client_cache()


async def test_project_llm_uses_active_openai_compatible_secret(
    project_llm, monkeypatch
):
    built = []

    def fake_build(settings):
        built.append(settings)
        return {"model": settings.model, "base_url": settings.base_url}

    monkeypatch.setattr(project_llm, "build_llm_provider", fake_build)
    _SecretService.secret = _Secret(
        id="secret-a",
        updated_at=datetime(2026, 7, 15, tzinfo=UTC),
        data={
            "OPENAI_API_KEY": "key-a",
            "OPENAI_BASE_URL": "https://api.a.test/v1",
            "OPENAI_MODEL": "model-a",
        },
    )

    client = await project_llm.get_project_llm_client("project-1")

    assert client == {"model": "model-a", "base_url": "https://api.a.test/v1"}
    assert built[0].model == "model-a"
    assert built[0].base_url == "https://api.a.test/v1"
    assert built[0].api_key.get_secret_value() == "key-a"


async def test_project_llm_uses_active_anthropic_secret(project_llm, monkeypatch):
    built = []

    class FakeAnthropicProvider:
        def __init__(self, *, model, api_key, base_url):
            built.append(
                {
                    "model": model,
                    "api_key": api_key,
                    "base_url": base_url,
                }
            )

    monkeypatch.setattr(project_llm, "AnthropicProvider", FakeAnthropicProvider)
    _SecretService.secret = _Secret(
        id="secret-anthropic",
        updated_at=datetime(2026, 7, 15, tzinfo=UTC),
        data={
            "ANTHROPIC_API_KEY": "anthropic-key",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.test",
            "ANTHROPIC_MODEL": "claude-test",
        },
    )

    client = await project_llm.get_project_llm_client("project-1")

    assert isinstance(client, FakeAnthropicProvider)
    assert built == [
        {
            "model": "claude-test",
            "api_key": "anthropic-key",
            "base_url": "https://api.anthropic.test",
        }
    ]


async def test_project_llm_cache_changes_when_active_secret_changes(
    project_llm, monkeypatch
):
    built = []

    def fake_build(settings):
        client = object()
        built.append((settings.model, client))
        return client

    monkeypatch.setattr(project_llm, "build_llm_provider", fake_build)
    now = datetime(2026, 7, 15, tzinfo=UTC)
    _SecretService.secret = _Secret(
        id="secret-a",
        updated_at=now,
        data={
            "OPENAI_API_KEY": "key-a",
            "OPENAI_BASE_URL": "https://api.a.test/v1",
            "OPENAI_MODEL": "model-a",
        },
    )

    first = await project_llm.get_project_llm_client("project-1")
    again = await project_llm.get_project_llm_client("project-1")

    _SecretService.secret = _Secret(
        id="secret-b",
        updated_at=now + timedelta(seconds=1),
        data={
            "OPENAI_API_KEY": "key-b",
            "OPENAI_BASE_URL": "https://api.b.test/v1",
            "OPENAI_MODEL": "model-b",
        },
    )
    second = await project_llm.get_project_llm_client("project-1")

    assert first is again
    assert second is not first
    assert [model for model, _client in built] == ["model-a", "model-b"]


async def test_project_llm_rejects_incomplete_active_secret_without_fallback(
    project_llm, monkeypatch
):
    fallback_called = False

    def fake_fallback():
        nonlocal fallback_called
        fallback_called = True
        return object()

    monkeypatch.setattr(project_llm, "get_llm_client", fake_fallback)
    _SecretService.secret = _Secret(
        id="secret-incomplete",
        updated_at=datetime(2026, 7, 15, tzinfo=UTC),
        data={
            "ANTHROPIC_MODEL": "claude-test",
        },
    )

    with pytest.raises(project_llm.IncompatibleProjectLLMSecretError):
        await project_llm.get_project_llm_client("project-1")

    assert fallback_called is False


async def test_project_llm_falls_back_to_settings_when_no_active_secret(
    project_llm, monkeypatch
):
    fallback_client = object()

    monkeypatch.setattr(project_llm, "get_llm_client", lambda: fallback_client)
    _SecretService.secret = None

    assert await project_llm.get_project_llm_client("project-1") is fallback_client


async def test_search_llm_resolver_threads_project_id(monkeypatch):
    search = importlib.import_module("app.everos.service.search")

    search._llm_client = None
    search._llm_resolved = False
    seen = []
    project_client = object()

    async def fake_project_client(project_id):
        seen.append(project_id)
        return project_client

    monkeypatch.setattr(search, "get_project_llm_client", fake_project_client)

    assert await search._get_llm_client(project_id="project-1") is project_client
    assert seen == ["project-1"]


async def test_memorize_llm_resolver_threads_project_id(monkeypatch):
    memorize = importlib.import_module("app.everos.service.memorize")

    seen = []
    project_client = object()

    async def fake_project_client(project_id):
        seen.append(project_id)
        return project_client

    monkeypatch.setattr(memorize, "get_project_llm_client", fake_project_client)

    assert await memorize._get_llm_client(project_id="project-1") is project_client
    assert seen == ["project-1"]


async def test_anthropic_provider_uses_messages_api_shape(monkeypatch):
    from app.everos.component.llm.anthropic_provider import AnthropicProvider
    from app.everos.component.llm.protocol import ChatMessage

    captured = {}

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "model": "claude-test",
                    "content": [{"type": "text", "text": "{\"ok\": true}"}],
                    "usage": {"input_tokens": 12, "output_tokens": 4},
                    "stop_reason": "end_turn",
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    provider = AnthropicProvider(
        model="claude-test",
        api_key="anthropic-key",
        base_url="https://api.anthropic.test",
    )

    response = await provider.chat(
        [ChatMessage(role="user", content="return json")],
        max_tokens=128,
    )

    assert captured["url"] == "https://api.anthropic.test/v1/messages"
    assert captured["headers"]["x-api-key"] == "anthropic-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["json"]["model"] == "claude-test"
    assert captured["json"]["messages"] == [
        {"role": "user", "content": "return json"}
    ]
    assert captured["json"]["max_tokens"] == 128
    assert response.content == "{\"ok\": true}"
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 4
    assert response.finish_reason == "stop"
