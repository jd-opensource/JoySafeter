"""ObservationTracerProvider: per-execution OTel TracerProvider lifecycle."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.observation.otel.provider import ObservationTracerProvider


@pytest.mark.asyncio
async def test_get_tracer_returns_tracer():
    provider = ObservationTracerProvider(
        execution_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        broadcast_fn=None,
        event_loop=asyncio.get_running_loop(),
    )
    tracer = provider.get_tracer()
    assert tracer is not None


@pytest.mark.asyncio
async def test_dispatch_live_event_routes_to_broadcast():
    provider = ObservationTracerProvider(
        execution_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        broadcast_fn=None,
        event_loop=asyncio.get_running_loop(),
    )
    # BroadcastProcessor is in _live_processors
    assert len(provider._live_processors) == 1
    mock_span = MagicMock()
    # Patch the BroadcastProcessor's on_event to verify dispatch
    provider._live_processors[0].on_event = MagicMock()
    provider.dispatch_live_event(mock_span, "llm_token", {"token": "Hi"})
    provider._live_processors[0].on_event.assert_called_once_with(
        mock_span, "llm_token", {"token": "Hi"}
    )


@pytest.mark.asyncio
async def test_get_persistence_aggregates():
    provider = ObservationTracerProvider(
        execution_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=AsyncMock(),
        broadcast_fn=None,
        event_loop=asyncio.get_running_loop(),
    )
    agg = provider.get_persistence_aggregates()
    assert "total_tokens" in agg
    assert "total_cost" in agg
    assert "total_observations" in agg
    assert "has_error" in agg
