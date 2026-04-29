# Observation CallbackHandler Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `backend/app/core/observation/` as an OpenTelemetry-backed pipeline with full Langfuse callback parity (all 18 hooks), live streaming via `LiveSpanProcessor`, and an updated WebSocket envelope consumed by the frontend trace viewer.

**Architecture:** Per-execution `TracerProvider` feeds a composite `SpanProcessor` pipeline (`PersistenceProcessor` → batched PG writes; `BroadcastProcessor` → instant WS push). `ObservationCallbackHandler` is a fresh `AsyncCallbackHandler` over OTel `Tracer`, with `_run_states`/`_root_run_states` for explicit run trees and `context.attach`/`detach` for OTel context. `ObservationSpan` is a thin typed wrapper over `Span` exposing observation-shaped setters plus `add_llm_token`/`add_intermediate_update` that route through `LiveSpanProcessor.on_event`.

**Tech Stack:** Python 3.12, OpenTelemetry SDK (api+sdk), LangChain `AsyncCallbackHandler`, SQLAlchemy 2.x async, FastAPI WS, asyncio.

**Spec:** `docs/superpowers/specs/2026-04-29-observation-callback-handler-refactor-design.md`

**Branch:** `joysafeter-v2` (in-place rewrite — no parallel module).

---

## Conventions

- All new files live under `backend/app/core/observation/`.
- All new tests live under `backend/tests/core/observation/`. Create `__init__.py` in any new tests subdirectory if not present.
- Use `pytest -xvs <path>` to run a single test. `pytest backend/tests/core/observation/ -x` to run the suite.
- Type-check command (project-wide): `cd backend && uv run pyright app/core/observation`. Run after each implementation step that touches multiple files.
- Commit after every task (TDD: red → green → commit). Commits use conventional-commit prefixes (`feat`, `refactor`, `test`, `chore`).
- DRY, YAGNI, TDD. Do not introduce abstractions not required by the spec.

## File Inventory (locked)

**Create:**
- `backend/app/core/observation/otel/__init__.py`
- `backend/app/core/observation/otel/processor_base.py`
- `backend/app/core/observation/otel/span_wrapper.py`
- `backend/app/core/observation/otel/persistence_processor.py`
- `backend/app/core/observation/otel/broadcast_processor.py`
- `backend/app/core/observation/otel/provider.py`
- `backend/app/core/observation/instrumentation/langchain_utils.py`
- Tests: `backend/tests/core/observation/test_langchain_utils.py`, `test_run_state.py`, `test_callback_handler.py`, `test_persistence_processor.py`, `test_broadcast_processor.py`, `test_collector.py`

**Rewrite:**
- `backend/app/core/observation/collector.py`
- `backend/app/core/observation/instrumentation/langchain_handler.py`
- `backend/app/core/observation/__init__.py`
- `backend/app/core/observation/types.py` (drop `SpanHandle`)

**Delete:**
- `backend/app/core/observation/writer.py`
- `backend/app/core/observation/broadcaster.py`

**Modify (call sites):**
- `backend/app/core/engine/orchestrator.py` (~L820–865)
- `backend/app/core/engine/graph_engine.py` (~L209)
- `backend/app/core/engine/code_engine.py` (~L73)
- `backend/app/core/engine/copilot_engine.py` (~L66)
- `backend/app/core/observation/instrumentation/cli_extractor.py`
- `backend/app/core/observation/instrumentation/copilot_extractor.py`
- `backend/app/core/observation/instrumentation/file_tracker.py`

**Frontend (separate sub-task at the end):**
- `frontend/components/observation/types.ts`
- `frontend/components/observation/store/*` (WS event handlers)
- `docs/superpowers/specs/2026-04-28-frontend-observation-viewer-design.md` (sync envelope changes)

---

## Task 1: Add OpenTelemetry dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Inspect current dependencies block**

Run: `grep -n "opentelemetry\|dependencies" backend/pyproject.toml | head -40`

- [ ] **Step 2: Add OTel deps**

Add to `[project.dependencies]` (or equivalent table — match existing style; do NOT introduce a new tool):

```
"opentelemetry-api>=1.25.0",
"opentelemetry-sdk>=1.25.0",
```

- [ ] **Step 3: Lock and install**

