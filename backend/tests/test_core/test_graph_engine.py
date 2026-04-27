from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Overwrite

from app.core.engine.graph_engine import GraphEngine
from app.core.engine.graph_engine import _extract_message_contents_from_stream_chunk
from app.core.engine.protocol import ExecutionContext
from app.core.events.event_types import ExecutionEventType


def test_extract_message_contents_ignores_overwrite_state_updates() -> None:
    chunk = {
        "PatchToolCallsMiddleware.before_agent": {
            "messages": Overwrite([HumanMessage(content="hello")]),
        }
    }

    assert _extract_message_contents_from_stream_chunk(chunk) == []


def test_extract_message_contents_reads_normal_node_messages() -> None:
    chunk = {
        "model": {
            "messages": [
                AIMessage(content="done"),
            ],
        }
    }

    assert _extract_message_contents_from_stream_chunk(chunk) == ["done"]


@pytest.mark.asyncio
async def test_graph_engine_ignores_overwrite_chunks_during_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompiledGraph:
        async def astream(self, *_args, **_kwargs):
            yield {
                "PatchToolCallsMiddleware.before_agent": {
                    "messages": Overwrite([HumanMessage(content="hello")]),
                }
            }
            yield {"model": {"messages": [AIMessage(content="done")]}}

    async def fake_build_deep_agents_graph(*_args, **_kwargs):
        return FakeCompiledGraph()

    monkeypatch.setattr(
        "app.core.graph.deep_agents.builder.build_deep_agents_graph",
        fake_build_deep_agents_graph,
    )
    monkeypatch.setattr("app.services.model_service.ModelService", lambda _db: object())

    emitted: list[tuple[ExecutionEventType, dict]] = []
    completions: list[tuple[str, str | None]] = []
    statuses: list[str] = []

    async def emit(event_type: ExecutionEventType, payload: dict) -> None:
        emitted.append((event_type, payload))

    async def update_status(status: str) -> None:
        statuses.append(status)

    async def complete(status: str, result_summary: str | None = None) -> None:
        completions.append((status, result_summary))

    context = ExecutionContext(
        db=AsyncMock(),
        execution_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
    )
    context.db.execute.side_effect = RuntimeError("skip run lookup")
    context._emit_fn = emit
    context._status_fn = update_status
    context._complete_fn = complete

    await GraphEngine().start(
        context,
        release_runtime_binding={},
        definition_kind="graph",
        definition_payload={"nodes": [{"id": "agent1"}], "edges": []},
        prompt="hello",
    )

    assert (ExecutionEventType.ASSISTANT_TEXT, {"content": "done"}) in emitted
    assert completions == [("succeeded", "done")]
