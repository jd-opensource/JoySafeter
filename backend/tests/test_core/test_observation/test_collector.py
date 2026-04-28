# backend/tests/test_core/test_observation/test_collector.py
from __future__ import annotations

import uuid

import pytest

from app.core.observation.collector import ObservationCollector
from app.core.observation.types import ObservationLevel, ObservationType


class FakeWriter:
    def __init__(self):
        self.inserted: list = []
        self.updated: list = []
        self.flushed = 0
        self.finalized = False

    async def insert(self, obs):
        self.inserted.append(obs)

    async def update(self, obs_id, fields):
        self.updated.append((obs_id, fields))

    async def flush(self):
        self.flushed += 1

    async def finalize(self):
        self.finalized = True


class FakeBroadcaster:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event: str, observation: dict):
        self.events.append((event, observation))


@pytest.fixture
def collector():
    writer = FakeWriter()
    broadcaster = FakeBroadcaster()
    c = ObservationCollector(
        trace_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        writer=writer,
        broadcaster=broadcaster,
    )
    return c, writer, broadcaster


@pytest.mark.asyncio
async def test_start_span_creates_observation_and_emits_span_open(collector) -> None:
    c, writer, broadcaster = collector
    span = await c.start_span(ObservationType.AGENT, "root")

    assert span.observation_id is not None
    assert len(writer.inserted) == 1
    assert writer.inserted[0].type == "AGENT"
    assert writer.inserted[0].name == "root"
    assert broadcaster.events[0][0] == "span_open"


@pytest.mark.asyncio
async def test_end_span_updates_and_emits_span_close(collector) -> None:
    c, writer, broadcaster = collector
    span = await c.start_span(ObservationType.GENERATION, "llm")
    await c.end_span(span, output={"completion": "hello"})

    assert len(writer.updated) == 1
    obs_id, fields = writer.updated[0]
    assert obs_id == span.observation_id
    assert fields["output"] == {"completion": "hello"}
    assert fields["end_time"] is not None
    assert broadcaster.events[1][0] == "span_close"


@pytest.mark.asyncio
async def test_child_span_sets_parent_id(collector) -> None:
    c, writer, _ = collector
    parent = await c.start_span(ObservationType.AGENT, "root")
    child = await parent.child_span(ObservationType.GENERATION, "llm")

    child_obs = writer.inserted[1]
    assert child_obs.parent_observation_id == parent.observation_id


@pytest.mark.asyncio
async def test_record_generation_creates_complete_observation(collector) -> None:
    c, writer, broadcaster = collector
    obs_id = await c.record_generation(
        "gpt-4o",
        input={"messages": []},
        output={"completion": "hi"},
        model="gpt-4o",
        usage_details={"input": 100, "output": 50, "total": 150},
        cost_details={"total": 0.01},
        latency_ms=500,
    )

    assert obs_id is not None
    obs = writer.inserted[0]
    assert obs.type == "GENERATION"
    assert obs.model == "gpt-4o"
    assert obs.usage_details == {"input": 100, "output": 50, "total": 150}
    assert obs.end_time is not None
    assert broadcaster.events[0][0] == "record"


@pytest.mark.asyncio
async def test_record_tool_creates_tool_observation(collector) -> None:
    c, writer, _ = collector
    obs_id = await c.record_tool(
        "web_search",
        input={"query": "langfuse"},
        output={"results": []},
        latency_ms=200,
    )

    obs = writer.inserted[0]
    assert obs.type == "TOOL"
    assert obs.name == "web_search"


@pytest.mark.asyncio
async def test_record_event_creates_event_with_no_end_time(collector) -> None:
    c, writer, _ = collector
    await c.record_event(
        "file:write /tmp/out.json",
        metadata={"file.path": "/tmp/out.json", "file.operation": "write"},
    )

    obs = writer.inserted[0]
    assert obs.type == "EVENT"
    assert obs.end_time is None


@pytest.mark.asyncio
async def test_start_agent_returns_span_handle(collector) -> None:
    c, writer, _ = collector
    handle = await c.start_agent("worker:Researcher")

    assert handle.observation_id is not None
    obs = writer.inserted[0]
    assert obs.type == "AGENT"


@pytest.mark.asyncio
async def test_finalize_closes_open_spans_with_warning(collector) -> None:
    c, writer, broadcaster = collector
    span = await c.start_span(ObservationType.AGENT, "root")
    # Don't close it

    await c.finalize()

    assert len(writer.updated) == 1
    _, fields = writer.updated[0]
    assert fields["end_time"] is not None
    assert fields.get("level") == "WARNING"
    assert writer.finalized is True


@pytest.mark.asyncio
async def test_finalize_emits_trace_complete(collector) -> None:
    c, writer, broadcaster = collector
    await c.record_generation(
        "gpt-4o",
        input={}, output={},
        model="gpt-4o",
        usage_details={"input": 100, "output": 50, "total": 150},
        cost_details={"total": 0.01},
        latency_ms=500,
    )

    await c.finalize()

    last_event = broadcaster.events[-1]
    assert last_event[0] == "trace_complete"


@pytest.mark.asyncio
async def test_finalize_preserves_error_level(collector) -> None:
    c, writer, broadcaster = collector
    span = await c.start_span(ObservationType.AGENT, "root")
    await c.record_event(
        "error:RuntimeError",
        input={"message": "boom"},
        level=ObservationLevel.ERROR,
    )

    await c.finalize()

    _, fields = writer.updated[0]
    assert fields.get("level") == "WARNING"


@pytest.mark.asyncio
async def test_flush_delegates_to_writer(collector) -> None:
    c, writer, _ = collector
    await c.flush()
    assert writer.flushed == 1
