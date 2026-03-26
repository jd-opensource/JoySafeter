from __future__ import annotations

import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.test_service import TestService as GraphTestService


def _install_graph_builder_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    compiled_graph: MagicMock,
):
    fake_package = types.ModuleType("app.core.graph")
    fake_package.__path__ = []
    fake_module = types.ModuleType("app.core.graph.graph_builder_factory")

    class _CapturingGraphBuilder:
        init_kwargs: list[dict] = []

        def __init__(self, *args, **kwargs):
            self.__class__.init_kwargs.append(kwargs)

        async def build(self):
            return compiled_graph

    fake_module.GraphBuilder = _CapturingGraphBuilder
    monkeypatch.setitem(sys.modules, "app.core.graph", fake_package)
    monkeypatch.setitem(sys.modules, "app.core.graph.graph_builder_factory", fake_module)
    return _CapturingGraphBuilder


@pytest.mark.asyncio
async def test_run_test_suite_uses_same_thread_id_for_build_and_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    graph_id = uuid.uuid4()
    graph = MagicMock()
    graph.id = graph_id
    graph.nodes = []
    graph.edges = []

    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = graph
    session.execute.return_value = execute_result

    service = GraphTestService(session)
    service.get_test_cases = AsyncMock(
        return_value=[
            MagicMock(
                id=uuid.uuid4(),
                name="runtime-context",
                inputs={"input": "value"},
                expected_outputs={"output": "ok"},
                assertions=[],
            )
        ]
    )

    compiled_graph = MagicMock()
    compiled_graph.ainvoke = AsyncMock(return_value={"output": "ok"})
    capturing_builder = _install_graph_builder_stub(monkeypatch, compiled_graph=compiled_graph)

    fixed_uuid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(uuid, "uuid4", lambda: fixed_uuid)

    result = await service.run_test_suite(graph_id)

    assert result["passed"] == 1
    assert capturing_builder.init_kwargs[0]["thread_id"] == str(fixed_uuid)
    config = compiled_graph.ainvoke.await_args.kwargs["config"]
    assert config["configurable"]["thread_id"] == str(fixed_uuid)
