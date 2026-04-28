# backend/tests/test_core/test_observation/test_writer.py
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.observation.writer import ObservationWriter


@pytest.fixture
def mock_db_factory():
    session = AsyncMock()
    session.add_all = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    async def factory():
        return session

    return factory, session


def _make_obs(**kwargs):
    """Minimal observation-like object."""
    defaults = dict(
        id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        type="GENERATION",
        name="test",
        level="DEFAULT",
        start_time=datetime.now(timezone.utc),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
    )
    defaults.update(kwargs)
    return MagicMock(**defaults)


@pytest.mark.asyncio
async def test_insert_flushes_at_max_batch(mock_db_factory) -> None:
    factory, session = mock_db_factory
    writer = ObservationWriter(factory, max_batch=3, max_wait_ms=5000)

    await writer.insert(_make_obs())
    await writer.insert(_make_obs())
    assert session.commit.call_count == 0

    await writer.insert(_make_obs())  # triggers flush at batch=3
    assert session.commit.call_count == 1


@pytest.mark.asyncio
async def test_delayed_flush_fires_after_wait(mock_db_factory) -> None:
    factory, session = mock_db_factory
    writer = ObservationWriter(factory, max_batch=100, max_wait_ms=50)

    await writer.insert(_make_obs())
    assert session.commit.call_count == 0

    await asyncio.sleep(0.1)
    assert session.commit.call_count == 1


@pytest.mark.asyncio
async def test_finalize_flushes_remaining(mock_db_factory) -> None:
    factory, session = mock_db_factory
    writer = ObservationWriter(factory, max_batch=100, max_wait_ms=5000)

    await writer.insert(_make_obs())
    await writer.insert(_make_obs())
    assert session.commit.call_count == 0

    await writer.finalize()
    assert session.commit.call_count == 1


@pytest.mark.asyncio
async def test_update_batches_with_inserts(mock_db_factory) -> None:
    factory, session = mock_db_factory
    writer = ObservationWriter(factory, max_batch=2, max_wait_ms=5000)

    await writer.insert(_make_obs())
    await writer.update(uuid.uuid4(), {"end_time": datetime.now(timezone.utc)})
    # insert(1) + update(1) = 2 → flush
    assert session.commit.call_count == 1


@pytest.mark.asyncio
async def test_flush_explicit(mock_db_factory) -> None:
    factory, session = mock_db_factory
    writer = ObservationWriter(factory, max_batch=100, max_wait_ms=5000)

    await writer.insert(_make_obs())
    await writer.flush()
    assert session.commit.call_count == 1