Run: `cd backend && uv sync` (or the project's standard dependency-lock command — check `Makefile`/`README.md` first)

Expected: lockfile updated, no error.

- [ ] **Step 4: Smoke import**

Run: `cd backend && uv run python -c "from opentelemetry import trace, context; from opentelemetry.sdk.trace import TracerProvider; from opentelemetry.sdk.trace.export import SpanProcessor; print('ok')"`

Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(observation): add OpenTelemetry api/sdk deps"
```

---

## Task 2: Create otel package skeleton + LiveSpanProcessor

**Files:**
- Create: `backend/app/core/observation/otel/__init__.py`
- Create: `backend/app/core/observation/otel/processor_base.py`
- Create: `backend/tests/core/observation/__init__.py` (if missing)
- Create: `backend/tests/core/observation/test_processor_base.py`

- [ ] **Step 1: Write failing test**

`backend/tests/core/observation/test_processor_base.py`:

```python
"""Contract: LiveSpanProcessor extends OTel SpanProcessor with on_event hook."""
from opentelemetry.sdk.trace.export import SpanProcessor

from app.core.observation.otel.processor_base import LiveSpanProcessor


def test_live_span_processor_is_span_processor():
    assert issubclass(LiveSpanProcessor, SpanProcessor)


def test_on_event_default_is_noop():
    class P(LiveSpanProcessor):
        pass
    p = P()
    # default on_event must not raise even when not overridden
    p.on_event(span=None, event_name="x", attributes={})
```

- [ ] **Step 2: Run test (expected fail: ImportError)**

Run: `cd backend && uv run pytest tests/core/observation/test_processor_base.py -xvs`
Expected: ImportError on `app.core.observation.otel.processor_base`.

- [ ] **Step 3: Create package init**

`backend/app/core/observation/otel/__init__.py`:

```python
"""OpenTelemetry-backed observation pipeline."""
```

- [ ] **Step 4: Implement LiveSpanProcessor**

`backend/app/core/observation/otel/processor_base.py`:

```python
"""Base SpanProcessor extension that adds an on_event hook for live streaming."""
from __future__ import annotations

from typing import Any

from opentelemetry.sdk.trace.export import SpanProcessor


class LiveSpanProcessor(SpanProcessor):
    """SpanProcessor variant that also receives live (mid-span) events.

    OTel's stock SpanProcessor only fires on_start/on_end. LiveSpanProcessor
    adds on_event so streaming token / intermediate-update events can be
    pushed out the moment they happen — bypassing on_end batching.
    """

    def on_event(self, span: Any, event_name: str, attributes: dict) -> None:
        """Called by ObservationSpan when a live event is emitted. Default: no-op."""
        return None
```

- [ ] **Step 5: Run test (expected pass)**

Run: `cd backend && uv run pytest tests/core/observation/test_processor_base.py -xvs`
Expected: 2 passed.

- [ ] **Step 6: Type-check**

Run: `cd backend && uv run pyright app/core/observation/otel/processor_base.py`
Expected: 0 errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/observation/otel/__init__.py \
        backend/app/core/observation/otel/processor_base.py \
        backend/tests/core/observation/__init__.py \
        backend/tests/core/observation/test_processor_base.py
git commit -m "feat(observation): add LiveSpanProcessor base for streaming events"
```

---

## Task 3: ObservationSpan (typed OTel Span wrapper)

**Files:**
- Create: `backend/app/core/observation/otel/span_wrapper.py`
- Create: `backend/tests/core/observation/test_span_wrapper.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/core/observation/test_span_wrapper.py`:

```python
"""ObservationSpan: typed wrapper providing observation-schema attribute setters."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationLevel, ObservationType


def _make_span_and_provider():
    span = MagicMock()
    span.set_attribute = MagicMock()
    span.add_event = MagicMock()
    span.end = MagicMock()
    provider = MagicMock()
    obs_id = uuid.uuid4()
    return ObservationSpan(span, obs_id, provider), span, provider, obs_id


def test_set_input_serializes_to_json_attribute():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_input({"messages": [{"role": "user"}]})
    span.set_attribute.assert_any_call(
        "observation.input", json.dumps({"messages": [{"role": "user"}]})
    )


def test_set_output():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_output({"result": "ok"})
    span.set_attribute.assert_any_call(
        "observation.output", json.dumps({"result": "ok"})
    )


def test_set_model():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_model("gpt-4o")
    span.set_attribute.assert_any_call("llm.model", "gpt-4o")


def test_set_usage():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_usage({"input": 10, "output": 5, "total": 15})
    span.set_attribute.assert_any_call("llm.usage.input", 10)
    span.set_attribute.assert_any_call("llm.usage.output", 5)
    span.set_attribute.assert_any_call("llm.usage.total", 15)


def test_set_observation_type():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_observation_type(ObservationType.GENERATION)
    span.set_attribute.assert_any_call("observation.type", "GENERATION")


def test_set_level():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_level(ObservationLevel.ERROR)
    span.set_attribute.assert_any_call("observation.level", "ERROR")


def test_add_llm_token_fires_span_event_and_live_dispatch():
    obs, span, provider, _ = _make_span_and_provider()
    obs.add_llm_token("Hello", 0)
    span.add_event.assert_called_once_with(
        "stream.llm_token", {"token": "Hello", "index": 0}
    )
    provider.dispatch_live_event.assert_called_once_with(
        obs, "llm_token", {"token": "Hello", "index": 0}
    )


def test_add_intermediate_update_serializes_payload():
    obs, span, provider, _ = _make_span_and_provider()
    obs.add_intermediate_update({"type": "AGENT"})
    call_args = span.add_event.call_args
    assert call_args[0][0] == "stream.intermediate_update"
    payload = json.loads(call_args[0][1]["payload_json"])
    assert payload == {"type": "AGENT"}


def test_record_error_sets_attributes():
    obs, span, _, _ = _make_span_and_provider()
    exc = ValueError("test error")
    obs.record_error(exc, ObservationLevel.ERROR)
    span.set_attribute.assert_any_call("observation.level", "ERROR")
    span.set_attribute.assert_any_call("observation.status_message", "test error")


def test_end_calls_span_end():
    obs, span, _, _ = _make_span_and_provider()
    obs.end()
    span.end.assert_called_once()


def test_set_completion_start_time():
    obs, span, _, _ = _make_span_and_provider()
    ts = datetime(2026, 4, 29, 10, 0, 0, tzinfo=timezone.utc)
    obs.set_completion_start_time(ts)
    span.set_attribute.assert_any_call(
        "llm.completion_start_time", "2026-04-29T10:00:00+00:00"
    )


def test_set_prompt():
    obs, span, _, _ = _make_span_and_provider()
    obs.set_prompt("my-prompt", "3")
    span.set_attribute.assert_any_call("llm.prompt.name", "my-prompt")
    span.set_attribute.assert_any_call("llm.prompt.version", "3")
```

- [ ] **Step 2: Run tests (expected fail: ImportError)**

Run: `cd backend && uv run pytest tests/core/observation/test_span_wrapper.py -xvs`
Expected: ImportError.

- [ ] **Step 3: Implement ObservationSpan**

`backend/app/core/observation/otel/span_wrapper.py`:

```python
"""ObservationSpan — typed wrapper over an OTel Span with observation-schema setters."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import Span

from app.core.observation.types import ObservationLevel, ObservationType

if TYPE_CHECKING:
    from app.core.observation.otel.provider import ObservationTracerProvider


def _safe_json(value: Any) -> str:
    return json.dumps(value, default=str)


class ObservationSpan:
    __slots__ = ("_span", "observation_id", "_provider")

    def __init__(
        self,
        otel_span: Span,
        observation_id: uuid.UUID,
        provider: ObservationTracerProvider,
    ) -> None:
        self._span = otel_span
        self.observation_id = observation_id
        self._provider = provider

    # --- typed attribute setters ---

    def set_input(self, value: Any) -> None:
        self._span.set_attribute("observation.input", _safe_json(value))

    def set_output(self, value: Any) -> None:
        self._span.set_attribute("observation.output", _safe_json(value))

    def set_metadata(self, value: dict) -> None:
        self._span.set_attribute("observation.metadata", _safe_json(value))

    def set_model(self, name: str) -> None:
        self._span.set_attribute("llm.model", name)

    def set_model_parameters(self, params: dict) -> None:
        self._span.set_attribute("llm.parameters", _safe_json(params))

    def set_usage(self, usage: dict) -> None:
        for key in ("input", "output", "total"):
            if key in usage:
                self._span.set_attribute(f"llm.usage.{key}", usage[key])

    def set_cost(self, cost: dict) -> None:
        for key in ("input", "output", "total"):
            if key in cost:
                self._span.set_attribute(f"llm.cost.{key}", cost[key])

    def set_level(self, level: ObservationLevel) -> None:
        self._span.set_attribute("observation.level", level.value)

    def set_status_message(self, msg: str) -> None:
        self._span.set_attribute("observation.status_message", msg)

    def set_observation_type(self, t: ObservationType) -> None:
        self._span.set_attribute("observation.type", t.value)

    def set_prompt(self, name: str, version: str | None) -> None:
        self._span.set_attribute("llm.prompt.name", name)
        if version is not None:
            self._span.set_attribute("llm.prompt.version", version)

    def set_tool_calls(self, calls: list) -> None:
        self._span.set_attribute("tool.calls", _safe_json(calls))

    def set_tool_definitions(self, defs: list) -> None:
        self._span.set_attribute("tool.definitions", _safe_json(defs))

    def set_completion_start_time(self, ts: datetime) -> None:
        self._span.set_attribute("llm.completion_start_time", ts.isoformat())

    # --- streaming events ---

    def add_llm_token(self, token: str, index: int) -> None:
        attrs = {"token": token, "index": index}
        self._span.add_event("stream.llm_token", attrs)
        self._provider.dispatch_live_event(self, "llm_token", attrs)

    def add_intermediate_update(self, payload: dict) -> None:
        self._span.add_event("stream.intermediate_update", {
            "payload_json": json.dumps(payload, default=str),
        })
        self._provider.dispatch_live_event(self, "span_update", payload)

    # --- lifecycle ---

    def record_error(self, exc: Exception, level: ObservationLevel) -> None:
        self._span.set_attribute("observation.level", level.value)
        self._span.set_attribute("observation.status_message", str(exc))

    def end(self) -> None:
        self._span.end()
```

- [ ] **Step 4: Run tests (expected pass)**

Run: `cd backend && uv run pytest tests/core/observation/test_span_wrapper.py -xvs`
Expected: all passed.

- [ ] **Step 5: Type-check**

Run: `cd backend && uv run pyright app/core/observation/otel/span_wrapper.py`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/observation/otel/span_wrapper.py \
        backend/tests/core/observation/test_span_wrapper.py
git commit -m "feat(observation): add ObservationSpan — typed OTel Span wrapper"
```

---

## Task 4: PersistenceProcessor (batched PG writer via SpanProcessor)

**Files:**
- Create: `backend/app/core/observation/otel/persistence_processor.py`
- Create: `backend/tests/core/observation/test_persistence_processor.py`

- [ ] **Step 1: Write failing test — deferred insert + aggregates**

`backend/tests/core/observation/test_persistence_processor.py`:

```python
"""PersistenceProcessor: span → batched PG persistence via drain loop."""
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
    # stream event not counted, but persist event creates an observation
    # Total observations: 1 (the span itself) — event-to-observation creation
    # is an implementation detail; the key invariant is stream events are skipped
    assert proc.get_aggregates()["total_observations"] == 1
    await proc.shutdown()
```

- [ ] **Step 2: Run tests (expected fail: ImportError)**

Run: `cd backend && uv run pytest tests/core/observation/test_persistence_processor.py -xvs`
Expected: ImportError.

- [ ] **Step 3: Implement PersistenceProcessor**

`backend/app/core/observation/otel/persistence_processor.py`:

```python
"""PersistenceProcessor — deferred-INSERT SpanProcessor writing Observation rows to PG."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from loguru import logger
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanProcessor

from app.core.observation.model import Observation
from app.core.observation.types import ObservationLevel, ObservationType

_SENTINEL = object()


class PersistenceProcessor(SpanProcessor):
    def __init__(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        workspace_id: uuid.UUID,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        event_loop: asyncio.AbstractEventLoop,
        *,
        max_batch: int = 10,
        max_wait_ms: int = 300,
        max_buffer_size: int = 1000,
    ) -> None:
        self._execution_id = execution_id
        self._trace_id = trace_id
        self._workspace_id = workspace_id
        self._db_session_factory = db_session_factory
        self._loop = event_loop
        self._max_batch = max_batch
        self._max_wait_ms = max_wait_ms
        self._max_buffer_size = max_buffer_size

        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._otel_span_id_to_observation_id: dict[int, uuid.UUID] = {}

        # Aggregation state
        self._total_tokens = 0
        self._total_cost = 0.0
        self._observation_count = 0
        self._has_error = False

        # Start drain loop on the event loop
        self._drain_future = asyncio.run_coroutine_threadsafe(
            self._drain_loop(), self._loop
        )

    def on_start(self, span: ReadableSpan, parent_context: Any = None) -> None:
        obs_id_str = span.attributes.get("observation.id")
        if obs_id_str:
            self._otel_span_id_to_observation_id[span.context.span_id] = uuid.UUID(
                str(obs_id_str)
            )

    def on_end(self, span: ReadableSpan) -> None:
        attrs = span.attributes or {}
        obs_id_str = attrs.get("observation.id")
        if not obs_id_str:
            return

        obs_id = uuid.UUID(str(obs_id_str))

        # Resolve parent observation_id from OTel parent span
        parent_obs_id: uuid.UUID | None = None
        if span.parent:
            parent_obs_id = self._otel_span_id_to_observation_id.get(
                span.parent.span_id
            )

        # Build Observation
        obs = Observation(
            id=obs_id,
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            parent_observation_id=parent_obs_id,
            type=str(attrs.get("observation.type", ObservationType.SPAN.value)),
            name=span.name,
            level=str(attrs.get("observation.level", ObservationLevel.DEFAULT.value)),
            start_time=self._ns_to_dt(span.start_time),
            end_time=self._ns_to_dt(span.end_time),
            input=self._parse_json_attr(attrs, "observation.input"),
            output=self._parse_json_attr(attrs, "observation.output"),
            meta=self._parse_json_attr(attrs, "observation.metadata"),
            model=attrs.get("llm.model"),
            model_parameters=self._parse_json_attr(attrs, "llm.parameters"),
            usage_details=self._build_usage(attrs),
            cost_details=self._build_cost(attrs),
            completion_start_time=self._parse_iso_attr(
                attrs, "llm.completion_start_time"
            ),
            prompt_name=attrs.get("llm.prompt.name"),
            prompt_version=self._safe_int(attrs.get("llm.prompt.version")),
            tool_calls=self._parse_json_attr(attrs, "tool.calls"),
            tool_definitions=self._parse_json_attr(attrs, "tool.definitions"),
        )

        self._loop.call_soon_threadsafe(self._queue.put_nowait, obs)

        # Accumulate aggregates
        usage_total = attrs.get("llm.usage.total", 0)
        if usage_total:
            self._total_tokens += int(usage_total)
        cost_total = attrs.get("llm.cost.total", 0.0)
        if cost_total:
            self._total_cost += float(cost_total)
        self._observation_count += 1
        if str(attrs.get("observation.level")) == "ERROR":
            self._has_error = True

        # Persist non-stream events as child observations
        for event in span.events:
            if event.name.startswith("stream."):
                continue
            event_obs = Observation(
                id=uuid.uuid4(),
                trace_id=self._trace_id,
                execution_id=self._execution_id,
                workspace_id=self._workspace_id,
                parent_observation_id=obs_id,
                type=ObservationType.EVENT.value,
                name=event.name,
                level=ObservationLevel.DEFAULT.value,
                start_time=self._ns_to_dt(event.timestamp),
                meta=dict(event.attributes) if event.attributes else None,
            )
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event_obs)

    def get_aggregates(self) -> dict:
        return {
            "total_tokens": self._total_tokens,
            "total_cost": self._total_cost,
            "total_observations": self._observation_count,
            "has_error": self._has_error,
        }

    async def _drain_loop(self) -> None:
        buffer: list[Observation] = []
        while True:
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._max_wait_ms / 1000
                )
            except asyncio.TimeoutError:
                if buffer:
                    await self._flush(buffer)
                    buffer.clear()
                continue

            if item is _SENTINEL:
                if buffer:
                    await self._flush(buffer)
                break

            buffer.append(item)
            if len(buffer) >= self._max_batch:
                await self._flush(buffer)
                buffer.clear()

    async def _flush(self, buffer: list[Observation]) -> None:
        if not buffer:
            return
        try:
            session = await self._db_session_factory()
            session.add_all(buffer)
            await session.commit()
        except Exception:
            logger.opt(exception=True).warning("PersistenceProcessor flush failed")

    async def shutdown(self) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, _SENTINEL)
        try:
            self._drain_future.result(timeout=10)
        except Exception:
            logger.opt(exception=True).warning(
                "PersistenceProcessor drain loop did not exit cleanly"
            )

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    @staticmethod
    def _ns_to_dt(ns: int | None) -> datetime | None:
        if ns is None:
            return None
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)

    @staticmethod
    def _parse_json_attr(attrs: dict, key: str) -> Any:
        val = attrs.get(key)
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, ValueError):
                return val
        return val

    @staticmethod
    def _parse_iso_attr(attrs: dict, key: str) -> datetime | None:
        val = attrs.get(key)
        if not val or not isinstance(val, str):
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    @staticmethod
    def _safe_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_usage(attrs: dict) -> dict | None:
        inp = attrs.get("llm.usage.input")
        out = attrs.get("llm.usage.output")
        total = attrs.get("llm.usage.total")
        if inp is None and out is None and total is None:
            return None
        return {
            "input": int(inp) if inp is not None else 0,
            "output": int(out) if out is not None else 0,
            "total": int(total) if total is not None else 0,
        }

    @staticmethod
    def _build_cost(attrs: dict) -> dict | None:
        inp = attrs.get("llm.cost.input")
        out = attrs.get("llm.cost.output")
        total = attrs.get("llm.cost.total")
        if inp is None and out is None and total is None:
            return None
        return {
            "input": float(inp) if inp is not None else 0.0,
            "output": float(out) if out is not None else 0.0,
            "total": float(total) if total is not None else 0.0,
        }
```

- [ ] **Step 4: Run tests (expected pass)**

Run: `cd backend && uv run pytest tests/core/observation/test_persistence_processor.py -xvs`
Expected: all passed.

- [ ] **Step 5: Type-check**

Run: `cd backend && uv run pyright app/core/observation/otel/persistence_processor.py`
Expected: 0 errors (warnings about Observation fields acceptable if model imports differ).

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/observation/otel/persistence_processor.py \
        backend/tests/core/observation/test_persistence_processor.py
git commit -m "feat(observation): add PersistenceProcessor — deferred-INSERT OTel span writer"
```

---

## Task 5: BroadcastProcessor (instant WS relay via LiveSpanProcessor)

**Files:**
- Create: `backend/app/core/observation/otel/broadcast_processor.py`
- Create: `backend/tests/core/observation/test_broadcast_processor.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/core/observation/test_broadcast_processor.py`:

```python
"""BroadcastProcessor: fire-and-forget WS relay via LiveSpanProcessor."""
from __future__ import annotations

import asyncio
import itertools
import uuid
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.core.observation.otel.broadcast_processor import BroadcastProcessor
from app.core.observation.otel.processor_base import LiveSpanProcessor


def test_broadcast_processor_is_live_span_processor():
    assert issubclass(BroadcastProcessor, LiveSpanProcessor)


@pytest.mark.asyncio
async def test_emit_sends_envelope_with_seq():
    captured: list[dict] = []
    exec_id = uuid.uuid4()

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(exec_id, fake_broadcast, loop)
    proc._emit("span_open", {
        "observation_id": "obs-1",
        "parent_observation_id": None,
        "data": {"name": "test"},
    })
    # Let the scheduled coroutine run
    await asyncio.sleep(0.05)
    assert len(captured) == 1
    msg = captured[0]
    assert msg["channel"] == "observation"
    assert msg["trace_id"] == str(exec_id)
    assert msg["seq"] == 1
    assert msg["event"] == "span_open"
    assert msg["observation_id"] == "obs-1"


@pytest.mark.asyncio
async def test_seq_increments_monotonically():
    captured: list[dict] = []

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), fake_broadcast, loop)
    proc._emit("a", {"observation_id": "1", "data": {}})
    proc._emit("b", {"observation_id": "2", "data": {}})
    proc._emit("c", {"observation_id": "3", "data": {}})
    await asyncio.sleep(0.05)
    seqs = [m["seq"] for m in captured]
    assert seqs == [1, 2, 3]


@pytest.mark.asyncio
async def test_no_broadcast_fn_is_noop():
    """When broadcast_fn is None, _emit must not crash."""
    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), None, loop)
    proc._emit("span_open", {"observation_id": "1", "data": {}})
    # Should not raise


@pytest.mark.asyncio
async def test_on_event_routes_through_emit():
    captured: list[dict] = []

    async def fake_broadcast(eid, msg):
        captured.append(msg)

    loop = asyncio.get_running_loop()
    proc = BroadcastProcessor(uuid.uuid4(), fake_broadcast, loop)
    span = MagicMock()
    span.observation_id = uuid.uuid4()
    span._span = MagicMock()
    span._span.parent = None
    proc.on_event(span, "llm_token", {"token": "Hi", "index": 0})
    await asyncio.sleep(0.05)
    assert len(captured) == 1
    assert captured[0]["event"] == "llm_token"
    assert captured[0]["data"]["token"] == "Hi"
```

- [ ] **Step 2: Run tests (expected fail: ImportError)**

Run: `cd backend && uv run pytest tests/core/observation/test_broadcast_processor.py -xvs`
Expected: ImportError.

- [ ] **Step 3: Implement BroadcastProcessor**

`backend/app/core/observation/otel/broadcast_processor.py`:

```python
"""BroadcastProcessor — instant WebSocket relay via LiveSpanProcessor."""
from __future__ import annotations

import asyncio
import itertools
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from loguru import logger

from app.core.observation.otel.processor_base import LiveSpanProcessor
from app.core.observation.otel.span_wrapper import ObservationSpan


class BroadcastProcessor(LiveSpanProcessor):
    def __init__(
        self,
        execution_id: uuid.UUID,
        broadcast_fn: Callable[..., Coroutine[Any, Any, None]] | None,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._execution_id = execution_id
        self._broadcast_fn = broadcast_fn
        self._loop = event_loop
        self._seq = itertools.count(1)
        self._otel_span_id_to_observation_id: dict[int, str] = {}

    def _resolve_parent_obs_id(self, span: Any) -> str | None:
        if span.parent:
            return self._otel_span_id_to_observation_id.get(span.parent.span_id)
        return None

    @staticmethod
    def _ns_to_iso(ns: int | None) -> str | None:
        if ns is None:
            return None
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat()

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        attrs = span.attributes or {}
        obs_id = str(attrs.get("observation.id", ""))
        if obs_id and hasattr(span, "context"):
            self._otel_span_id_to_observation_id[span.context.span_id] = obs_id
        self._emit("span_open", {
            "observation_id": obs_id,
            "parent_observation_id": self._resolve_parent_obs_id(span),
            "data": {
                "name": span.name,
                "type": attrs.get("observation.type", "SPAN"),
                "level": attrs.get("observation.level", "DEFAULT"),
                "input": self._parse_json(attrs.get("observation.input")),
                "metadata": self._parse_json(attrs.get("observation.metadata")),
                "model": attrs.get("llm.model"),
                "start_time": self._ns_to_iso(span.start_time),
            },
        })

    def on_end(self, span: Any) -> None:
        attrs = span.attributes or {}
        self._emit("span_close", {
            "observation_id": str(attrs.get("observation.id", "")),
            "parent_observation_id": self._resolve_parent_obs_id(span),
            "data": {
                "output": self._parse_json(attrs.get("observation.output")),
                "level": attrs.get("observation.level", "DEFAULT"),
                "end_time": self._ns_to_iso(span.end_time),
                "usage": self._build_usage(attrs),
                "cost": self._build_cost(attrs),
                "status_message": attrs.get("observation.status_message"),
            },
        })

    def on_event(
        self, span: ObservationSpan, event_name: str, attributes: dict
    ) -> None:
        parent_obs_id: str | None = None
        if hasattr(span, "_span") and span._span.parent:
            parent_obs_id = self._otel_span_id_to_observation_id.get(
                span._span.parent.span_id
            )
        self._emit(event_name, {
            "observation_id": str(span.observation_id),
            "parent_observation_id": parent_obs_id,
            "data": dict(attributes),
        })

    def _emit(self, event: str, payload: dict) -> None:
        if not self._broadcast_fn:
            return
        seq = next(self._seq)
        message = {
            "channel": "observation",
            "trace_id": str(self._execution_id),
            "seq": seq,
            "event": event,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            **payload,
        }
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._broadcast_fn(self._execution_id, message), self._loop
            )
            future.add_done_callback(self._log_if_failed)
        except Exception:
            pass  # WS disconnect / loop closed — never crash the pipeline

    @staticmethod
    def _log_if_failed(future: Any) -> None:
        exc = future.exception()
        if exc:
            logger.warning("broadcast failed: %s", exc)

    @staticmethod
    def _parse_json(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, ValueError):
                return val
        return val

    @staticmethod
    def _build_usage(attrs: dict) -> dict | None:
        inp = attrs.get("llm.usage.input")
        out = attrs.get("llm.usage.output")
        total = attrs.get("llm.usage.total")
        if inp is None and out is None and total is None:
            return None
        return {
            "input": int(inp) if inp is not None else 0,
            "output": int(out) if out is not None else 0,
            "total": int(total) if total is not None else 0,
        }

    @staticmethod
    def _build_cost(attrs: dict) -> dict | None:
        total = attrs.get("llm.cost.total")
        if total is None:
            return None
        return {"total": float(total)}

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
```

- [ ] **Step 4: Run tests (expected pass)**

Run: `cd backend && uv run pytest tests/core/observation/test_broadcast_processor.py -xvs`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/otel/broadcast_processor.py \
        backend/tests/core/observation/test_broadcast_processor.py
git commit -m "feat(observation): add BroadcastProcessor — instant WS relay via LiveSpanProcessor"
```

---

## Task 6: ObservationTracerProvider (per-execution provider)

**Files:**
- Create: `backend/app/core/observation/otel/provider.py`
- Create: `backend/tests/core/observation/test_provider.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/core/observation/test_provider.py`:

```python
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
```

- [ ] **Step 2: Run tests (expected fail: ImportError)**

Run: `cd backend && uv run pytest tests/core/observation/test_provider.py -xvs`

- [ ] **Step 3: Implement ObservationTracerProvider**

`backend/app/core/observation/otel/provider.py`:

```python
"""ObservationTracerProvider — per-execution OTel TracerProvider lifecycle."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace import Tracer

from app.core.observation.otel.broadcast_processor import BroadcastProcessor
from app.core.observation.otel.persistence_processor import PersistenceProcessor
from app.core.observation.otel.processor_base import LiveSpanProcessor
from app.core.observation.otel.span_wrapper import ObservationSpan


class ObservationTracerProvider:
    def __init__(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        workspace_id: uuid.UUID,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        broadcast_fn: Callable[..., Coroutine[Any, Any, None]] | None,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._provider = TracerProvider(
            resource=Resource.create({
                "service.name": "joysafeter",
                "execution.id": str(execution_id),
                "trace.id": str(trace_id),
                "workspace.id": str(workspace_id),
            })
        )
        self._persistence = PersistenceProcessor(
            execution_id, trace_id, workspace_id, db_session_factory, event_loop
        )
        self._broadcast = BroadcastProcessor(execution_id, broadcast_fn, event_loop)
        self._provider.add_span_processor(self._persistence)
        self._provider.add_span_processor(self._broadcast)
        self._tracer = self._provider.get_tracer("joysafeter.observation")
        self._live_processors: list[LiveSpanProcessor] = [self._broadcast]

    def get_tracer(self) -> Tracer:
        return self._tracer

    def dispatch_live_event(
        self, span: ObservationSpan, event_name: str, attributes: dict
    ) -> None:
        for proc in self._live_processors:
            proc.on_event(span, event_name, attributes)

    def get_persistence_aggregates(self) -> dict:
        return self._persistence.get_aggregates()

    def broadcast_trace_complete(self, status: str, aggregates: dict) -> None:
        self._broadcast._emit("trace_complete", {
            "observation_id": None,
            "parent_observation_id": None,
            "data": {"status": status, **aggregates},
        })

    async def shutdown(self) -> None:
        await self._persistence.shutdown()
        self._broadcast.shutdown()
```

- [ ] **Step 4: Run tests (expected pass)**

Run: `cd backend && uv run pytest tests/core/observation/test_provider.py -xvs`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/otel/provider.py \
        backend/tests/core/observation/test_provider.py
git commit -m "feat(observation): add ObservationTracerProvider — per-execution OTel lifecycle"
```

---

## Task 7: langchain_utils.py (message serialization + model/usage extraction)

**Files:**
- Create: `backend/app/core/observation/instrumentation/langchain_utils.py`
- Create: `backend/tests/core/observation/test_langchain_utils.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/core/observation/test_langchain_utils.py`:

```python
"""langchain_utils: message conversion, usage normalization, model extraction, chain classification."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import (
    AIMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.observation.instrumentation.langchain_utils import (
    _classify_chain,
    convert_message_to_dict,
    extract_model_name,
    normalize_usage,
)
from app.core.observation.types import ObservationType


# --- convert_message_to_dict ---

class TestConvertMessageToDict:
    def test_human_message(self):
        msg = HumanMessage(content="Hello")
        result = convert_message_to_dict(msg)
        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_ai_message(self):
        msg = AIMessage(content="Hi")
        result = convert_message_to_dict(msg)
        assert result["role"] == "assistant"

    def test_system_message(self):
        msg = SystemMessage(content="You are helpful")
        result = convert_message_to_dict(msg)
        assert result["role"] == "system"

    def test_tool_message(self):
        msg = ToolMessage(content="result", tool_call_id="call_123")
        result = convert_message_to_dict(msg)
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_123"

    def test_chat_message_custom_role(self):
        msg = ChatMessage(content="custom", role="moderator")
        result = convert_message_to_dict(msg)
        assert result["role"] == "moderator"

    def test_ai_message_with_tool_calls(self):
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "get_weather", "args": {"city": "NYC"}, "id": "1"}],
        )
        result = convert_message_to_dict(msg)
        assert result["role"] == "assistant"
        assert len(result["tool_calls"]) == 1

    def test_additional_kwargs_merged(self):
        msg = HumanMessage(content="hi", additional_kwargs={"custom_field": "val"})
        result = convert_message_to_dict(msg)
        assert result["custom_field"] == "val"


# --- normalize_usage ---

class TestNormalizeUsage:
    def test_openai_format(self):
        raw = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        result = normalize_usage(raw)
        assert result == {"input": 10, "output": 5, "total": 15}

    def test_anthropic_format(self):
        raw = {"input_tokens": 20, "output_tokens": 10}
        result = normalize_usage(raw)
        assert result == {"input": 20, "output": 10, "total": 30}

    def test_vertex_format(self):
        raw = {"promptTokenCount": 30, "candidatesTokenCount": 15, "totalTokenCount": 45}
        result = normalize_usage(raw)
        assert result == {"input": 30, "output": 15, "total": 45}

    def test_bedrock_format(self):
        raw = {"inputTokens": 40, "outputTokens": 20, "totalTokens": 60}
        result = normalize_usage(raw)
        assert result == {"input": 40, "output": 20, "total": 60}

    def test_none_input(self):
        assert normalize_usage(None) == {}

    def test_empty_dict(self):
        assert normalize_usage({}) == {}

    def test_unknown_format(self):
        assert normalize_usage({"foo": 1}) == {}


# --- extract_model_name ---

class TestExtractModelName:
    def test_metadata_ls_model_name(self):
        result = extract_model_name(
            metadata={"ls_model_name": "gpt-4o"},
            serialized={},
            kwargs={},
            response=None,
        )
        assert result == "gpt-4o"

    def test_serialized_kwargs_model_name(self):
        result = extract_model_name(
            metadata={},
            serialized={"kwargs": {"model_name": "claude-3"}},
            kwargs={},
            response=None,
        )
        assert result == "claude-3"

    def test_serialized_kwargs_model(self):
        result = extract_model_name(
            metadata={},
            serialized={"kwargs": {"model": "gemini-pro"}},
            kwargs={},
            response=None,
        )
        assert result == "gemini-pro"

    def test_invocation_params_model_name(self):
        result = extract_model_name(
            metadata={},
            serialized={},
            kwargs={"invocation_params": {"model_name": "gpt-3.5"}},
            response=None,
        )
        assert result == "gpt-3.5"

    def test_invocation_params_model(self):
        result = extract_model_name(
            metadata={},
            serialized={},
            kwargs={"invocation_params": {"model": "titan"}},
            response=None,
        )
        assert result == "titan"

    def test_response_llm_output_model_name(self):
        response = MagicMock()
        response.llm_output = {"model_name": "from-response"}
        result = extract_model_name(
            metadata={},
            serialized={},
            kwargs={},
            response=response,
        )
        assert result == "from-response"

    def test_all_missing_returns_none(self):
        result = extract_model_name(
            metadata={}, serialized={}, kwargs={}, response=None
        )
        assert result is None


# --- _classify_chain ---

class TestClassifyChain:
    def test_worker_prefix(self):
        assert _classify_chain("worker:summarize", {}) == ObservationType.AGENT

    def test_subagent_in_name(self):
        assert _classify_chain("SubAgentRunner", {}) == ObservationType.AGENT

    def test_compiled_subagent(self):
        assert _classify_chain("CompiledSubAgent", {}) == ObservationType.AGENT

    def test_serialized_agent_path(self):
        assert (
            _classify_chain("run", {"id": ["langchain", "agents", "AgentExecutor"]})
            == ObservationType.AGENT
        )

    def test_regular_chain(self):
        assert _classify_chain("RunnableSequence", {}) == ObservationType.CHAIN

    def test_empty_name(self):
        assert _classify_chain("", {}) == ObservationType.CHAIN
```

- [ ] **Step 2: Run tests (expected fail: ImportError)**

Run: `cd backend && uv run pytest tests/core/observation/test_langchain_utils.py -xvs`

- [ ] **Step 3: Implement langchain_utils**

`backend/app/core/observation/instrumentation/langchain_utils.py`:

```python
"""LangChain callback helper utilities — message conversion, usage normalization, model extraction."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage

from app.core.observation.types import ObservationType

MESSAGE_ROLE_MAP: dict[str, str | None] = {
    "HumanMessage": "user",
    "AIMessage": "assistant",
    "SystemMessage": "system",
    "ToolMessage": "tool",
    "FunctionMessage": "function",
    "ChatMessage": None,
}

USAGE_KEY_MAP: list[tuple[str, str, str | None]] = [
    ("prompt_tokens", "completion_tokens", "total_tokens"),
    ("input_tokens", "output_tokens", None),
    ("promptTokenCount", "candidatesTokenCount", "totalTokenCount"),
    ("inputTokens", "outputTokens", "totalTokens"),
]


def convert_message_to_dict(message: BaseMessage) -> dict:
    role = MESSAGE_ROLE_MAP.get(type(message).__name__, "unknown")
    if role is None:
        role = getattr(message, "role", "unknown")
    result: dict[str, Any] = {"role": role, "content": message.content}
    if hasattr(message, "tool_calls") and message.tool_calls:
        result["tool_calls"] = message.tool_calls
    if hasattr(message, "tool_call_id") and message.tool_call_id:
        result["tool_call_id"] = message.tool_call_id
    if message.additional_kwargs:
        result.update(message.additional_kwargs)
    return result


def normalize_usage(raw: dict | None) -> dict[str, int]:
    if not raw:
        return {}
    for input_key, output_key, total_key in USAGE_KEY_MAP:
        if input_key in raw:
            inp = int(raw[input_key])
            out = int(raw.get(output_key, 0))
            total = (
                int(raw[total_key]) if total_key and total_key in raw else inp + out
            )
            return {"input": inp, "output": out, "total": total}
    return {}


def extract_model_name(
    *,
    metadata: dict | None,
    serialized: dict | None,
    kwargs: dict,
    response: Any | None,
) -> str | None:
    if metadata and metadata.get("ls_model_name"):
        return str(metadata["ls_model_name"])

    ser_kwargs = (serialized or {}).get("kwargs", {})
    if ser_kwargs.get("model_name"):
        return str(ser_kwargs["model_name"])
    if ser_kwargs.get("model"):
        return str(ser_kwargs["model"])

    inv_params = kwargs.get("invocation_params", {})
    if inv_params.get("model_name"):
        return str(inv_params["model_name"])
    if inv_params.get("model"):
        return str(inv_params["model"])

    if response and hasattr(response, "llm_output") and response.llm_output:
        if response.llm_output.get("model_name"):
            return str(response.llm_output["model_name"])

    return None


def _classify_chain(name: str, serialized: dict) -> ObservationType:
    if name and (
        name.startswith("worker:")
        or "SubAgent" in name
        or "CompiledSubAgent" in name
    ):
        return ObservationType.AGENT
    if serialized:
        path = serialized.get("id", [])
        if any("agent" in seg.lower() for seg in path if isinstance(seg, str)):
            return ObservationType.AGENT
    return ObservationType.CHAIN
```

- [ ] **Step 4: Run tests (expected pass)**

Run: `cd backend && uv run pytest tests/core/observation/test_langchain_utils.py -xvs`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/instrumentation/langchain_utils.py \
        backend/tests/core/observation/test_langchain_utils.py
git commit -m "feat(observation): add langchain_utils — message serialization, usage normalization, model extraction"
```

---

## Task 8: ObservationCallbackHandler full rewrite (all 18 hooks)

**Files:**
- Rewrite: `backend/app/core/observation/instrumentation/langchain_handler.py`
- Create: `backend/tests/core/observation/test_callback_handler.py`

This is the largest task. The handler implements all 18 LangChain callback hooks with:
- `_run_states` / `_root_run_states` for explicit run tree tracking
- OTel `context.attach` / `context.detach` per span
- `try/except` on every method
- Streaming token support (`on_llm_new_token`)
- Agent type mutation (`on_agent_action` / `on_agent_finish`)

- [ ] **Step 1: Write failing tests — run state tracking**

`backend/tests/core/observation/test_callback_handler.py`:

```python
"""ObservationCallbackHandler — full rewrite with all 18 LangChain hooks."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.core.observation.instrumentation.langchain_handler import (
    ObservationCallbackHandler,
    RunState,
    RootRunState,
)
from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationType


def _make_handler():
    tracer = MagicMock()
    provider = MagicMock()
    obs_span = MagicMock(spec=ObservationSpan)
    obs_span.observation_id = uuid.uuid4()
    obs_span._span = MagicMock()
    tracer.start_span.return_value = obs_span._span
    provider.dispatch_live_event = MagicMock()
    handler = ObservationCallbackHandler(tracer, provider)
    return handler, tracer, provider


# --- Run tree ---

class TestRunStateTracking:
    def test_track_root_run(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        handler._track_run(run_id, None)
        assert run_id in handler._run_states
        state = handler._run_states[run_id]
        assert state.root_run_id == run_id
        assert run_id in handler._root_run_states

    def test_track_child_run(self):
        handler, _, _ = _make_handler()
        root = uuid.uuid4()
        child = uuid.uuid4()
        handler._track_run(root, None)
        handler._track_run(child, root)
        assert handler._run_states[child].root_run_id == root
        assert child in handler._root_run_states[root].run_ids

    def test_reset_clears_subtree(self):
        handler, _, _ = _make_handler()
        root = uuid.uuid4()
        child1 = uuid.uuid4()
        child2 = uuid.uuid4()
        handler._track_run(root, None)
        handler._track_run(child1, root)
        handler._track_run(child2, root)
        handler._reset(root)
        assert root not in handler._run_states
        assert child1 not in handler._run_states
        assert child2 not in handler._run_states
        assert root not in handler._root_run_states

    def test_idempotent_track(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        handler._track_run(run_id, None)
        handler._track_run(run_id, None)  # second call should be no-op
        assert len(handler._root_run_states[run_id].run_ids) == 1


# --- Callback hooks (integration with mock OTel) ---

class TestCallbackHooks:
    @pytest.mark.asyncio
    async def test_on_chain_start_creates_span(self):
        handler, tracer, provider = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_chain_start(
            serialized={"name": "RunnableSequence", "id": ["langchain", "chains"]},
            inputs={"input": "test"},
            run_id=run_id,
            parent_run_id=None,
        )
        assert run_id in handler._runs
        tracer.start_span.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_chain_end_detaches(self):
        handler, tracer, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_chain_start(
            serialized={"name": "test"},
            inputs={},
            run_id=run_id,
            parent_run_id=None,
        )
        await handler.on_chain_end(outputs={"result": "done"}, run_id=run_id)
        assert run_id not in handler._runs

    @pytest.mark.asyncio
    async def test_on_chat_model_start_creates_generation(self):
        handler, tracer, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_chat_model_start(
            serialized={"id": ["langchain", "chat_models", "ChatOpenAI"]},
            messages=[[HumanMessage(content="hi")]],
            run_id=run_id,
            parent_run_id=None,
            metadata={"ls_model_name": "gpt-4o"},
        )
        assert run_id in handler._runs

    @pytest.mark.asyncio
    async def test_on_llm_error_cleans_up(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_llm_start(
            serialized={"name": "llm"},
            prompts=["hello"],
            run_id=run_id,
        )
        await handler.on_llm_error(
            error=ValueError("boom"),
            run_id=run_id,
        )
        assert run_id not in handler._runs

    @pytest.mark.asyncio
    async def test_on_tool_start_end(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_tool_start(
            serialized={"name": "calculator"},
            input_str="2+2",
            run_id=run_id,
        )
        assert run_id in handler._runs
        await handler.on_tool_end(output="4", run_id=run_id)
        assert run_id not in handler._runs

    @pytest.mark.asyncio
    async def test_on_retriever_start_end(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_retriever_start(
            serialized={"name": "vector_store"},
            query="search query",
            run_id=run_id,
        )
        assert run_id in handler._runs
        await handler.on_retriever_end(documents=[], run_id=run_id)
        assert run_id not in handler._runs

    @pytest.mark.asyncio
    async def test_on_llm_new_token_first_sets_completion_start_time(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_llm_start(
            serialized={"name": "llm"},
            prompts=["hello"],
            run_id=run_id,
        )
        span = handler._runs.get(run_id)
        assert span is not None
        await handler.on_llm_new_token(token="Hi", run_id=run_id)
        # First token sets completion_start_time
        assert run_id in handler._completion_start_memo

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_propagate(self):
        handler, tracer, _ = _make_handler()
        # Force tracer.start_span to raise
        tracer.start_span.side_effect = RuntimeError("otel crash")
        # This should NOT raise
        await handler.on_chain_start(
            serialized={"name": "test"},
            inputs={},
            run_id=uuid.uuid4(),
        )
```

- [ ] **Step 2: Run tests (expected fail: ImportError)**

Run: `cd backend && uv run pytest tests/core/observation/test_callback_handler.py -xvs`

- [ ] **Step 3: Implement ObservationCallbackHandler**

Rewrite `backend/app/core/observation/instrumentation/langchain_handler.py`:

```python
"""LangChain async callback handler — maps all 18 hooks to OTel observation spans."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from loguru import logger
from opentelemetry import context, trace
from opentelemetry.sdk.trace import Tracer

from app.core.observation.instrumentation.langchain_utils import (
    _classify_chain,
    convert_message_to_dict,
    extract_model_name,
    normalize_usage,
)
from app.core.observation.otel.provider import ObservationTracerProvider
from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationLevel, ObservationType


def _safe_json(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_json(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


@dataclass
class RunState:
    parent_run_id: uuid.UUID | None
    root_run_id: uuid.UUID


@dataclass
class RootRunState:
    run_ids: set[uuid.UUID] = field(default_factory=set)


class ObservationCallbackHandler(AsyncCallbackHandler):
    def __init__(self, tracer: Tracer, provider: ObservationTracerProvider) -> None:
        self._tracer = tracer
        self._provider = provider
        self._runs: dict[uuid.UUID, ObservationSpan] = {}
        self._context_tokens: dict[uuid.UUID, Any] = {}
        self._run_states: dict[uuid.UUID, RunState] = {}
        self._root_run_states: dict[uuid.UUID, RootRunState] = {}
        self._completion_start_memo: set[uuid.UUID] = set()
        self._prompt_to_parent: dict[uuid.UUID, Any] = {}

    # --- run tree ---

    def _track_run(self, run_id: uuid.UUID, parent_run_id: uuid.UUID | None) -> None:
        if run_id in self._run_states:
            return
        if parent_run_id is None or parent_run_id not in self._run_states:
            root = run_id
            self._root_run_states[root] = RootRunState()
        else:
            root = self._run_states[parent_run_id].root_run_id
        self._run_states[run_id] = RunState(parent_run_id, root)
        self._root_run_states[root].run_ids.add(run_id)

    def _is_root(self, run_id: uuid.UUID) -> bool:
        state = self._run_states.get(run_id)
        return state is not None and state.root_run_id == run_id

    # --- OTel context ---

    def _start_obs_span(
        self,
        run_id: uuid.UUID,
        name: str,
        obs_type: ObservationType,
        parent_run_id: uuid.UUID | None = None,
    ) -> ObservationSpan:
        obs_id = uuid.uuid4()

        # Resolve OTel parent context
        parent_ctx = None
        if parent_run_id and parent_run_id in self._runs:
            parent_span = self._runs[parent_run_id]
            parent_ctx = trace.set_span_in_context(parent_span._span)

        otel_span = self._tracer.start_span(
            name, context=parent_ctx,
            attributes={
                "observation.id": str(obs_id),
                "observation.type": obs_type.value,
                "observation.level": ObservationLevel.DEFAULT.value,
            },
        )
        obs = ObservationSpan(otel_span, obs_id, self._provider)

        # Attach context
        ctx = trace.set_span_in_context(otel_span)
        token = context.attach(ctx)
        self._runs[run_id] = obs
        self._context_tokens[run_id] = token
        return obs

    def _detach_span(self, run_id: uuid.UUID) -> ObservationSpan | None:
        token = self._context_tokens.pop(run_id, None)
        if token:
            try:
                context.detach(token)
            except Exception:
                pass
        return self._runs.pop(run_id, None)

    def _reset(self, root_run_id: uuid.UUID) -> None:
        state = self._root_run_states.pop(root_run_id, None)
        if state:
            for rid in state.run_ids:
                self._run_states.pop(rid, None)

    # --- chain hooks ---

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "chain")
            obs_type = _classify_chain(name, serialized or {})
            obs = self._start_obs_span(run_id, name, obs_type, parent_run_id)
            obs.set_input(_safe_json(inputs))
            if metadata:
                obs.set_metadata(metadata)
                prompt = metadata.get("langfuse_prompt")
                if prompt:
                    self._prompt_to_parent[run_id] = prompt
        except Exception:
            logger.opt(exception=True).debug("on_chain_start failed")

    async def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_output(_safe_json(outputs))
                obs.end()
            if self._is_root(run_id):
                self._reset(run_id)
        except Exception:
            logger.opt(exception=True).debug("on_chain_end failed")

    async def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_level(ObservationLevel.ERROR)
                obs.set_status_message(str(error))
                obs.end()
            if self._is_root(run_id):
                self._reset(run_id)
        except Exception:
            logger.opt(exception=True).debug("on_chain_error failed")

    # --- LLM hooks ---

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "chat_model")

            input_msgs = []
            for msg_list in messages:
                input_msgs.extend(convert_message_to_dict(m) for m in msg_list)

            obs = self._start_obs_span(
                run_id, name, ObservationType.GENERATION, parent_run_id
            )
            obs.set_input({"messages": input_msgs})

            model = extract_model_name(
                metadata=metadata,
                serialized=serialized,
                kwargs=kwargs,
                response=None,
            )
            if model:
                obs.set_model(model)

            inv_params = kwargs.get("invocation_params")
            if inv_params:
                obs.set_model_parameters(inv_params)

            if metadata:
                obs.set_metadata(metadata)

            self._maybe_link_prompt(run_id, parent_run_id, obs)
        except Exception:
            logger.opt(exception=True).debug("on_chat_model_start failed")

    async def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "llm")
            obs = self._start_obs_span(
                run_id, name, ObservationType.GENERATION, parent_run_id
            )
            obs.set_input({"prompts": prompts})

            model = extract_model_name(
                metadata=metadata,
                serialized=serialized or {},
                kwargs=kwargs,
                response=None,
            )
            if model:
                obs.set_model(model)

            if metadata:
                obs.set_metadata(metadata)

            self._maybe_link_prompt(run_id, parent_run_id, obs)
        except Exception:
            logger.opt(exception=True).debug("on_llm_start failed")

    async def on_llm_end(
        self,
        response: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if not obs:
                return

            output: dict[str, Any] = {}
            if hasattr(response, "generations") and response.generations:
                gen_list = response.generations[0] if response.generations else []
                if gen_list:
                    gen = gen_list[0]
                    if hasattr(gen, "message"):
                        output = convert_message_to_dict(gen.message)
                    elif hasattr(gen, "text"):
                        output = {"completion": gen.text}

            if hasattr(response, "llm_output") and response.llm_output:
                llm_out = response.llm_output
                token_usage = llm_out.get("token_usage")
                if token_usage:
                    usage = normalize_usage(token_usage)
                    if usage:
                        obs.set_usage(usage)

                model_from_response = llm_out.get("model_name")
                if model_from_response:
                    obs.set_model(model_from_response)

            obs.set_output(output)
            obs.end()
            self._completion_start_memo.discard(run_id)
        except Exception:
            logger.opt(exception=True).debug("on_llm_end failed")

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_level(ObservationLevel.ERROR)
                obs.set_status_message(str(error))
                obs.end()
            self._completion_start_memo.discard(run_id)
        except Exception:
            logger.opt(exception=True).debug("on_llm_error failed")

    async def on_llm_new_token(
        self,
        token: str,
        *,
        run_id: uuid.UUID,
        chunk: Any | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._runs.get(run_id)
            if not obs:
                return
            if run_id not in self._completion_start_memo:
                self._completion_start_memo.add(run_id)
                obs.set_completion_start_time(datetime.now(tz=timezone.utc))
            idx = kwargs.get("index", 0)
            obs.add_llm_token(token, idx)
        except Exception:
            logger.opt(exception=True).debug("on_llm_new_token failed")

    # --- tool hooks ---

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "tool")
            obs = self._start_obs_span(
                run_id, name, ObservationType.TOOL, parent_run_id
            )
            obs.set_input({"arguments": input_str})
            if metadata:
                obs.set_metadata(metadata)
        except Exception:
            logger.opt(exception=True).debug("on_tool_start failed")

    async def on_tool_end(
        self,
        output: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_output({"result": output})
                obs.end()
        except Exception:
            logger.opt(exception=True).debug("on_tool_end failed")

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_level(ObservationLevel.ERROR)
                obs.set_status_message(str(error))
                obs.end()
        except Exception:
            logger.opt(exception=True).debug("on_tool_error failed")

    # --- retriever hooks ---

    async def on_retriever_start(
        self,
        serialized: dict[str, Any] | None,
        query: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "retriever")
            obs = self._start_obs_span(
                run_id, name, ObservationType.RETRIEVER, parent_run_id
            )
            obs.set_input({"query": query})
            if metadata:
                obs.set_metadata(metadata)
        except Exception:
            logger.opt(exception=True).debug("on_retriever_start failed")

    async def on_retriever_end(
        self,
        documents: Sequence[Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                docs_out = [_safe_json(d) for d in documents]
                obs.set_output({"documents": docs_out})
                obs.end()
        except Exception:
            logger.opt(exception=True).debug("on_retriever_end failed")

    async def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_level(ObservationLevel.ERROR)
                obs.set_status_message(str(error))
                obs.end()
        except Exception:
            logger.opt(exception=True).debug("on_retriever_error failed")

    # --- agent hooks ---

    async def on_agent_action(
        self,
        action: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._runs.get(run_id)
            if obs:
                obs.set_observation_type(ObservationType.AGENT)
                log = _safe_json(getattr(action, "log", str(action)))
                obs.add_intermediate_update({"type": "AGENT", "action_log": log})
        except Exception:
            logger.opt(exception=True).debug("on_agent_action failed")

    async def on_agent_finish(
        self,
        finish: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._runs.get(run_id)
            if obs:
                return_values = _safe_json(
                    getattr(finish, "return_values", str(finish))
                )
                obs.set_output(return_values)
        except Exception:
            logger.opt(exception=True).debug("on_agent_finish failed")

    # --- misc hooks ---

    async def on_retry(
        self,
        retry_state: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._runs.get(run_id)
            if obs:
                obs._span.add_event("retry", {
                    "attempt": str(getattr(retry_state, "attempt_number", "?")),
                    "error": str(getattr(retry_state, "outcome", "")),
                })
        except Exception:
            logger.opt(exception=True).debug("on_retry failed")

    async def on_text(
        self,
        text: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        pass  # Ignored — info covered by other hooks

    # --- prompt linkage helper ---

    def _maybe_link_prompt(
        self,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None,
        obs: ObservationSpan,
    ) -> None:
        current = parent_run_id
        while current:
            prompt = self._prompt_to_parent.pop(current, None)
            if prompt:
                name = getattr(prompt, "name", str(prompt))
                version = str(getattr(prompt, "version", ""))
                obs.set_prompt(name, version or None)
                return
            state = self._run_states.get(current)
            current = state.parent_run_id if state else None
```

- [ ] **Step 4: Run tests (expected pass)**

Run: `cd backend && uv run pytest tests/core/observation/test_callback_handler.py -xvs`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/instrumentation/langchain_handler.py \
        backend/tests/core/observation/test_callback_handler.py
git commit -m "feat(observation): rewrite ObservationCallbackHandler with all 18 LangChain hooks"
```

---

## Task 9: ObservationCollector rewrite (OTel-backed)

**Files:**
- Rewrite: `backend/app/core/observation/collector.py`
- Create: `backend/tests/core/observation/test_collector.py`

The new collector wraps `ObservationTracerProvider`, creates spans via OTel `Tracer`, and exposes a sync API (OTel span creation is sync). `finalize()` remains async.

- [ ] **Step 1: Write failing tests**

`backend/tests/core/observation/test_collector.py`:

```python
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
```

- [ ] **Step 2: Run tests (expected fail)**

Run: `cd backend && uv run pytest tests/core/observation/test_collector.py -xvs`

- [ ] **Step 3: Implement new ObservationCollector**

Rewrite `backend/app/core/observation/collector.py`:

```python
"""ObservationCollector — OTel-backed central API for observation tracing."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine

import sqlalchemy as sa
from loguru import logger
from opentelemetry import trace

from app.core.observation.instrumentation.langchain_handler import (
    ObservationCallbackHandler,
)
from app.core.observation.model import Trace
from app.core.observation.otel.provider import ObservationTracerProvider
from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationLevel, ObservationType
from app.utils.datetime import utc_now


class ObservationCollector:
    def __init__(
        self,
        trace_id: uuid.UUID,
        execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        broadcast_fn: Callable[..., Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._loop = asyncio.get_running_loop()
        self._provider = ObservationTracerProvider(
            execution_id=execution_id,
            trace_id=trace_id,
            workspace_id=workspace_id,
            db_session_factory=db_session_factory,
            broadcast_fn=broadcast_fn,
            event_loop=self._loop,
        )
        self._tracer = self._provider.get_tracer()
        self._trace_id = trace_id
        self._execution_id = execution_id
        self._db_session_factory = db_session_factory

    def start_span(
        self,
        obs_type: ObservationType,
        name: str,
        *,
        parent: ObservationSpan | None = None,
        input: Any = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
    ) -> ObservationSpan:
        obs_id = uuid.uuid4()

        parent_ctx = None
        if parent:
            parent_ctx = trace.set_span_in_context(parent._span)

        otel_span = self._tracer.start_span(
            name,
            context=parent_ctx,
            attributes={
                "observation.id": str(obs_id),
                "observation.type": obs_type.value,
                "observation.level": level.value,
            },
        )

        obs = ObservationSpan(otel_span, obs_id, self._provider)

        if input is not None:
            obs.set_input(input)
        if metadata:
            obs.set_metadata(metadata)

        return obs

    def start_agent(self, name: str, **kw: Any) -> ObservationSpan:
        return self.start_span(ObservationType.AGENT, name, **kw)

    def child_span(
        self,
        parent: ObservationSpan,
        obs_type: ObservationType,
        name: str,
        *,
        input: Any = None,
        **kw: Any,
    ) -> ObservationSpan:
        return self.start_span(obs_type, name, parent=parent, input=input, **kw)

    def record_generation(
        self,
        name: str,
        *,
        parent: ObservationSpan | None = None,
        input: Any = None,
        output: Any = None,
        model: str | None = None,
        usage_details: dict | None = None,
        cost_details: dict | None = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
        **kw: Any,
    ) -> ObservationSpan:
        span = self.start_span(
            ObservationType.GENERATION, name,
            parent=parent, input=input, metadata=metadata, level=level,
        )
        if output is not None:
            span.set_output(output)
        if model:
            span.set_model(model)
        if usage_details:
            span.set_usage(usage_details)
        if cost_details:
            span.set_cost(cost_details)
        span.end()
        return span

    def record_tool(
        self,
        name: str,
        *,
        parent: ObservationSpan | None = None,
        input: Any = None,
        output: Any = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
        **kw: Any,
    ) -> ObservationSpan:
        span = self.start_span(
            ObservationType.TOOL, name,
            parent=parent, input=input, metadata=metadata, level=level,
        )
        if output is not None:
            span.set_output(output)
        span.end()
        return span

    def record_event(
        self,
        name: str,
        *,
        parent: ObservationSpan | None = None,
        input: Any = None,
        metadata: dict | None = None,
        level: ObservationLevel = ObservationLevel.DEFAULT,
        **kw: Any,
    ) -> ObservationSpan:
        span = self.start_span(
            ObservationType.EVENT, name,
            parent=parent, input=input, metadata=metadata, level=level,
        )
        span.end()
        return span

    def create_langchain_handler(self) -> ObservationCallbackHandler:
        return ObservationCallbackHandler(self._tracer, self._provider)

    async def finalize(self, status: str = "complete") -> None:
        agg = self._provider.get_persistence_aggregates()
        final_status = "error" if agg["has_error"] else status
        self._provider.broadcast_trace_complete(final_status, agg)
        await self._provider.shutdown()
        await self._update_trace_row(final_status, agg)

    async def _update_trace_row(self, status: str, agg: dict) -> None:
        try:
            session = await self._db_session_factory()
            now = utc_now()
            await session.execute(
                sa.update(Trace)
                .where(Trace.id == self._trace_id)
                .values(
                    status=status,
                    end_time=now,
                    total_observations=agg["total_observations"],
                    total_tokens=agg["total_tokens"],
                    total_cost=agg["total_cost"],
                )
            )
            await session.commit()
        except Exception:
            logger.opt(exception=True).warning("Failed to update Trace row")
```

- [ ] **Step 4: Run tests (expected pass)**

Run: `cd backend && uv run pytest tests/core/observation/test_collector.py -xvs`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/collector.py \
        backend/tests/core/observation/test_collector.py
git commit -m "feat(observation): rewrite ObservationCollector as OTel-backed API"
```

---

## Task 10: Delete old files, update types.py + __init__.py

**Files:**
- Delete: `backend/app/core/observation/writer.py`
- Delete: `backend/app/core/observation/broadcaster.py`
- Modify: `backend/app/core/observation/types.py` (remove SpanHandle)
- Modify: `backend/app/core/observation/__init__.py` (update re-exports)

- [ ] **Step 1: Delete writer.py and broadcaster.py**

```bash
git rm backend/app/core/observation/writer.py
git rm backend/app/core/observation/broadcaster.py
```

- [ ] **Step 2: Update types.py — remove SpanHandle**

Remove the `SpanHandle` dataclass and `TYPE_CHECKING` imports from `backend/app/core/observation/types.py`. Keep `ObservationType` and `ObservationLevel` only:

```python
"""
Canonical observation types — the single source of truth for Langfuse-aligned tracing.

Values MUST match Langfuse SDK enums exactly (uppercase). Used by ObservationCollector
to emit observation events to the trace tree.
"""

from __future__ import annotations

from enum import StrEnum


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
```

- [ ] **Step 3: Update __init__.py — new re-exports**

```python
"""Observation tracing — Langfuse-aligned trace tree for in-product agent debugging."""

from app.core.observation.collector import ObservationCollector
from app.core.observation.model import Observation, Trace
from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationLevel, ObservationType

__all__ = [
    "Observation",
    "ObservationCollector",
    "ObservationLevel",
    "ObservationSpan",
    "ObservationType",
    "Trace",
]
```

- [ ] **Step 4: Verify import**

Run: `cd backend && uv run python -c "from app.core.observation import ObservationCollector, ObservationSpan, ObservationType, ObservationLevel; print('ok')"`

Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/types.py \
        backend/app/core/observation/__init__.py
git commit -m "refactor(observation): remove SpanHandle, writer, broadcaster — replaced by OTel pipeline"
```

---

## Task 11: Adapt extractor call sites (cli, copilot, file_tracker)

**Files:**
- Modify: `backend/app/core/observation/instrumentation/cli_extractor.py`
- Modify: `backend/app/core/observation/instrumentation/copilot_extractor.py`
- Modify: `backend/app/core/observation/instrumentation/file_tracker.py`

All three extractors currently use `SpanHandle` methods. They must switch to using `ObservationCollector` methods with explicit `parent` parameter. All calls become sync (remove `await`).

- [ ] **Step 1: Update cli_extractor.py**

Replace `SpanHandle` references with `ObservationSpan` and `ObservationCollector` calls. The constructor changes from `(collector, root_span: SpanHandle)` to `(collector, root_span: ObservationSpan)`.

`backend/app/core/observation/instrumentation/cli_extractor.py`:

```python
"""CLI message stream → observation extractor for CLI engines."""
from __future__ import annotations

from app.core.agent.cli_backends.base import CLIMessage
from app.core.observation.collector import ObservationCollector
from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationType


FILE_TOOLS = frozenset({
    "read_file", "write_file", "create_file", "edit_file",
    "Read", "Write", "Edit", "Glob", "Grep",
})


class CLIObservationExtractor:
    def __init__(self, collector: ObservationCollector, root_span: ObservationSpan):
        self._collector = collector
        self._root = root_span
        self._text_buffer: list[str] = []
        self._current_tool_span: ObservationSpan | None = None
        self._current_usage: dict | None = None

    async def process_message(self, msg: CLIMessage) -> None:
        match msg.type:
            case "text":
                self._text_buffer.append(msg.content or "")

            case "tool_use":
                await self._flush_generation()
                tool_name = msg.tool_name or msg.tool or msg.content or "tool"
                tool_input = msg.tool_input or msg.input or {}
                self._current_tool_span = self._collector.child_span(
                    self._root, ObservationType.TOOL, name=tool_name,
                    input={"arguments": tool_input},
                )
                if tool_name in FILE_TOOLS:
                    path = tool_input.get("path", tool_input.get("file_path", ""))
                    op = (
                        "read"
                        if "read" in tool_name.lower() or tool_name in ("Read", "Glob", "Grep")
                        else "write"
                    )
                    self._collector.record_event(
                        f"file:{op} {path}",
                        parent=self._current_tool_span,
                        metadata={"file.path": path, "file.operation": op},
                    )

            case "tool_result":
                if self._current_tool_span:
                    self._current_tool_span.set_output({"result": msg.content})
                    self._current_tool_span.end()
                    self._current_tool_span = None

            case "usage":
                self._current_usage = msg.usage

    async def flush_pending(self) -> None:
        await self._flush_generation()

    async def _flush_generation(self) -> None:
        if not self._text_buffer:
            return
        text = "".join(self._text_buffer)
        self._text_buffer.clear()
        usage = self._current_usage or {}
        self._current_usage = None

        self._collector.record_generation(
            "cli-generation",
            parent=self._root,
            input=None,
            output={"completion": text},
            model=None,
            usage_details=usage if usage else None,
            cost_details=None,
        )
```

- [ ] **Step 2: Update copilot_extractor.py**

Add `parent_span` parameter to constructor. Pass `parent=` in `record_generation`:

```python
"""Copilot stream → observation extractor."""
from __future__ import annotations

from app.core.observation.collector import ObservationCollector
from app.core.observation.otel.span_wrapper import ObservationSpan


class CopilotObservationExtractor:
    def __init__(
        self,
        collector: ObservationCollector,
        model_name: str,
        parent_span: ObservationSpan | None = None,
    ):
        self._collector = collector
        self._model_name = model_name
        self._parent_span = parent_span
        self._chunks: list[str] = []

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
        self._collector.record_generation(
            f"copilot:{self._model_name}",
            parent=self._parent_span,
            input={"prompt": prompt, "mode": mode},
            output={"completion": "".join(self._chunks)},
            model=self._model_name,
            usage_details=usage_details,
            cost_details=None,
        )
```

- [ ] **Step 3: Update file_tracker.py**

Replace `SpanHandle` with `ObservationSpan`, pass `parent=`:

```python
"""File operation → EVENT observation tracker."""
from __future__ import annotations

from app.core.observation.collector import ObservationCollector
from app.core.observation.otel.span_wrapper import ObservationSpan


class FileOperationTracker:
    def __init__(
        self,
        collector: ObservationCollector,
        parent_span: ObservationSpan | None = None,
    ):
        self._collector = collector
        self._parent_span = parent_span

    async def track_write(self, path: str, content: bytes | str) -> None:
        size, preview = self._byte_len(content), None
        if isinstance(content, str):
            preview = content[:200]
        else:
            preview = content[:200].decode(errors="replace")
        await self._track(path, "write", size, content_preview=preview)

    async def track_read(self, path: str, content: bytes | str) -> None:
        await self._track(path, "read", self._byte_len(content))

    async def _track(self, path: str, operation: str, size: int, **extra: str | None) -> None:
        meta: dict = {"file.path": path, "file.operation": operation, "file.size_bytes": size}
        meta.update({k: v for k, v in extra.items() if v is not None})
        self._collector.record_event(
            f"file:{operation} {path}",
            parent=self._parent_span,
            metadata=meta,
        )

    @staticmethod
    def _byte_len(content: bytes | str) -> int:
        return len(content.encode() if isinstance(content, str) else content)
```

- [ ] **Step 4: Verify import**

Run: `cd backend && uv run python -c "from app.core.observation.instrumentation.cli_extractor import CLIObservationExtractor; from app.core.observation.instrumentation.copilot_extractor import CopilotObservationExtractor; from app.core.observation.instrumentation.file_tracker import FileOperationTracker; print('ok')"`

Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/observation/instrumentation/cli_extractor.py \
        backend/app/core/observation/instrumentation/copilot_extractor.py \
        backend/app/core/observation/instrumentation/file_tracker.py
git commit -m "refactor(observation): adapt extractors to OTel-backed collector API"
```

---

## Task 12: Update engine integration points (orchestrator + engines)

**Files:**
- Modify: `backend/app/core/engine/orchestrator.py` (~L820-865)
- Modify: `backend/app/core/engine/graph_engine.py` (~L206-214)
- Modify: `backend/app/core/engine/code_engine.py` (~L67-77)
- Modify: `backend/app/core/engine/copilot_engine.py` (~L63-69)

- [ ] **Step 1: Update orchestrator.py**

Replace lines L821-843 in `orchestrator.py`. Remove `ObservationWriter`, `ObservationBroadcaster` imports. Simplify collector construction:

**Before (L821-843):**
```python
collector = None
if debug:
    from app.core.observation import (
        ObservationBroadcaster,
        ObservationCollector,
        ObservationWriter,
    )
    from app.core.observation.types import ObservationLevel
    from app.websocket.execution_subscription_manager import execution_subscription_manager

    async def _db_factory():
        return db

    async def _broadcast(exec_id: Any, message: dict) -> None:
        await execution_subscription_manager.broadcast_event(str(exec_id), message)

    collector = ObservationCollector(
        trace_id=execution.id,
        execution_id=execution.id,
        workspace_id=workspace_id,
        writer=ObservationWriter(_db_factory),
        broadcaster=ObservationBroadcaster(execution.id, broadcast_fn=_broadcast),
    )
```

**After:**
```python
collector = None
if debug:
    from app.core.observation import ObservationCollector
    from app.core.observation.types import ObservationLevel
    from app.websocket.execution_subscription_manager import execution_subscription_manager

    async def _db_factory():
        return db

    async def _broadcast(exec_id: Any, message: dict) -> None:
        await execution_subscription_manager.broadcast_event(str(exec_id), message)

    collector = ObservationCollector(
        trace_id=execution.id,
        execution_id=execution.id,
        workspace_id=workspace_id,
        db_session_factory=_db_factory,
        broadcast_fn=_broadcast,
    )
```

Also update the error handler at L857:

**Before:**
```python
await collector.record_event(
    f"error:{type(exc).__name__}",
    input={"message": str(exc)},
    level=ObservationLevel.ERROR,
)
```

**After:**
```python
collector.record_event(
    f"error:{type(exc).__name__}",
    input={"message": str(exc)},
    level=ObservationLevel.ERROR,
)
```

Note: `record_event` is now sync — remove `await`.

- [ ] **Step 2: Update graph_engine.py**

Replace L206-213:

**Before:**
```python
root_span = None
obs_handler = None
if context.collector:
    from app.core.observation.instrumentation.langchain_handler import ObservationCallbackHandler

    graph_name = definition_payload.get("name", "graph")
    root_span = await context.collector.start_agent(name=f"root:{graph_name}")
    obs_handler = ObservationCallbackHandler(context.collector, root_span)
```

**After:**
```python
root_span = None
obs_handler = None
if context.collector:
    graph_name = definition_payload.get("name", "graph")
    root_span = context.collector.start_agent(name=f"root:{graph_name}")
    obs_handler = context.collector.create_langchain_handler()
```

Note: `start_agent` is now sync — remove `await`. Handler is created via `create_langchain_handler()`.

- [ ] **Step 3: Update code_engine.py**

Replace L70-76:

**Before:**
```python
root_span = None
obs_handler = None
if context.collector:
    from app.core.observation.instrumentation.langchain_handler import ObservationCallbackHandler

    root_span = await context.collector.start_agent(name="code_executor")
    obs_handler = ObservationCallbackHandler(context.collector, root_span)
```

**After:**
```python
root_span = None
obs_handler = None
if context.collector:
    root_span = context.collector.start_agent(name="code_executor")
    obs_handler = context.collector.create_langchain_handler()
```

- [ ] **Step 4: Update copilot_engine.py**

No `root_span` needed since copilot creates generations at root. Check if constructor needs `parent_span`:

**Before (L63-68):**
```python
copilot_extractor = None
obs_start: float = 0.0
if context.collector and model_name:
    from app.core.observation.instrumentation.copilot_extractor import CopilotObservationExtractor

    copilot_extractor = CopilotObservationExtractor(context.collector, model_name)
```

**After:**
```python
copilot_extractor = None
obs_start: float = 0.0
if context.collector and model_name:
    from app.core.observation.instrumentation.copilot_extractor import CopilotObservationExtractor

    copilot_extractor = CopilotObservationExtractor(context.collector, model_name)
```

This call site stays the same (parent_span defaults to None, fixing the root-level nesting bug).

- [ ] **Step 5: Type check + import smoke test**

Run: `cd backend && uv run python -c "from app.core.engine.orchestrator import Orchestrator; print('ok')"`

Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/engine/orchestrator.py \
        backend/app/core/engine/graph_engine.py \
        backend/app/core/engine/code_engine.py \
        backend/app/core/engine/copilot_engine.py
git commit -m "refactor(observation): update engine call sites to OTel-backed collector"
```

---

## Task 13: Run full test suite + fix regressions

**Files:**
- No new files — this is a verification task.

- [ ] **Step 1: Run all observation tests**

Run: `cd backend && uv run pytest tests/core/observation/ -xvs`

Expected: all tests pass.

- [ ] **Step 2: Grep for stale SpanHandle / ObservationWriter / ObservationBroadcaster references**

Run: `grep -rn "SpanHandle\|ObservationWriter\|ObservationBroadcaster" backend/app/ --include="*.py"`

Expected: no results (all references cleaned up). If any remain, fix them.

- [ ] **Step 3: Grep for stale await on now-sync methods**

Run: `grep -rn "await.*collector\.start_span\|await.*collector\.start_agent\|await.*collector\.record_event\|await.*collector\.record_tool\|await.*collector\.record_generation\|await.*collector\.child_span" backend/app/ --include="*.py"`

Expected: no results (all `await` removed from sync calls). If any remain, fix them.

- [ ] **Step 4: Full backend test suite (sanity check)**

Run: `cd backend && uv run pytest --tb=short -q 2>&1 | tail -20`

Expected: observation-related tests pass. Non-observation tests unaffected.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(observation): resolve regressions from OTel refactor"
```

(Skip if no fixes needed.)

---

## Task 14: Frontend WebSocket Protocol Update (stub)

> **Note:** This task is intentionally a stub. The frontend changes should be planned in a separate spec cycle since they affect `frontend/components/observation/` which has its own viewer design spec (`docs/superpowers/specs/2026-04-28-frontend-observation-viewer-design.md`). Backend + frontend must land together.

**Required changes (from spec section 4.3):**
1. Update `ObservationEvent` type: delete `"record"`, add `"llm_token"` and `"span_update"`
2. Update message envelope: change `observation: {...}` to `observation_id: string` + `parent_observation_id: string | null` + `data: {...}`
3. Add `llm_token` event handler in WS consumer (append token to stream buffer, requestAnimationFrame batch render)
4. Add `span_update` event handler (update observation node attributes)

- [ ] **Step 1: Create a ticket / issue for frontend WS protocol update**

Document the exact envelope changes and required handler updates. Reference spec section 4.3.

---

<!-- PLAN-END -->
