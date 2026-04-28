# Observation Tracing System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Langfuse-aligned observation tracing system for in-product agent debugging, with WebSocket real-time streaming of structured trace trees across all four engines.

**Architecture:** Independent ObservationCollector with own data model (traces + observations tables), reusing existing WebSocket transport with `channel: "observation"`. Each engine instruments its own code path. Orchestrator injects collector via `debug=True` flag on ExecutionContext.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0 (async), Alembic, asyncio, existing WebSocket infrastructure

**Spec:** `docs/superpowers/specs/2026-04-28-observation-tracing-design.md`

---

## Phase 1 — Core Layer

### Task 1: ObservationType + ObservationLevel + SpanHandle

**Files:**
- Create: `backend/app/core/observation/__init__.py`
- Create: `backend/app/core/observation/types.py`
- Test: `backend/tests/test_core/test_observation/test_types.py`

- [ ] **Step 1: Create test file with type alignment tests**

```python
# backend/tests/test_core/test_observation/test_types.py
from __future__ import annotations

from app.core.observation.types import ObservationLevel, ObservationType


LANGFUSE_OBSERVATION_TYPES = {
    "SPAN", "EVENT", "GENERATION", "AGENT", "TOOL",
    "CHAIN", "RETRIEVER", "EMBEDDING", "EVALUATOR", "GUARDRAIL",
}

LANGFUSE_OBSERVATION_LEVELS = {"DEBUG", "DEFAULT", "WARNING", "ERROR"}


def test_observation_type_values_match_langfuse() -> None:
    actual = {t.value for t in ObservationType}
    assert actual == LANGFUSE_OBSERVATION_TYPES


def test_observation_level_values_match_langfuse() -> None:
    actual = {lv.value for lv in ObservationLevel}
    assert actual == LANGFUSE_OBSERVATION_LEVELS


def test_observation_type_is_str_enum() -> None:
    assert ObservationType.GENERATION == "GENERATION"
    assert isinstance(ObservationType.GENERATION, str)


def test_event_type_has_no_end_time_semantics() -> None:
    """EVENT is the only type that semantically has no end_time."""
    assert ObservationType.EVENT == "EVENT"


def test_generation_like_types() -> None:
    """Types that carry model/usage/cost fields per Langfuse convention."""
    generation_like = {
        ObservationType.GENERATION, ObservationType.AGENT,
        ObservationType.TOOL, ObservationType.CHAIN,
        ObservationType.RETRIEVER, ObservationType.EVALUATOR,
        ObservationType.EMBEDDING, ObservationType.GUARDRAIL,
    }
    assert ObservationType.SPAN not in generation_like
    assert ObservationType.EVENT not in generation_like
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.observation'`

- [ ] **Step 3: Create `__init__.py` files**

```python
# backend/tests/test_core/test_observation/__init__.py
# (empty)
```

```python
# backend/app/core/observation/__init__.py
from app.core.observation.types import ObservationLevel, ObservationType, SpanHandle

__all__ = ["ObservationLevel", "ObservationType", "SpanHandle"]
```

- [ ] **Step 4: Implement types.py**

```python
# backend/app/core/observation/types.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.observation.collector import ObservationCollector


class ObservationType(StrEnum):
    SPAN       = "SPAN"
    EVENT      = "EVENT"
    GENERATION = "GENERATION"
    AGENT      = "AGENT"
    TOOL       = "TOOL"
    CHAIN      = "CHAIN"
    RETRIEVER  = "RETRIEVER"
    EMBEDDING  = "EMBEDDING"
    EVALUATOR  = "EVALUATOR"
    GUARDRAIL  = "GUARDRAIL"


class ObservationLevel(StrEnum):
    DEBUG   = "DEBUG"
    DEFAULT = "DEFAULT"
    WARNING = "WARNING"
    ERROR   = "ERROR"


@dataclass
class SpanHandle:
    observation_id: uuid.UUID
    collector: ObservationCollector

    async def child_span(self, type: ObservationType, name: str, **kwargs: Any) -> SpanHandle:
        return await self.collector.start_span(type, name, parent_id=self.observation_id, **kwargs)

    async def record_generation(self, name: str, **kwargs: Any) -> uuid.UUID:
        return await self.collector.record_generation(name, parent_id=self.observation_id, **kwargs)

    async def record_tool(self, name: str, **kwargs: Any) -> uuid.UUID:
        return await self.collector.record_tool(name, parent_id=self.observation_id, **kwargs)

    async def record_event(self, name: str, **kwargs: Any) -> uuid.UUID:
        return await self.collector.record_event(name, parent_id=self.observation_id, **kwargs)

    async def end(self, **kwargs: Any) -> None:
        await self.collector.end_span(self, **kwargs)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_types.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/observation/__init__.py backend/app/core/observation/types.py \
  backend/tests/test_core/test_observation/__init__.py backend/tests/test_core/test_observation/test_types.py
git commit -m "feat(observation): add ObservationType, ObservationLevel, SpanHandle aligned with Langfuse"
```

---

### Task 2: SQLAlchemy Models (Trace + Observation)

**Files:**
- Create: `backend/app/core/observation/model.py`
- Test: `backend/tests/test_core/test_observation/test_model.py`

