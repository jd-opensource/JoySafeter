from __future__ import annotations

import importlib


def test_dispatch_service_uses_service_layer_orchestrator() -> None:
    module = importlib.import_module("app.services.dispatch_service")
    assert module.ExecutionOrchestrator.__module__ == "app.services.execution_orchestrator"


def test_core_engine_orchestrator_module_removed() -> None:
    try:
        importlib.import_module("app.core.engine.orchestrator")
        assert False, "app.core.engine.orchestrator should not remain importable"
    except ModuleNotFoundError:
        pass


def test_engine_package_does_not_export_product_orchestration() -> None:
    engine_module = importlib.import_module("app.core.engine")
    assert not hasattr(engine_module, "ExecutionOrchestrator")
