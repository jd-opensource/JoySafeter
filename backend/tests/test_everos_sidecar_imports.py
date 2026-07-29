import importlib

from fastapi import FastAPI


def test_everos_service_modules_import_from_app_namespace():
    modules = [
        "app.everos.service.memorize",
        "app.everos.service.search",
        "app.everos.service.get",
        "app.everos.entrypoints.api.app",
    ]

    for module in modules:
        importlib.import_module(module)


def test_everos_app_factory_uses_expected_metadata_without_lifespan():
    app_module = importlib.import_module("app.everos.entrypoints.api.app")

    app = app_module.create_app(lifespan_providers=[])

    assert app.title == "everos"
    paths = set(app.openapi()["paths"])
    assert "/health" in paths
    assert "/api/v1/memory/add" in paths
    assert "/api/v1/memory/search" in paths


async def test_everos_llm_lifespan_allows_missing_credentials(monkeypatch):
    lifespan_module = importlib.import_module(
        "app.everos.entrypoints.api.lifespans.llm"
    )

    def raise_not_configured():
        raise lifespan_module.LLMNotConfiguredError("missing test llm")

    monkeypatch.setattr(lifespan_module, "get_llm_client", raise_not_configured)

    provider = lifespan_module.LLMLifespanProvider()

    assert await provider.startup(FastAPI()) is None


def test_everos_app_factory_includes_vector_rebuild_lifespan_by_default():
    app_module = importlib.import_module("app.everos.entrypoints.api.app")

    providers = app_module._default_lifespan_providers()

    assert any(
        provider.name == "vector_rebuild"
        for provider in providers
    )


async def test_everos_vector_rebuild_lifespan_can_be_disabled(monkeypatch):
    lifespan_module = importlib.import_module(
        "app.everos.entrypoints.api.lifespans.vector_rebuild"
    )
    settings_module = importlib.import_module("app.everos.config.settings")
    settings = settings_module.Settings()
    settings.search.vector_auto_rebuild_enabled = False
    monkeypatch.setattr(lifespan_module, "load_settings", lambda: settings)

    provider = lifespan_module.VectorRebuildLifespanProvider()

    assert await provider.startup(FastAPI()) is None


async def test_everos_vector_rebuild_lifespan_skips_keyword_mode(monkeypatch):
    lifespan_module = importlib.import_module(
        "app.everos.entrypoints.api.lifespans.vector_rebuild"
    )
    settings_module = importlib.import_module("app.everos.config.settings")
    settings = settings_module.Settings()
    settings.search.mode = "keyword"
    settings.search.vector_auto_rebuild_enabled = True
    monkeypatch.setattr(lifespan_module, "load_settings", lambda: settings)

    def fail_build_embedding_provider(_settings):
        raise AssertionError("embedding provider should not be built in keyword mode")

    monkeypatch.setattr(
        lifespan_module,
        "build_embedding_provider",
        fail_build_embedding_provider,
    )

    provider = lifespan_module.VectorRebuildLifespanProvider()

    assert await provider.startup(FastAPI()) is None
