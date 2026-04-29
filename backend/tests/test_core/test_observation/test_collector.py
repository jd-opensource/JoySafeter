"""ObservationCollector — OTel-backed rewrite."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.observation.types import ObservationType, ObservationLevel


@pytest.mark.asyncio
async def test_collector_creates_provider():
    from app.core.observation.collector import ObservationCollector

    collector = ObservationCollector(
        trace_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        broadcast_fn=None,
    )
    assert collector._provider is not None
    assert collector._tracer is not None


@pytest.mark.asyncio
async def test_start_span_returns_observation_span():
    from app.core.observation.collector import ObservationCollector
    from app.core.observation.otel.span_wrapper import ObservationSpan

    collector = ObservationCollector(
        trace_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        broadcast_fn=None,
    )
    span = collector.start_span(ObservationType.AGENT, "root:test")
    assert isinstance(span, ObservationSpan)
    assert span.observation_id is not None


@pytest.mark.asyncio
async def test_child_span_links_parent():
    from app.core.observation.collector import ObservationCollector

    collector = ObservationCollector(
        trace_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        broadcast_fn=None,
    )
    parent = collector.start_span(ObservationType.AGENT, "root")
    child = collector.child_span(parent, ObservationType.TOOL, "child-tool")
    assert child.observation_id != parent.observation_id


@pytest.mark.asyncio
async def test_create_langchain_handler():
    from app.core.observation.collector import ObservationCollector
    from app.core.observation.instrumentation.langchain_handler import (
        ObservationCallbackHandler,
    )

    collector = ObservationCollector(
        trace_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        broadcast_fn=None,
    )
    handler = collector.create_langchain_handler()
    assert isinstance(handler, ObservationCallbackHandler)


@pytest.mark.asyncio
async def test_finalize_updates_trace_row():
    from app.core.observation.collector import ObservationCollector

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    async def fake_factory():
        return mock_session

    collector = ObservationCollector(
        trace_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=fake_factory,
        broadcast_fn=None,
    )
    await collector.finalize(status="complete")
    # Verify that session.execute was called (trace update)
    assert mock_session.execute.called