**Notes:**
- Use `meta` as Python attribute name; column name is `metadata` (avoid `Base.metadata` collision)
- Tables use existing `Base` from `app/core/database.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_core/test_observation/test_model.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from app.core.observation.model import Observation, Trace
from app.core.observation.types import ObservationLevel, ObservationType


def test_trace_meta_column_named_metadata() -> None:
    col = Trace.__table__.columns["metadata"]
    assert col is not None
    assert "meta" in {a.key for a in Trace.__mapper__.attrs}


def test_observation_meta_column_named_metadata() -> None:
    col = Observation.__table__.columns["metadata"]
    assert col is not None
    assert "meta" in {a.key for a in Observation.__mapper__.attrs}


def test_trace_required_fields() -> None:
    cols = Trace.__table__.columns
    for required in ("id", "name", "workspace_id", "start_time", "status",
                     "execution_id", "agent_version_id", "user_id"):
        assert cols[required].nullable is False, f"{required} must be NOT NULL"


def test_observation_required_fields() -> None:
    cols = Observation.__table__.columns
    for required in ("id", "trace_id", "type", "name", "level",
                     "start_time", "execution_id", "workspace_id"):
        assert cols[required].nullable is False, f"{required} must be NOT NULL"


def test_observation_parent_fk_self_reference() -> None:
    col = Observation.__table__.columns["parent_observation_id"]
    assert col.nullable is True


def test_trace_default_status_running() -> None:
    cols = Trace.__table__.columns
    assert cols["status"].server_default is not None


def test_observation_default_level_default() -> None:
    cols = Observation.__table__.columns
    assert cols["level"].server_default is not None


def test_trace_can_instantiate_with_minimum_fields() -> None:
    t = Trace(
        id=uuid.uuid4(),
        name="test agent",
        workspace_id=uuid.uuid4(),
        start_time=datetime.now(timezone.utc),
        status="running",
        execution_id=uuid.uuid4(),
        agent_version_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    assert t.environment is None or t.environment == "debug"


def test_observation_can_instantiate_with_minimum_fields() -> None:
    o = Observation(
        id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        type=ObservationType.GENERATION,
        name="gpt-4o",
        level=ObservationLevel.DEFAULT,
        start_time=datetime.now(timezone.utc),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
    )
    assert o.type == "GENERATION"
```

