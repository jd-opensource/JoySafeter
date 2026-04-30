from __future__ import annotations

import asyncio
import importlib
import uuid

from app.common.app_errors import InvalidRequestError
from app.core.engine.protocol import EngineCapabilities
from app.models.agent import AgentRelease
from app.models.agent_run import AgentRun
from app.models.execution import Execution
from app.services.execution_orchestrator import ExecutionOrchestrator


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


def test_send_message_rejects_unsupported_engine_before_dispatch() -> None:
    execution_id = uuid.uuid4()
    run_id = uuid.uuid4()
    release_id = uuid.uuid4()

    execution = Execution(
        id=execution_id,
        run_id=run_id,
        attempt_index=1,
        executor_kind="graph",
    )
    run = AgentRun(
        id=run_id,
        release_id=release_id,
        workspace_id=uuid.uuid4(),
        trigger_source="manual",
        status="running",
    )
    release = AgentRelease(
        id=release_id,
        agent_version_id=uuid.uuid4(),
        release_number=1,
        runtime_kind="graph",
        runtime_binding={},
    )

    class FakeResult:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class FakeDB:
        def __init__(self, values):
            self.values = list(values)

        async def execute(self, *_args, **_kwargs):
            return FakeResult(self.values.pop(0))

    class FakeUnsupportedEngine:
        engine_kind = "graph"
        capabilities = EngineCapabilities(supports_message_injection=False)

        def __init__(self) -> None:
            self.send_message_called = False

        async def send_message(self, *_args, **_kwargs) -> None:
            self.send_message_called = True

    engine = FakeUnsupportedEngine()
    orchestrator = ExecutionOrchestrator(FakeDB([execution, run, release]))  # type: ignore[arg-type]
    orchestrator._resolve_engine = lambda *_args: engine  # type: ignore[method-assign]

    try:
        asyncio.run(orchestrator.send_message(execution_id, "hello"))
        assert False, "Expected InvalidRequestError"
    except InvalidRequestError as exc:
        assert exc.to_payload() == {
            "code": "EXECUTION_OPERATION_UNSUPPORTED",
            "message": "Execution engine does not support message injection",
            "data": {
                "operation": "send_message",
                "engine_kind": "graph",
                "execution_id": str(execution_id),
            },
        }

    assert engine.send_message_called is False
