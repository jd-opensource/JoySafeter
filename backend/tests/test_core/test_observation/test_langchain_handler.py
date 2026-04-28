# backend/tests/test_core/test_observation/test_langchain_handler.py
from __future__ import annotations

import uuid

import pytest

from tests.test_core.test_observation.test_collector import FakeBroadcaster, FakeWriter
from app.core.observation.collector import ObservationCollector
from app.core.observation.instrumentation.langchain_handler import ObservationCallbackHandler


@pytest.fixture
async def handler():
    writer = FakeWriter()
    broadcaster = FakeBroadcaster()
    collector = ObservationCollector(
        trace_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        writer=writer,
        broadcaster=broadcaster,
    )
    root_span = await collector.start_agent("root")
    h = ObservationCallbackHandler(collector, root_span)
    return h, writer, broadcaster, collector


@pytest.mark.asyncio
async def test_on_llm_start_creates_generation_span(handler) -> None:
    h, writer, _, _ = handler
    run_id = uuid.uuid4()
    await h.on_llm_start({"name": "gpt-4o"}, ["hello"], run_id=run_id, parent_run_id=None)

    assert len(writer.inserted) == 2
    gen_obs = writer.inserted[1]
    assert gen_obs.type == "GENERATION"


@pytest.mark.asyncio
async def test_on_tool_start_creates_tool_span(handler) -> None:
    h, writer, _, _ = handler
    run_id = uuid.uuid4()
    await h.on_tool_start({"name": "web_search"}, '{"query": "test"}', run_id=run_id, parent_run_id=None)

    tool_obs = writer.inserted[1]
    assert tool_obs.type == "TOOL"
    assert tool_obs.name == "web_search"
