"""PersistenceProcessor: span -> batched PG persistence via drain loop."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.observation.otel.persistence_processor import PersistenceProcessor


def _make_span(
    *,
    observation_id: uuid.UUID | None = None,
    observation_type: str = "GENERATION",
    obs_level: str = "DEFAULT",
    parent_span_id: int | None = None,
    model: str | None = "gpt-4o",
    usage_input: int = 5,
    usage_output: int = 3,
) -> MagicMock:
    """Build a mock ReadableSpan with observation attributes."""
    span = MagicMock()
    obs_id = observation_id or uuid.uuid4()

    attrs = {
        "observation.id": str(obs_id),
        "observation.type": observation_type,
        "observation.level": obs_level,
        "observation.input": '{"messages": []}',
        "observation.output": '{"content": "hi"}',
        "observation.metadata": "{}",
        "llm.model": model,
        "llm.usage.input": usage_input,
        "llm.usage.output": usage_output,
        "llm.usage.total": usage_input + usage_output,
    }
    span.attributes = attrs
    span.name = "test-span"
    span.start_time = int(datetime(2026, 4, 29, tzinfo=timezone.utc).timestamp() * 1e9)
    span.end_time = int(datetime(2026, 4, 29, 0, 0, 1, tzinfo=timezone.utc).timestamp() * 1e9)

    # OTel span context
    span_ctx = MagicMock()
    span_ctx.span_id = 12345
    span.context = span_ctx

    # Parent
    if parent_span_id is not None:
        parent = MagicMock()
        parent.span_id = parent_span_id
        span.parent = parent
    else:
        span.parent = None

    # Events (skip stream. prefix)
    span.events = []

    return span


@pytest.mark.asyncio
async def test_on_start_stashes_span_id_mapping():
    """on_start should stash the otel span_id -> observation_id mapping."""
    loop = asyncio.get_running_loop()
    proc = PersistenceProcessor(
        execution_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        event_loop=loop,
    )
    span = _make_span()
    proc.on_start(span, parent_context=None)
    obs_id_str = span.attributes["observation.id"]
    assert proc._otel_span_id_to_observation_id[span.context.span_id] == uuid.UUID(obs_id_str)
    await proc.shutdown()


@pytest.mark.asyncio
async def test_get_aggregates_accumulates():
    """get_aggregates returns accumulated totals from on_end calls."""
    loop = asyncio.get_running_loop()
    proc = PersistenceProcessor(
        execution_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        event_loop=loop,
    )
    span1 = _make_span(usage_input=10, usage_output=5)
    span2 = _make_span(usage_input=20, usage_output=10, obs_level="ERROR")
    proc.on_end(span1)
    proc.on_end(span2)
    agg = proc.get_aggregates()
    assert agg["total_tokens"] == 45  # (10+5) + (20+10)
    assert agg["total_observations"] == 2
    assert agg["has_error"] is True
    await proc.shutdown()


@pytest.mark.asyncio
async def test_stream_events_skipped_in_on_end():
    """Events prefixed with stream. must NOT be enqueued for DB persistence."""
    loop = asyncio.get_running_loop()
    proc = PersistenceProcessor(
        execution_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        event_loop=loop,
    )
    stream_event = MagicMock()
    stream_event.name = "stream.llm_token"
    persist_event = MagicMock()
    persist_event.name = "retry"
    persist_event.attributes = {"attempt": 1}
    persist_event.timestamp = 0
    span = _make_span()
    span.events = [stream_event, persist_event]
    proc.on_end(span)
    assert proc.get_aggregates()["total_observations"] == 1
    await proc.shutdown()