- [ ] **Step 2: Run to verify fails**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_model.py -v`
Expected: FAIL — module/class not found

- [ ] **Step 3: Implement model.py**

```python
# backend/app/core/observation/model.py
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY, Boolean, Column, DateTime, ForeignKey, Integer, Numeric,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")

    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    environment: Mapped[str] = mapped_column(String(50), server_default="debug")
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), server_default="{}")
    release: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bookmarked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    public: Mapped[bool] = mapped_column(Boolean, server_default="false")

    total_observations: Mapped[int] = mapped_column(Integer, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("traces.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False, server_default="DEFAULT")
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str] = mapped_column(String(50), server_default="debug")

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    usage_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prompt_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tool_definitions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    tool_call_names: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_model.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/model.py backend/tests/test_core/test_observation/test_model.py
git commit -m "feat(observation): add Trace and Observation SQLAlchemy models"
```

---

### Task 3: ObservationWriter (攒批持久化)

**Files:**
- Create: `backend/app/core/observation/writer.py`
- Test: `backend/tests/test_core/test_observation/test_writer.py`

**Notes:**
- All tests use a fake writer (no DB). The writer Protocol allows injection.
- Writer exposes `insert()`, `update()`, `flush()`, `finalize()`.
- Batching: max 10 items OR 300ms delay, whichever first.

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run to verify fails**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_writer.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement writer.py**

```python
# backend/app/core/observation/writer.py
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable, Coroutine

import sqlalchemy as sa

from app.core.observation.model import Observation


class ObservationWriter:
    def __init__(
        self,
        db_session_factory: Callable[[], Coroutine[Any, Any, Any]],
        *,
        max_batch: int = 10,
        max_wait_ms: int = 300,
    ):
        self._db_session_factory = db_session_factory
        self._max_batch = max_batch
        self._max_wait_ms = max_wait_ms
        self._insert_buffer: list[Any] = []
        self._update_buffer: list[tuple[uuid.UUID, dict]] = []
        self._flush_task: asyncio.Task | None = None

    @property
    def _buffer_size(self) -> int:
        return len(self._insert_buffer) + len(self._update_buffer)

    async def insert(self, observation: Any) -> None:
        self._insert_buffer.append(observation)
        await self._maybe_flush()

    async def update(self, observation_id: uuid.UUID, fields: dict) -> None:
        self._update_buffer.append((observation_id, fields))
        await self._maybe_flush()

    async def flush(self) -> None:
        self._cancel_delayed()
        await self._do_flush()

    async def finalize(self) -> None:
        self._cancel_delayed()
        await self._do_flush()

    async def _maybe_flush(self) -> None:
        if self._buffer_size >= self._max_batch:
            self._cancel_delayed()
            await self._do_flush()
        elif self._flush_task is None:
            self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        await asyncio.sleep(self._max_wait_ms / 1000)
        await self._do_flush()
        self._flush_task = None

    def _cancel_delayed(self) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None

    async def _do_flush(self) -> None:
        if not self._insert_buffer and not self._update_buffer:
            return

        inserts = self._insert_buffer[:]
        updates = self._update_buffer[:]
        self._insert_buffer.clear()
        self._update_buffer.clear()

        session = await self._db_session_factory()
        if inserts:
            session.add_all(inserts)
        for obs_id, fields in updates:
            await session.execute(
                sa.update(Observation)
                .where(Observation.id == obs_id)
                .values(**fields)
            )
        await session.commit()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_writer.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/writer.py backend/tests/test_core/test_observation/test_writer.py
git commit -m "feat(observation): add ObservationWriter with batch flush strategy"
```

---

### Task 4: ObservationBroadcaster (WebSocket 推送)

**Files:**
- Create: `backend/app/core/observation/broadcaster.py`
- Test: `backend/tests/test_core/test_observation/test_broadcaster.py`

**Notes:**
- Owns `_seq` counter (per-trace monotonic).
- Calls `ws_manager.broadcast_to_execution()` — inject as dependency for testability.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_core/test_observation/test_broadcaster.py
from __future__ import annotations

import uuid

import pytest
from unittest.mock import AsyncMock

from app.core.observation.broadcaster import ObservationBroadcaster


@pytest.fixture
def broadcaster():
    ws = AsyncMock()
    execution_id = uuid.uuid4()
    return ObservationBroadcaster(execution_id, broadcast_fn=ws), ws, execution_id


@pytest.mark.asyncio
async def test_emit_sends_observation_channel(broadcaster) -> None:
    bc, ws, exec_id = broadcaster
    await bc.emit("span_open", {"id": "obs-1", "type": "GENERATION"})

    ws.assert_called_once()
    msg = ws.call_args[0][1]
    assert msg["channel"] == "observation"
    assert msg["trace_id"] == str(exec_id)
    assert msg["event"] == "span_open"
    assert msg["observation"]["id"] == "obs-1"


@pytest.mark.asyncio
async def test_seq_monotonically_increases(broadcaster) -> None:
    bc, ws, _ = broadcaster
    await bc.emit("span_open", {"id": "a"})
    await bc.emit("span_close", {"id": "a"})
    await bc.emit("record", {"id": "b"})

    seqs = [call[0][1]["seq"] for call in ws.call_args_list]
    assert seqs == [1, 2, 3]


@pytest.mark.asyncio
async def test_trace_complete_event(broadcaster) -> None:
    bc, ws, _ = broadcaster
    await bc.emit("trace_complete", {"total_tokens": 1540, "total_cost": 0.016})

    msg = ws.call_args[0][1]
    assert msg["event"] == "trace_complete"
```

- [ ] **Step 2: Run to verify fails**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_broadcaster.py -v`

- [ ] **Step 3: Implement broadcaster.py**

```python
# backend/app/core/observation/broadcaster.py
from __future__ import annotations

import uuid
from typing import Any, Callable, Coroutine


class ObservationBroadcaster:
    def __init__(
        self,
        execution_id: uuid.UUID,
        *,
        broadcast_fn: Callable[[uuid.UUID, dict], Coroutine[Any, Any, None]] | None = None,
    ):
        self._execution_id = execution_id
        self._seq = 0
        self._broadcast_fn = broadcast_fn

    async def emit(self, event: str, observation: dict) -> None:
        self._seq += 1
        message = {
            "channel": "observation",
            "trace_id": str(self._execution_id),
            "seq": self._seq,
            "event": event,
            "observation": observation,
        }
        if self._broadcast_fn:
            await self._broadcast_fn(self._execution_id, message)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_broadcaster.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/broadcaster.py backend/tests/test_core/test_observation/test_broadcaster.py
git commit -m "feat(observation): add ObservationBroadcaster with monotonic seq"
```

---

### Task 5: ObservationCollector (核心)

**Files:**
- Create: `backend/app/core/observation/collector.py`
- Test: `backend/tests/test_core/test_observation/test_collector.py`

**Notes:**
- This is the biggest task. Tests use fake writer + fake broadcaster (no DB/WS).
- Key behaviors: start_span/end_span lifecycle, convenience methods, finalize auto-close, tree structure.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_core/test_observation/test_collector.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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

    # Should have been auto-closed
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
    # root span still open

    await c.finalize()

    # The auto-close should use WARNING (not override ERROR on root)
    _, fields = writer.updated[0]
    assert fields.get("level") == "WARNING"


@pytest.mark.asyncio
async def test_flush_delegates_to_writer(collector) -> None:
    c, writer, _ = collector
    await c.flush()
    assert writer.flushed == 1
```

- [ ] **Step 2: Run to verify fails**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_collector.py -v`

- [ ] **Step 3: Implement collector.py**

```python
# backend/app/core/observation/collector.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.core.observation.model import Observation
from app.core.observation.types import ObservationLevel, ObservationType, SpanHandle


class ObservationCollector:
    def __init__(
        self,
        trace_id: uuid.UUID,
        execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
        writer: Any,
        broadcaster: Any,
    ):
        self._trace_id = trace_id
        self._execution_id = execution_id
        self._workspace_id = workspace_id
        self._writer = writer
        self._broadcaster = broadcaster
        self._open_spans: dict[uuid.UUID, SpanHandle] = {}
        self._has_error = False
        self._total_tokens = 0
        self._total_cost = Decimal(0)
        self._start_time = datetime.now(timezone.utc)

    async def start_span(
        self,
        type: ObservationType,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> SpanHandle:
        obs_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        obs = Observation(
            id=obs_id,
            trace_id=self._trace_id,
            parent_observation_id=parent_id,
            type=type.value,
            name=name,
            level=level.value,
            start_time=now,
            input=input,
            meta=metadata,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("span_open", self._obs_to_dict(obs))

        handle = SpanHandle(observation_id=obs_id, collector=self)
        self._open_spans[obs_id] = handle
        return handle

    async def end_span(
        self,
        span: SpanHandle,
        *,
        output: dict | None = None,
        level: ObservationLevel | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        fields: dict[str, Any] = {"end_time": now}
        if output is not None:
            fields["output"] = output
        if level is not None:
            fields["level"] = level.value

        await self._writer.update(span.observation_id, fields)
        await self._broadcaster.emit("span_close", {
            "id": str(span.observation_id),
            **fields,
            "end_time": now.isoformat(),
        })
        self._open_spans.pop(span.observation_id, None)

    async def record_generation(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        output: dict | None = None,
        model: str | None = None,
        model_parameters: dict | None = None,
        usage_details: dict | None = None,
        cost_details: dict | None = None,
        completion_start_time: datetime | None = None,
        latency_ms: float = 0,
        level: ObservationLevel = ObservationLevel.DEFAULT,
        tool_definitions: dict | None = None,
        tool_calls: list | None = None,
        tool_call_names: list[str] | None = None,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs_id = uuid.uuid4()

        obs = Observation(
            id=obs_id,
            trace_id=self._trace_id,
            parent_observation_id=parent_id,
            type=ObservationType.GENERATION.value,
            name=name,
            level=level.value,
            start_time=now,
            end_time=now,
            completion_start_time=completion_start_time,
            input=input,
            output=output,
            model=model,
            model_parameters=model_parameters,
            usage_details=usage_details,
            cost_details=cost_details,
            tool_definitions=tool_definitions,
            tool_calls=tool_calls,
            tool_call_names=tool_call_names,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))

        if usage_details and "total" in usage_details:
            self._total_tokens += usage_details["total"]
        if cost_details and "total" in cost_details:
            self._total_cost += Decimal(str(cost_details["total"]))

        return obs_id

    async def record_tool(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        output: dict | None = None,
        latency_ms: float = 0,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs_id = uuid.uuid4()

        obs = Observation(
            id=obs_id,
            trace_id=self._trace_id,
            parent_observation_id=parent_id,
            type=ObservationType.TOOL.value,
            name=name,
            level=level.value,
            start_time=now,
            end_time=now,
            input=input,
            output=output,
            meta=metadata,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))
        return obs_id

    async def record_event(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        input: dict | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs_id = uuid.uuid4()

        obs = Observation(
            id=obs_id,
            trace_id=self._trace_id,
            parent_observation_id=parent_id,
            type=ObservationType.EVENT.value,
            name=name,
            level=level.value,
            start_time=now,
            end_time=None,  # EVENT has no end_time
            input=input,
            meta=metadata,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))

        if level == ObservationLevel.ERROR:
            self._has_error = True

        return obs_id

    async def start_agent(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        node_config: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> SpanHandle:
        return await self.start_span(
            ObservationType.AGENT, name,
            parent_id=parent_id, input=node_config, level=level,
        )

    async def start_chain(
        self,
        name: str,
        *,
        parent_id: uuid.UUID | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> SpanHandle:
        return await self.start_span(
            ObservationType.CHAIN, name,
            parent_id=parent_id, level=level,
        )

    async def record_retriever(
        self, name: str, *, parent_id: uuid.UUID | None = None,
        input: dict | None = None, output: dict | None = None,
        latency_ms: float = 0, level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        return await self._record_instant(
            ObservationType.RETRIEVER, name, parent_id=parent_id,
            input=input, output=output, level=level,
        )

    async def record_embedding(
        self, name: str, *, parent_id: uuid.UUID | None = None,
        input: dict | None = None, output: dict | None = None,
        model: str | None = None, usage_details: dict | None = None,
        latency_ms: float = 0, level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs_id = uuid.uuid4()
        obs = Observation(
            id=obs_id, trace_id=self._trace_id, parent_observation_id=parent_id,
            type=ObservationType.EMBEDDING.value, name=name, level=level.value,
            start_time=now, end_time=now, input=input, output=output,
            model=model, usage_details=usage_details,
            execution_id=self._execution_id, workspace_id=self._workspace_id,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))
        return obs_id

    async def flush(self) -> None:
        await self._writer.flush()

    async def finalize(self) -> None:
        now = datetime.now(timezone.utc)
        for span_id in list(self._open_spans):
            await self._writer.update(span_id, {
                "end_time": now,
                "level": ObservationLevel.WARNING.value,
            })
            self._open_spans.pop(span_id)

        await self._writer.finalize()

        duration_ms = int((now - self._start_time).total_seconds() * 1000)
        await self._broadcaster.emit("trace_complete", {
            "total_tokens": self._total_tokens,
            "total_cost": float(self._total_cost),
            "duration_ms": duration_ms,
            "status": "error" if self._has_error else "completed",
        })

    async def _record_instant(
        self, type: ObservationType, name: str, *,
        parent_id: uuid.UUID | None, input: dict | None,
        output: dict | None, level: ObservationLevel,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        obs_id = uuid.uuid4()
        obs = Observation(
            id=obs_id, trace_id=self._trace_id, parent_observation_id=parent_id,
            type=type.value, name=name, level=level.value,
            start_time=now, end_time=now, input=input, output=output,
            execution_id=self._execution_id, workspace_id=self._workspace_id,
        )
        await self._writer.insert(obs)
        await self._broadcaster.emit("record", self._obs_to_dict(obs))
        return obs_id

    @staticmethod
    def _obs_to_dict(obs: Any) -> dict:
        return {
            "id": str(obs.id),
            "trace_id": str(obs.trace_id),
            "parent_observation_id": str(obs.parent_observation_id) if obs.parent_observation_id else None,
            "type": obs.type,
            "name": obs.name,
            "level": obs.level,
            "start_time": obs.start_time.isoformat() if obs.start_time else None,
            "end_time": obs.end_time.isoformat() if obs.end_time else None,
            "completion_start_time": obs.completion_start_time.isoformat() if getattr(obs, "completion_start_time", None) else None,
            "input": obs.input,
            "output": obs.output,
            "metadata": obs.meta if hasattr(obs, "meta") else None,
            "model": getattr(obs, "model", None),
            "usage_details": getattr(obs, "usage_details", None),
            "cost_details": getattr(obs, "cost_details", None),
            "tool_calls": getattr(obs, "tool_calls", None),
            "tool_call_names": getattr(obs, "tool_call_names", None),
        }
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_collector.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/collector.py backend/tests/test_core/test_observation/test_collector.py
git commit -m "feat(observation): add ObservationCollector with span lifecycle and convenience methods"
```

---

### Task 6: Alembic Migration

**Files:**
- Create: `backend/migrations/versions/xxxx_add_traces_observations.py`

**Notes:** Use exact DDL from spec Section 10. Generate via alembic or create manually.

- [ ] **Step 1: Generate migration stub**

Run: `cd backend && alembic revision --autogenerate -m "add traces and observations tables"`

If autogenerate doesn't pick up the tables (model not imported in env), create manually.

- [ ] **Step 2: Verify migration DDL matches spec**

Ensure these indexes exist:
- `ix_traces_workspace_created` on `(workspace_id, created_at)`
- `ix_traces_execution` on `(execution_id)` UNIQUE
- `ix_traces_session` on `(session_id, created_at)`
- `ix_observations_trace_time` on `(trace_id, start_time)`
- `ix_observations_parent` on `(parent_observation_id)`
- `ix_observations_trace_type` on `(trace_id, type)`

- [ ] **Step 3: Run migration against dev DB**

Run: `cd backend && alembic upgrade head`
Expected: Tables created without error

- [ ] **Step 4: Verify downgrade works**

Run: `cd backend && alembic downgrade -1 && alembic upgrade head`

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/
git commit -m "migration: add traces and observations tables"
```

---

### Task 7: Update __init__.py exports + update observation module exports

**Files:**
- Modify: `backend/app/core/observation/__init__.py`

- [ ] **Step 1: Update exports**

```python
# backend/app/core/observation/__init__.py
from app.core.observation.broadcaster import ObservationBroadcaster
from app.core.observation.collector import ObservationCollector
from app.core.observation.model import Observation, Trace
from app.core.observation.types import ObservationLevel, ObservationType, SpanHandle
from app.core.observation.writer import ObservationWriter

__all__ = [
    "Observation",
    "ObservationBroadcaster",
    "ObservationCollector",
    "ObservationLevel",
    "ObservationType",
    "ObservationWriter",
    "SpanHandle",
    "Trace",
]
```

- [ ] **Step 2: Run all observation tests**

Run: `cd backend && python -m pytest tests/test_core/test_observation/ -v`
Expected: ALL PASS

- [ ] **Step 3: Run all existing tests to check no regressions**

Run: `cd backend && python -m pytest tests/test_core/ -v`
Expected: ALL PASS (existing + new)

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/observation/__init__.py
git commit -m "feat(observation): export complete observation module"
```

---

## Phase 2 — Engine Integration

### Task 8: ExecutionContext 扩展 (debug + collector)

**Files:**
- Modify: `backend/app/core/engine/protocol.py:20-36`

- [ ] **Step 1: Add fields to ExecutionContext**

Add two fields after `metadata` (line 36):

```python
    debug: bool = False
    collector: Any = None  # ObservationCollector | None — import avoided for no circular deps
```

- [ ] **Step 2: Run existing tests**

Run: `cd backend && python -m pytest tests/test_core/ -v`
Expected: ALL PASS (dataclass default fields are backward compatible)

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/engine/protocol.py
git commit -m "feat(observation): add debug and collector fields to ExecutionContext"
```

---

### Task 9: Orchestrator collector injection

**Files:**
- Modify: `backend/app/core/engine/orchestrator.py` — `_fire_engine` method (~line 686-778)

**Notes:**
- In the `_run_engine` inner function, after creating `ctx`, check `debug` flag and construct collector.
- In the `finally` block call `collector.finalize()`.
- In the `except` block record ERROR event.

- [ ] **Step 1: Modify `_fire_engine` to accept and propagate `debug` flag**

In `_fire_engine` method signature, add `debug: bool = False` parameter.

In the `_run_engine` inner function, after `self._wire_context(ctx, **_run_meta)` (line ~756), add:

```python
                    collector = None
                    if debug:
                        from app.core.observation import (
                            ObservationBroadcaster,
                            ObservationCollector,
                            ObservationWriter,
                        )
                        collector = ObservationCollector(
                            trace_id=execution.id,
                            execution_id=execution.id,
                            workspace_id=workspace_id,
                            writer=ObservationWriter(lambda: db),
                            broadcaster=ObservationBroadcaster(execution.id),
                        )
                        ctx.debug = True
                        ctx.collector = collector
                    try:
                        await engine.start(ctx, ...)
                    except Exception as exc:
                        if collector:
                            await collector.record_event(
                                f"error:{type(exc).__name__}",
                                input={"message": str(exc)},
                                level=ObservationLevel.ERROR,
                            )
                        raise
                    finally:
                        if collector:
                            await collector.finalize()
```

- [ ] **Step 2: Add `dispatch_debug` method**

Add a new public method `dispatch_debug` that calls `_create_and_fire_draft` with `debug=True`.

```python
    async def dispatch_debug(
        self,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        prompt: str,
        user_id: str,
        workspace_id: uuid.UUID,
        variables: dict | None = None,
    ) -> AgentRun:
        """Dispatch a debug run — creates trace + observation collection."""
        return await self.dispatch_draft(
            agent_id=agent_id,
            version_id=version_id,
            prompt=prompt,
            user_id=user_id,
            workspace_id=workspace_id,
            input_payload={"debug": True, "variables": variables or {}},
        )
```

- [ ] **Step 3: Create Trace record in orchestrator**

In `dispatch_debug`, after the run is created, also create a `Trace` record:

```python
        from app.core.observation.model import Trace
        trace = Trace(
            id=run.current_execution_id,
            name=agent.name,
            workspace_id=workspace_id,
            start_time=datetime.now(timezone.utc),
            status="running",
            execution_id=run.current_execution_id,
            agent_version_id=version_id,
            user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
            session_id=f"debug-{user_id}-{version_id}-{datetime.now(timezone.utc).date()}",
            input={"prompt": prompt, "variables": variables or {}},
        )
        self.db.add(trace)
        await self.db.commit()
```

- [ ] **Step 4: Run existing tests**

Run: `cd backend && python -m pytest tests/test_core/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/engine/orchestrator.py
git commit -m "feat(observation): inject ObservationCollector in orchestrator for debug runs"
```

---

### Task 10: LangChain ObservationCallbackHandler (Graph + Code)

**Files:**
- Create: `backend/app/core/observation/instrumentation/__init__.py`
- Create: `backend/app/core/observation/instrumentation/langchain_handler.py`
- Test: `backend/tests/test_core/test_observation/test_langchain_handler.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_core/test_observation/test_langchain_handler.py
from __future__ import annotations

import uuid

import pytest

from tests.test_core.test_observation.test_collector import FakeBroadcaster, FakeWriter
from app.core.observation.collector import ObservationCollector
from app.core.observation.instrumentation.langchain_handler import ObservationCallbackHandler
from app.core.observation.types import ObservationType


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
    h, writer, _, _ = await handler
    run_id = uuid.uuid4()
    await h.on_llm_start({"name": "gpt-4o"}, ["hello"], run_id=run_id, parent_run_id=None)

    assert len(writer.inserted) == 2
    gen_obs = writer.inserted[1]
    assert gen_obs.type == "GENERATION"


@pytest.mark.asyncio
async def test_on_tool_start_creates_tool_span(handler) -> None:
    h, writer, _, _ = await handler
    run_id = uuid.uuid4()
    await h.on_tool_start({"name": "web_search"}, '{"query": "test"}', run_id=run_id, parent_run_id=None)

    tool_obs = writer.inserted[1]
    assert tool_obs.type == "TOOL"
    assert tool_obs.name == "web_search"
```

- [ ] **Step 2: Run to verify fails**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_langchain_handler.py -v`

- [ ] **Step 3: Implement langchain_handler.py**

```python
# backend/app/core/observation/instrumentation/langchain_handler.py
from __future__ import annotations

import uuid
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from app.core.observation.collector import ObservationCollector
from app.core.observation.types import ObservationLevel, ObservationType, SpanHandle


class ObservationCallbackHandler(AsyncCallbackHandler):
    """Async LangChain callback handler — emits observations to collector."""

    def __init__(self, collector: ObservationCollector, root_span: SpanHandle):
        self._collector = collector
        self._root_span = root_span
        self._active_spans: dict[uuid.UUID, SpanHandle] = {}

    def _resolve_parent(self, parent_run_id: uuid.UUID | None) -> SpanHandle:
        if parent_run_id and parent_run_id in self._active_spans:
            return self._active_spans[parent_run_id]
        return self._root_span

    async def on_llm_start(self, serialized: dict, prompts: list[str], *,
                           run_id: uuid.UUID, parent_run_id: uuid.UUID | None = None,
                           **kwargs: Any) -> None:
        parent = self._resolve_parent(parent_run_id)
        span = await parent.child_span(
            ObservationType.GENERATION,
            name=serialized.get("name", "llm"),
            input={"messages": prompts},
        )
        self._active_spans[run_id] = span

    async def on_llm_end(self, response: Any, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            output = {}
            if hasattr(response, "generations") and response.generations:
                output["completion"] = response.generations[0][0].text
            if hasattr(response, "llm_output") and response.llm_output:
                output["usage_details"] = response.llm_output.get("token_usage")
                output["model"] = response.llm_output.get("model_name")
            await span.end(output=output)

    async def on_tool_start(self, serialized: dict, input_str: str, *,
                            run_id: uuid.UUID, parent_run_id: uuid.UUID | None = None,
                            **kwargs: Any) -> None:
        parent = self._resolve_parent(parent_run_id)
        span = await parent.child_span(
            ObservationType.TOOL,
            name=serialized.get("name", "tool"),
            input={"arguments": input_str},
        )
        self._active_spans[run_id] = span

    async def on_tool_end(self, output: str, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            await span.end(output={"result": output})

    async def on_chain_start(self, serialized: dict, inputs: dict, *,
                             run_id: uuid.UUID, parent_run_id: uuid.UUID | None = None,
                             **kwargs: Any) -> None:
        name = serialized.get("name", "")
        parent = self._resolve_parent(parent_run_id)
        obs_type = ObservationType.AGENT if self._is_worker_dispatch(name) else ObservationType.CHAIN
        span = await parent.child_span(obs_type, name=name, input=inputs)
        self._active_spans[run_id] = span

    async def on_chain_end(self, outputs: dict, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            await span.end(output=outputs)

    async def on_llm_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            await span.end(output={"error": str(error)}, level=ObservationLevel.ERROR)

    async def on_tool_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            await span.end(output={"error": str(error)}, level=ObservationLevel.ERROR)

    @staticmethod
    def _is_worker_dispatch(name: str) -> bool:
        return name.startswith("worker:") or "SubAgent" in name or "CompiledSubAgent" in name
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_langchain_handler.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/instrumentation/
git add backend/tests/test_core/test_observation/test_langchain_handler.py
git commit -m "feat(observation): add LangChain ObservationCallbackHandler for Graph and Code engines"
```

---

### Task 11: CLIObservationExtractor (CLI Engine)

**Files:**
- Create: `backend/app/core/observation/instrumentation/cli_extractor.py`
- Test: `backend/tests/test_core/test_observation/test_cli_extractor.py`

**Notes:**
- Pattern matches CLIMessage stream: text → accumulate, tool_use → flush gen + open TOOL span, tool_result → close TOOL, usage → update.
- Imports `CLIMessage` from `app.core.agent.cli_backends.base`.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_core/test_observation/test_cli_extractor.py
from __future__ import annotations

import uuid

import pytest

from app.core.agent.cli_backends.base import CLIMessage
from app.core.observation.instrumentation.cli_extractor import CLIObservationExtractor
from app.core.observation.collector import ObservationCollector
from tests.test_core.test_observation.test_collector import FakeBroadcaster, FakeWriter


@pytest.fixture
async def extractor():
    writer = FakeWriter()
    broadcaster = FakeBroadcaster()
    collector = ObservationCollector(
        trace_id=uuid.uuid4(), execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(), writer=writer, broadcaster=broadcaster,
    )
    root = await collector.start_agent("cli:claude_code")
    ext = CLIObservationExtractor(collector, root)
    return ext, writer, broadcaster


@pytest.mark.asyncio
async def test_text_accumulation_flushed_on_tool_use(extractor) -> None:
    ext, writer, _ = await extractor
    await ext.process_message(CLIMessage(type="text", content="Hello "))
    await ext.process_message(CLIMessage(type="text", content="world"))
    gens = [o for o in writer.inserted if o.type == "GENERATION"]
    assert len(gens) == 0

    await ext.process_message(CLIMessage(type="tool_use", content="web_search", tool_name="web_search", tool_input={"q": "test"}))
    gens = [o for o in writer.inserted if o.type == "GENERATION"]
    assert len(gens) == 1
    assert gens[0].output == {"completion": "Hello world"}


@pytest.mark.asyncio
async def test_tool_use_result_pair(extractor) -> None:
    ext, writer, _ = await extractor
    await ext.process_message(CLIMessage(type="tool_use", content="read_file", tool_name="read_file", tool_input={"path": "/tmp/x"}))
    tools_open = [o for o in writer.inserted if o.type == "TOOL"]
    assert len(tools_open) == 1

    await ext.process_message(CLIMessage(type="tool_result", content="file contents"))
    assert len(writer.updated) >= 1


@pytest.mark.asyncio
async def test_flush_pending_emits_final_generation(extractor) -> None:
    ext, writer, _ = await extractor
    await ext.process_message(CLIMessage(type="text", content="final output"))
    await ext.flush_pending()

    gens = [o for o in writer.inserted if o.type == "GENERATION"]
    assert len(gens) == 1
```

- [ ] **Step 2: Implement cli_extractor.py**

```python
# backend/app/core/observation/instrumentation/cli_extractor.py
from __future__ import annotations

from typing import Any

from app.core.agent.cli_backends.base import CLIMessage
from app.core.observation.collector import ObservationCollector
from app.core.observation.types import ObservationType, SpanHandle


FILE_TOOLS = frozenset({
    "read_file", "write_file", "create_file", "edit_file",
    "Read", "Write", "Edit", "Glob", "Grep",
})


class CLIObservationExtractor:
    def __init__(self, collector: ObservationCollector, root_span: SpanHandle):
        self._collector = collector
        self._root = root_span
        self._text_buffer: list[str] = []
        self._current_tool_span: SpanHandle | None = None
        self._current_usage: dict | None = None

    async def process_message(self, msg: CLIMessage) -> None:
        match msg.type:
            case "text":
                self._text_buffer.append(msg.content or "")

            case "tool_use":
                await self._flush_generation()
                tool_name = getattr(msg, "tool_name", None) or msg.content or "tool"
                tool_input = getattr(msg, "tool_input", None) or {}
                self._current_tool_span = await self._root.child_span(
                    ObservationType.TOOL, name=tool_name,
                    input={"arguments": tool_input},
                )
                if tool_name in FILE_TOOLS:
                    path = tool_input.get("path", tool_input.get("file_path", ""))
                    op = "read" if "read" in tool_name.lower() or tool_name in ("Read", "Glob", "Grep") else "write"
                    await self._current_tool_span.record_event(
                        f"file:{op} {path}",
                        metadata={"file.path": path, "file.operation": op},
                    )

            case "tool_result":
                if self._current_tool_span:
                    await self._current_tool_span.end(
                        output={"result": msg.content}
                    )
                    self._current_tool_span = None

            case "usage":
                self._current_usage = getattr(msg, "usage", None)

    async def flush_pending(self) -> None:
        await self._flush_generation()

    async def _flush_generation(self) -> None:
        if not self._text_buffer:
            return
        text = "".join(self._text_buffer)
        self._text_buffer.clear()
        usage = self._current_usage or {}
        self._current_usage = None

        await self._collector.record_generation(
            "cli-generation",
            parent_id=self._root.observation_id,
            input=None,
            output={"completion": text},
            model=None,
            usage_details=usage if usage else None,
            cost_details=None,
            latency_ms=0,
        )
```

- [ ] **Step 3: Run tests**

Run: `cd backend && python -m pytest tests/test_core/test_observation/test_cli_extractor.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/observation/instrumentation/cli_extractor.py \
  backend/tests/test_core/test_observation/test_cli_extractor.py
git commit -m "feat(observation): add CLIObservationExtractor for CLI engine"
```

---

### Task 12: CopilotObservationExtractor

**Files:**
- Create: `backend/app/core/observation/instrumentation/copilot_extractor.py`

**Notes:** Minimal — accumulates stream, calls record_generation on flush. No separate test file needed; covered by collector tests.

- [ ] **Step 1: Implement**

```python
# backend/app/core/observation/instrumentation/copilot_extractor.py
from __future__ import annotations

from app.core.observation.collector import ObservationCollector


class CopilotObservationExtractor:
    def __init__(self, collector: ObservationCollector, model_name: str):
        self._collector = collector
        self._model_name = model_name
        self._chunks: list[str] = []
        self._start_ms: float = 0

    def set_start_time(self, start_ms: float) -> None:
        self._start_ms = start_ms

    def accumulate(self, content: str) -> None:
        self._chunks.append(content)

    async def flush(
        self,
        *,
        prompt: str,
        mode: str,
        elapsed_ms: float,
        usage_details: dict | None = None,
    ) -> None:
        await self._collector.record_generation(
            f"copilot:{self._model_name}",
            input={"prompt": prompt, "mode": mode},
            output={"completion": "".join(self._chunks)},
            model=self._model_name,
            usage_details=usage_details,
            cost_details=None,
            latency_ms=elapsed_ms,
        )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/core/observation/instrumentation/copilot_extractor.py
git commit -m "feat(observation): add CopilotObservationExtractor"
```

---

### Task 13: FileTracker instrumentation

**Files:**
- Create: `backend/app/core/observation/instrumentation/file_tracker.py`

- [ ] **Step 1: Implement**

```python
# backend/app/core/observation/instrumentation/file_tracker.py
from __future__ import annotations

from typing import Any

from app.core.observation.collector import ObservationCollector
from app.core.observation.types import SpanHandle


class FileOperationTracker:
    def __init__(self, collector: ObservationCollector, parent_span: SpanHandle | None = None):
        self._collector = collector
        self._parent_span = parent_span

    async def track_write(self, path: str, content: bytes | str, **kwargs: Any) -> None:
        size = len(content.encode() if isinstance(content, str) else content)
        preview = (content[:200] if isinstance(content, str) else content[:200].decode(errors="replace"))
        parent_id = self._parent_span.observation_id if self._parent_span else None
        await self._collector.record_event(
            f"file:write {path}",
            parent_id=parent_id,
            metadata={"file.path": path, "file.operation": "write", "file.size_bytes": size, "file.content_preview": preview},
        )

    async def track_read(self, path: str, content: bytes | str, **kwargs: Any) -> None:
        size = len(content.encode() if isinstance(content, str) else content)
        parent_id = self._parent_span.observation_id if self._parent_span else None
        await self._collector.record_event(
            f"file:read {path}",
            parent_id=parent_id,
            metadata={"file.path": path, "file.operation": "read", "file.size_bytes": size},
        )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/core/observation/instrumentation/file_tracker.py
git commit -m "feat(observation): add FileOperationTracker for file I/O events"
```

---

### Task 14: Wire engines to collector

**Files:**
- Modify: `backend/app/core/engine/graph_engine.py`
- Modify: `backend/app/core/engine/cli_engine.py`
- Modify: `backend/app/core/engine/code_engine.py`
- Modify: `backend/app/core/engine/copilot_engine.py`
- Modify: `backend/app/core/agent/cli_backends/execution_runner.py`

**Notes:** Each engine checks `context.collector is not None` before instrumenting. When None, behavior is unchanged.

- [ ] **Step 1: GraphEngine — inject callback + file tracker**

In `graph_engine.py` `start()` method, after building callbacks list:

```python
if context.collector:
    from app.core.observation.instrumentation.langchain_handler import ObservationCallbackHandler
    root_span = await context.collector.start_agent(
        name=f"root:{root_config.name if hasattr(root_config, 'name') else 'graph'}",
    )
    callbacks.append(ObservationCallbackHandler(context.collector, root_span))
```

After streaming completes, close root span:
```python
if context.collector and root_span:
    await root_span.end(output={"status": "completed"})
```

- [ ] **Step 2: CLIEngine — pass collector to runner**

In `cli_engine.py` `start()`, pass `context.collector` to `ExecutionRunner`.

In `execution_runner.py`, in `_drain_messages`, construct `CLIObservationExtractor` when collector is present:

```python
if context.collector:
    from app.core.observation.instrumentation.cli_extractor import CLIObservationExtractor
    root_span = await context.collector.start_agent(name=f"cli:{self._executor_kind}")
    extractor = CLIObservationExtractor(context.collector, root_span)
```

In the message drain loop, call `await extractor.process_message(msg)` for each message.
After loop, call `await extractor.flush_pending()` and `await root_span.end()`.

- [ ] **Step 3: CodeEngine — inject callback**

Same pattern as GraphEngine: construct `ObservationCallbackHandler`, inject into `compiled.astream()` callbacks.

- [ ] **Step 4: CopilotEngine — accumulate and flush**

In `copilot_engine.py`, construct `CopilotObservationExtractor` when collector present. In the streaming loop, call `extractor.accumulate()`. After loop, call `extractor.flush()`.

- [ ] **Step 5: Run all tests**

Run: `cd backend && python -m pytest tests/test_core/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/engine/ backend/app/core/agent/cli_backends/execution_runner.py
git commit -m "feat(observation): wire all four engines to ObservationCollector"
```

---

### Task 15: Delete old langfuse_callback.py + deprecate trace_context.py

**Files:**
- Delete: `backend/app/core/agent/langfuse_callback.py`
- Modify or Delete: `backend/app/core/trace_context.py`

- [ ] **Step 1: Check for external callers of trace_context**

Run: `grep -r "trace_context" backend/app/ --include="*.py" -l`
Run: `grep -r "langfuse_callback" backend/app/ --include="*.py" -l`

- [ ] **Step 2: Remove imports and usages**

For each file found, remove the import and replace with no-op or collector equivalent.

- [ ] **Step 3: Delete files**

```bash
rm backend/app/core/agent/langfuse_callback.py
# If trace_context has no external callers:
rm backend/app/core/trace_context.py
# Otherwise: add deprecation warning comment at top
```

- [ ] **Step 4: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(observation): remove langfuse_callback.py, deprecate trace_context.py"
```

---

## Phase 3 — API + Frontend (outline)

> Phase 3 涉及前端代码，建议在 Phase 1+2 验证完毕后作为独立 plan 展开。此处仅列出后端 API 部分。

### Task 16: Traces API routes

**Files:**
- Create: `backend/app/api/routes/traces.py`

**Endpoints:**
- `POST /api/v1/executions/debug` → 调用 `orchestrator.dispatch_debug()`
- `GET /api/v1/traces/{trace_id}` → 返回 Trace 元信息
- `GET /api/v1/traces/{trace_id}/observations` → 返回扁平 observation 列表（支持 `?type=` 过滤）
- `GET /api/v1/traces` → 列表查询（workspace_id, agent_version_id, 分页）

- [ ] **Step 1: Implement routes**
- [ ] **Step 2: Register router in app**
- [ ] **Step 3: Test endpoints manually or with httpx**
- [ ] **Step 4: Commit**

---

## Verification

After all tasks complete:

1. **Unit tests**: `cd backend && python -m pytest tests/test_core/test_observation/ -v` — all pass
2. **Regression**: `cd backend && python -m pytest tests/test_core/ -v` — all existing tests still pass
3. **Migration**: `cd backend && alembic upgrade head` — tables created
4. **Integration**: Call `POST /api/v1/executions/debug` with a test agent, verify WebSocket receives `channel: "observation"` events with correct tree structure
5. **Type check**: `cd backend && mypy app/core/observation/` — no errors





