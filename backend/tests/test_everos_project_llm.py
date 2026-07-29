from __future__ import annotations

import importlib
import inspect
import sys
import types
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from app.everos.memory.events import EpisodeExtracted


class _StructuredOutput(BaseModel):
    subject: str
    content: str


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


async def test_project_llm_uses_active_openai_compatible_secret(project_llm, monkeypatch):
    from app.everos.component.llm.structured import JSONRepairingLLMClient

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

    assert isinstance(client, JSONRepairingLLMClient)
    assert client._delegate == {
        "model": "model-a",
        "base_url": "https://api.a.test/v1",
    }
    assert built[0].model == "model-a"
    assert built[0].base_url == "https://api.a.test/v1"
    assert built[0].api_key.get_secret_value() == "key-a"


async def test_project_llm_resolves_secret_with_stable_id_from_everos_scope(project_llm, monkeypatch):
    seen_project_ids = []

    class CapturingSecretService(_SecretService):
        async def get_default_secret(self, project_id: str | None = None):
            seen_project_ids.append(project_id)
            return self.secret

    monkeypatch.setattr(project_llm, "SecretService", CapturingSecretService)
    monkeypatch.setattr(
        project_llm,
        "build_llm_provider",
        lambda settings: {"model": settings.model},
    )
    _SecretService.secret = _Secret(
        id="secret-a",
        updated_at=datetime(2026, 7, 15, tzinfo=UTC),
        data={
            "OPENAI_API_KEY": "key-a",
            "OPENAI_BASE_URL": "https://api.a.test/v1",
            "OPENAI_MODEL": "model-a",
        },
    )

    await project_llm.get_project_llm_client("test__55c665e3-5fe7-4e26-a11b-e6bf095d1a07")

    assert seen_project_ids == ["55c665e3-5fe7-4e26-a11b-e6bf095d1a07"]


async def test_project_llm_uses_active_anthropic_secret(project_llm, monkeypatch):
    from app.everos.component.llm.structured import JSONRepairingLLMClient

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

    assert isinstance(client, JSONRepairingLLMClient)
    assert isinstance(client._delegate, FakeAnthropicProvider)
    assert built == [
        {
            "model": "claude-test",
            "api_key": "anthropic-key",
            "base_url": "https://api.anthropic.test",
        }
    ]


async def test_project_llm_cache_changes_when_active_secret_changes(project_llm, monkeypatch):
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


async def test_project_llm_rejects_incomplete_active_secret_without_fallback(project_llm, monkeypatch):
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


async def test_project_llm_falls_back_to_settings_when_no_active_secret(project_llm, monkeypatch):
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


async def test_ome_atomic_fact_strategy_uses_project_llm(monkeypatch):
    strategy = importlib.import_module("app.everos.memory.strategies.extract_atomic_facts")

    seen_project_ids = []
    project_client = object()
    extractor_clients = []

    async def fake_project_client(project_id):
        seen_project_ids.append(project_id)
        return project_client

    def fail_global_client():
        raise AssertionError("OME strategy must not use global LLM settings")

    class FakeAtomicFactExtractor:
        def __init__(self, *, llm):
            extractor_clients.append(llm)

        async def aextract_from_text(self, text, *, timestamp):
            return []

    monkeypatch.setattr(strategy, "get_project_llm_client", fake_project_client, raising=False)
    monkeypatch.setattr(strategy, "get_llm_client", fail_global_client, raising=False)
    monkeypatch.setattr(strategy, "AtomicFactExtractor", FakeAtomicFactExtractor)

    await strategy.extract_atomic_facts(
        EpisodeExtracted(
            memcell_id="mc-1",
            episode_entry_id="ep-1",
            episode_text="User likes carousel rides.",
            episode_timestamp_ms=1784107914266,
            owner_id="user-1",
            session_id="session-1",
            app_id="joysafeter",
            project_id="project-1",
            source="pipeline",
        ),
        ctx=object(),
    )

    assert seen_project_ids == ["project-1"]
    assert extractor_clients == [project_client]


def test_ome_strategy_modules_do_not_call_global_llm_client_directly():
    module_names = [
        "app.everos.memory.strategies.extract_agent_case",
        "app.everos.memory.strategies.extract_agent_skill",
        "app.everos.memory.strategies.extract_atomic_facts",
        "app.everos.memory.strategies.extract_foresight",
        "app.everos.memory.strategies.extract_user_profile",
        "app.everos.memory.strategies.reflect_episodes",
        "app.everos.memory.strategies.trigger_skill_clustering",
    ]

    offenders = []
    for module_name in module_names:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        if "get_llm_client()" in source:
            offenders.append(module_name)

    assert offenders == []


