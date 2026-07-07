import importlib


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