async def test_knowledge_extractor_uses_project_llm(monkeypatch):
    route = importlib.import_module("app.everos.entrypoints.api.routes.knowledge")

    seen_project_ids = []
    project_client = object()
    extractor_clients = []

    async def fake_project_client(project_id):
        seen_project_ids.append(project_id)
        return project_client

    class FakeKnowledgeExtractor:
        def __init__(self, *, llm):
            extractor_clients.append(llm)

    fake_knowledge_module = types.ModuleType("everalgo.knowledge")
    fake_knowledge_module.KnowledgeExtractor = FakeKnowledgeExtractor
    monkeypatch.setitem(sys.modules, "everalgo.knowledge", fake_knowledge_module)
    monkeypatch.setattr(route, "get_project_llm_client", fake_project_client)

    extractor = await route._build_extractor("project-1")

    assert isinstance(extractor, FakeKnowledgeExtractor)
    assert seen_project_ids == ["project-1"]
    assert extractor_clients == [project_client]


async def test_parser_aparse_file_uses_project_multimodal_llm(monkeypatch):
    parser_core = importlib.import_module("app.everos.component.parser._core")
    llm_module = importlib.import_module("app.everos.component.llm")

    seen_project_ids = []
    project_client = object()
    parser_clients = []

    async def fake_project_multimodal_client(project_id):
        seen_project_ids.append(project_id)
        return project_client

    async def fake_aparse(raw_file, *, llm):
        parser_clients.append(llm)
        return SimpleNamespace(text="parsed")

    fake_parser_module = types.ModuleType("everalgo.parser")
    fake_parser_module.aparse = fake_aparse
    monkeypatch.setitem(sys.modules, "everalgo.parser", fake_parser_module)
    monkeypatch.setattr(
        llm_module,
        "get_project_multimodal_llm_client",
        fake_project_multimodal_client,
        raising=False,
    )

    parsed = await parser_core.aparse_file(object(), project_id="project-1")

    assert parsed.text == "parsed"
    assert seen_project_ids == ["project-1"]
    assert parser_clients == [project_client]


async def test_ingest_multimodal_parser_threads_project_id(monkeypatch):
    enrich = importlib.import_module("app.everos.memory.extract.parser.enrich")

    seen_project_ids = []

    async def fake_build_raw_file(item):
        return object()

    async def fake_aparse_file(raw_file, *, project_id=None):
        seen_project_ids.append(project_id)
        return SimpleNamespace(text="parsed image")

    monkeypatch.setattr(enrich, "build_raw_file", fake_build_raw_file)
    parser_module = importlib.import_module("app.everos.component.parser")
    monkeypatch.setattr(parser_module, "aparse_file", fake_aparse_file)

    items = [{"type": "image", "content": "bytes"}]

    await enrich.enrich_content_items(items, project_id="project-1")

    assert seen_project_ids == ["project-1"]
    assert items[0]["parsed_content"] == "parsed image"
    assert items[0]["parse_status"] == "success"


async def test_knowledge_parse_upload_threads_project_id_to_multimodal_parser(
    monkeypatch,
):
    route = importlib.import_module("app.everos.entrypoints.api.routes.knowledge")
    parser_module = importlib.import_module("app.everos.component.parser")

    seen_project_ids = []

    async def fake_aparse_file(raw_file, *, project_id=None):
        seen_project_ids.append(project_id)
        return SimpleNamespace(text="parsed document")

    monkeypatch.setattr(parser_module, "parser_available", lambda: True)
    monkeypatch.setattr(parser_module, "aparse_file", fake_aparse_file)

    file = SimpleNamespace(filename="doc.pdf", content_type="application/pdf")

    parsed = await route._parse_upload(
        file,
        raw_bytes=b"%PDF",
        project_id="project-1",
    )

    assert parsed.text == "parsed document"
    assert seen_project_ids == ["project-1"]


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
                    "content": [{"type": "text", "text": '{"ok": true}'}],
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
    assert captured["json"]["messages"] == [{"role": "user", "content": "return json"}]
    assert captured["json"]["max_tokens"] == 128
    assert response.content == '{"ok": true}'
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 4
    assert response.finish_reason == "stop"


async def test_anthropic_provider_omits_pydantic_response_format(monkeypatch):
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
            captured["json"] = json
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "model": "claude-test",
                    "content": [{"type": "text", "text": '{"ok": true}'}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "stop_reason": "end_turn",
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    provider = AnthropicProvider(
        model="claude-test",
        api_key="anthropic-key",
        base_url="https://api.anthropic.test",
    )

    await provider.chat(
        [ChatMessage(role="user", content="return json")],
        response_format=_StructuredOutput,
    )

    assert "response_format" not in captured["json"]


async def test_openai_provider_omits_pydantic_response_format(monkeypatch):
    from app.everos.component.llm.openai_provider import OpenAIProvider
    from app.everos.component.llm.protocol import ChatMessage
    import app.everos.component.llm.openai_provider as provider_module

    captured = {}

    class FakeCompletions:
        async def create(self, **request):
            captured["request"] = request
            message = SimpleNamespace(content='{"ok": true}')
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(
                choices=[choice],
                model="openai-test",
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(provider_module.openai, "AsyncOpenAI", FakeAsyncOpenAI)

    provider = OpenAIProvider(
        model="openai-test",
        api_key="openai-key",
        base_url="https://api.openai.test/v1",
    )

    await provider.chat(
        [ChatMessage(role="user", content="return json")],
        response_format=_StructuredOutput,
    )

    assert "response_format" not in captured["request"]
