# Observation CallbackHandler Refactor — Design Spec

**Date:** 2026-04-29
**Status:** Draft
**Scope:** `backend/app/core/observation/` full rewrite

## Context

The current `ObservationCallbackHandler` has critical gaps when compared to the Langfuse-python reference implementation. Most notably, `on_chat_model_start` is not implemented — meaning all modern chat-based LangChain chains produce zero GENERATION spans. Additionally, missing error hooks (`on_chain_error`), lack of OTel integration, no streaming token support, and no try/except protection make the current implementation insufficient for production observability.

This refactor targets full Langfuse capability parity with an OTel-native architecture.

## Dependencies

New pip dependencies required:

```
opentelemetry-api>=1.25.0
opentelemetry-sdk>=1.25.0
```

Add to `pyproject.toml` under `[project.dependencies]` (or equivalent).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Target | Full Langfuse parity | All 18 callback hooks, multi-provider token parsing, prompt linkage, streaming, error classification |
| OTel | Integrate OpenTelemetry SDK | Standardized trace propagation; unlocks Jaeger/Langfuse SaaS export in future |
| LangGraph interrupt/resume | Not needed | Current graph_engine runs are one-shot |
| Storage layer | Full OTel unified pipeline | SpanProcessor pipeline is sole data outlet; persist and broadcast are both consumers |
| Streaming mechanism | LiveSpanProcessor extension | Custom `on_event` interface; avoids sidecar hack and dual-pipeline regression |
| Migration path | In-place rewrite | No parallel v2 module; rewrite directly in `observation/` |
| Architecture | Langfuse replica | RunState tree + OTel context attach/detach + SpanProcessor pipeline |

## Architecture Overview

```
LangChain Runtime
       | callbacks
       v
+---------------------------------------------+
|  ObservationCallbackHandler                  |
|  +-- _run_states: {run_id -> RunState}       |  <- explicit run tree
|  +-- _root_run_states: {root -> children}    |
|  +-- _context_tokens: {run_id -> Token}      |  <- OTel context attach/detach
|  +-- all 18 on_* hooks                       |
|  +-- try/except on every method body         |
+------------------+---------------------------+
                   | OTel span API
                   v
+---------------------------------------------+
|  OTel TracerProvider (per-execution)         |
|  +-- SpanProcessor pipeline (composite)     |
|       +-- PersistenceProcessor -> PG batch   |
|       +-- BroadcastProcessor  -> WS instant  |
|       +-- (future: JaegerExporter, etc.)     |
+---------------------------------------------+
```

## Module Structure

```
observation/
+-- __init__.py                          # public re-exports
+-- types.py                             # ObservationType, ObservationLevel (retained)
+-- model.py                             # Trace, Observation ORM (retained, no schema changes needed)
|
+-- otel/                                # NEW: OTel core layer
|   +-- __init__.py
|   +-- provider.py                      # ObservationTracerProvider lifecycle
|   +-- span_wrapper.py                  # ObservationSpan: typed OTel Span wrapper
|   +-- processor_base.py               # LiveSpanProcessor(SpanProcessor) + on_event
|   +-- persistence_processor.py         # SpanProcessor -> batched PG write
|   +-- broadcast_processor.py           # LiveSpanProcessor -> instant WS push
|
+-- collector.py                         # ObservationCollector (rewritten as OTel-backed)
|
+-- instrumentation/
    +-- langchain_handler.py             # ObservationCallbackHandler (full rewrite)
    +-- langchain_utils.py               # NEW: model name extraction + token parsing
    +-- cli_extractor.py                 # retained (adapt to new collector API)
    +-- copilot_extractor.py             # retained (adapt to new collector API)
    +-- file_tracker.py                  # retained (adapt to new collector API)
```

### Deletions

| File | Replacement |
|---|---|
| `observation/writer.py` | `PersistenceProcessor` |
| `observation/broadcaster.py` | `BroadcastProcessor` |
| `SpanHandle` dataclass in `types.py` | `ObservationSpan` |

## Section 1: OTel Layer

### 1.1 ObservationTracerProvider (otel/provider.py)

Per-execution TracerProvider. NOT a global singleton — each execution gets its own provider so processors capture only that execution's spans.

**OTel context API note**: `trace.set_span_in_context()` and `context.attach()` operate on `contextvars`, not on the global provider. They work correctly with per-execution providers — the global `TracerProvider` is never set or used.

```python
class ObservationTracerProvider:
    def __init__(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        workspace_id: uuid.UUID,
        db_session_factory: Callable,
        broadcast_fn: Callable | None,
        event_loop: asyncio.AbstractEventLoop,
    ):
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
        # LiveSpanProcessor registry: only processors implementing on_event
        self._live_processors: list[LiveSpanProcessor] = [self._broadcast]

    def get_tracer(self) -> Tracer: ...

    def dispatch_live_event(self, span: ObservationSpan, event_name: str, attributes: dict):
        """Route live events to all registered LiveSpanProcessor instances."""
        for p in self._live_processors:
            p.on_event(span, event_name, attributes)

    async def shutdown(self): ...
```

### 1.2 ObservationSpan (otel/span_wrapper.py)

Thin typed wrapper over an OTel Span. Provides attribute setters that map to our observation schema, plus live-event methods that trigger LiveSpanProcessor.

```python
class ObservationSpan:
    def __init__(self, otel_span: Span, observation_id: uuid.UUID,
                 provider: ObservationTracerProvider):
        self._span = otel_span
        self.observation_id = observation_id
        self._provider = provider

    # typed attribute setters
    def set_input(self, value: Any): ...
    def set_output(self, value: Any): ...
    def set_metadata(self, value: dict): ...
    def set_model(self, name: str): ...
    def set_model_parameters(self, params: dict): ...
    def set_usage(self, usage: dict): ...
    def set_cost(self, cost: dict): ...
    def set_level(self, level: ObservationLevel): ...
    def set_status_message(self, msg: str): ...
    def set_observation_type(self, t: ObservationType): ...
    def set_prompt(self, name: str, version: str | None): ...
    def set_tool_calls(self, calls: list): ...
    def set_completion_start_time(self, ts: datetime): ...

    # streaming events (trigger LiveSpanProcessor.on_event)
    def add_llm_token(self, token: str, index: int):
        attrs = {"token": token, "index": index}
        self._span.add_event("stream.llm_token", attrs)
        self._provider.dispatch_live_event(self, "llm_token", attrs)

    def add_intermediate_update(self, payload: dict):
        # OTel span events require flat primitive attributes; serialize nested
        # payloads to a JSON string for the persisted form
        self._span.add_event("stream.intermediate_update", {
            "payload_json": json.dumps(payload, default=str),
        })
        self._provider.dispatch_live_event(self, "span_update", payload)

    def record_error(self, exc: Exception, level: ObservationLevel): ...
    def end(self): ...
```

### 1.3 LiveSpanProcessor (otel/processor_base.py)

Extension of OTel SpanProcessor that adds an `on_event` method for live streaming events.

```python
class LiveSpanProcessor(SpanProcessor):
    def on_event(self, span: ObservationSpan, event_name: str, attributes: dict):
        """Called immediately when a live event is emitted, not batched."""
        ...
```

### 1.4 PersistenceProcessor (otel/persistence_processor.py)

Batched async PG writer driven by OTel span lifecycle. Replaces `ObservationWriter`.

**Sync-to-async bridge**: OTel's `SpanProcessor.on_start`/`on_end` are synchronous. Our DB writes are async. The bridge pattern: processor holds a reference to the running `asyncio` event loop (passed in via constructor from `ObservationTracerProvider`). `on_start`/`on_end` enqueue work to an `asyncio.Queue` via `loop.call_soon_threadsafe(queue.put_nowait, item)`. A long-running `_drain_task` (started in `__init__` via `loop.call_soon_threadsafe(asyncio.ensure_future, self._drain_loop())`) consumes the queue and performs batched DB writes. `shutdown()` sends a sentinel to the queue and awaits `_drain_task` completion, ensuring all pending writes flush before exit.

```python
class PersistenceProcessor(SpanProcessor):
    def __init__(self, execution_id, trace_id, workspace_id, db_factory, event_loop):
        self._loop = event_loop
        self._queue: asyncio.Queue = asyncio.Queue()
        self._insert_buffer: list[Observation] = []
        self._update_buffer: list[tuple[uuid.UUID, dict]] = []
        self._max_batch = 10
        self._max_wait_ms = 300
        self._max_buffer_size = 1000  # prevent unbounded growth on persistent failure
        # Aggregation state for Trace-level totals
        self._total_tokens = 0
        self._total_cost = 0.0
        self._observation_count = 0
        self._has_error = False
        # Start drain task on the event loop
        self._drain_task = asyncio.run_coroutine_threadsafe(self._drain_loop(), self._loop)

    def on_start(self, span: ReadableSpan, parent_context):
        obs = self._build_observation(span, parent_context)
        self._loop.call_soon_threadsafe(self._queue.put_nowait, ("insert", obs))

    def on_end(self, span: ReadableSpan):
        updates = self._extract_updates(span)
        events_to_persist = [e for e in span.events if not e.name.startswith("stream.")]
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait, ("update", span_observation_id, updates)
        )
        # Accumulate token/cost totals from usage attrs
        usage = self._extract_usage(span)
        if usage:
            self._total_tokens += usage.get("total", 0)
        cost = self._extract_cost(span)
        if cost:
            self._total_cost += cost.get("total", 0.0)
        self._observation_count += 1
        if span.attributes.get("observation.level") == "ERROR":
            self._has_error = True
        for ev in events_to_persist:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, ("insert", self._event_to_observation(ev))
            )

    async def _drain_loop(self):
        """Long-running consumer: batches queue items, flushes to DB."""
        ...

    def get_aggregates(self) -> dict:
        """Returns accumulated totals for Trace row finalization."""
        return {
            "total_tokens": self._total_tokens,
            "total_cost": self._total_cost,
            "total_observations": self._observation_count,
            "has_error": self._has_error,
        }

    def shutdown(self): ...
    def force_flush(self, timeout_millis: int = 30000) -> bool: ...
```

Event filtering: events prefixed with `stream.` are skipped by PersistenceProcessor. All other events are persisted as child Observation rows.

Buffer cap: `_max_buffer_size = 1000`. When exceeded, oldest items are dropped with a warning log. Prevents unbounded memory growth on persistent DB failure.

### 1.5 BroadcastProcessor (otel/broadcast_processor.py)

Real-time WebSocket relay via LiveSpanProcessor. Never batches — every event pushes immediately.

**Sync-to-async bridge**: same pattern as PersistenceProcessor. `broadcast_fn` is `async def _broadcast(execution_id, payload) -> None` (orchestrator-supplied). `_emit()` schedules the coroutine on the event loop via `asyncio.run_coroutine_threadsafe(broadcast_fn(...), self._loop)`. We don't await the future — fire and forget. Exceptions logged via callback on the future.

```python
class BroadcastProcessor(LiveSpanProcessor):
    def __init__(self, execution_id, broadcast_fn, event_loop):
        self._execution_id = execution_id
        self._broadcast_fn = broadcast_fn  # async callable
        self._loop = event_loop
        self._seq = 0

    def on_start(self, span, parent_context):
        self._emit("span_open", self._serialize_span_open(span))

    def on_end(self, span):
        self._emit("span_close", self._serialize_span_close(span))

    def on_event(self, span: ObservationSpan, event_name: str, attributes: dict):
        self._emit(event_name, {
            "observation_id": str(span.observation_id),
            "parent_observation_id": self._get_parent_id(span),
            "data": dict(attributes),
        })

    def _emit(self, event: str, payload: dict):
        if not self._broadcast_fn:
            return
        self._seq += 1
        message = {
            "channel": "observation",
            "trace_id": str(self._execution_id),
            "seq": self._seq,
            "event": event,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **payload,
        }
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._broadcast_fn(self._execution_id, message), self._loop
            )
            future.add_done_callback(self._log_if_failed)
        except Exception:
            pass  # WS disconnect / loop closed must not crash the pipeline

    @staticmethod
    def _log_if_failed(future):
        exc = future.exception()
        if exc:
            logger.warning("broadcast failed: %s", exc)
```

### 1.6 Span Attribute Namespace

| Attribute | Purpose |
|---|---|
| `observation.id` | UUID (our PK) |
| `observation.type` | ObservationType string |
| `observation.level` | ObservationLevel string |
| `observation.input` | JSON string |
| `observation.output` | JSON string |
| `observation.metadata` | JSON string |
| `observation.status_message` | error message |
| `llm.model` | model name |
| `llm.parameters` | JSON string |
| `llm.usage.input` / `output` / `total` | int |
| `llm.cost.input` / `output` / `total` | float |
| `llm.completion_start_time` | ISO timestamp |
| `llm.prompt.name` / `llm.prompt.version` | str |
| `tool.calls` | JSON string |
| `tool.definitions` | JSON string |

## Section 2: ObservationCallbackHandler Rewrite

### 2.1 State Management

```python
@dataclass
class RunState:
    parent_run_id: UUID | None
    root_run_id: UUID

@dataclass
class RootRunState:
    run_ids: set[UUID] = field(default_factory=set)

class ObservationCallbackHandler(AsyncCallbackHandler):
    def __init__(self, tracer: Tracer, provider: ObservationTracerProvider):
        self._tracer = tracer
        self._provider = provider
        self._runs: dict[UUID, ObservationSpan] = {}
        self._context_tokens: dict[UUID, Token] = {}
        self._run_states: dict[UUID, RunState] = {}
        self._root_run_states: dict[UUID, RootRunState] = {}
        self._completion_start_memo: set[UUID] = set()
        self._prompt_to_parent: dict[UUID, Any] = {}
```

**State field reference**:
- `_runs`: maps run_id to its open `ObservationSpan` for parent resolution
- `_context_tokens`: maps run_id to OTel context token for detach on span end
- `_run_states` / `_root_run_states`: explicit run tree (section 2.2)
- `_completion_start_memo`: tracks which run_ids have already recorded `completion_start_time`, so `on_llm_new_token` only sets it on the first token. Entries are removed in `on_llm_end`.
- `_prompt_to_parent`: maps `parent_run_id` to a Langfuse prompt object for chain-to-LLM prompt linkage. When a chain starts with `metadata["langfuse_prompt"]`, it is stored here keyed by `run_id`. In `on_chat_model_start`/`on_llm_start`, the handler walks up the ancestor chain via `_run_states` to find a registered prompt, deregisters it once consumed, and passes it to `span.set_prompt(name, version)`. Mirrors Langfuse's `_register_langfuse_prompt` / `_deregister_langfuse_prompt` mechanism.

### 2.2 Run Tree Management

```python
def _track_run(self, run_id: UUID, parent_run_id: UUID | None):
    if run_id in self._run_states:
        return
    if parent_run_id is None:
        root = run_id
        self._root_run_states[root] = RootRunState()
    else:
        root = self._run_states[parent_run_id].root_run_id
    self._run_states[run_id] = RunState(parent_run_id, root)
    self._root_run_states[root].run_ids.add(run_id)
```

### 2.3 OTel Context Attach/Detach

```python
def _attach_span(self, run_id: UUID, obs: ObservationSpan):
    ctx = trace.set_span_in_context(obs._span)
    token = context.attach(ctx)
    self._runs[run_id] = obs
    self._context_tokens[run_id] = token

def _detach_span(self, run_id: UUID) -> ObservationSpan | None:
    token = self._context_tokens.pop(run_id, None)
    if token:
        try:
            context.detach(token)
        except Exception:
            pass  # async context mismatch — safe to swallow
    return self._runs.pop(run_id, None)

def _reset(self, root_run_id: UUID):
    state = self._root_run_states.pop(root_run_id, None)
    if state:
        for rid in state.run_ids:
            self._run_states.pop(rid, None)
```

### 2.4 Complete Callback Hook Table

Every method body wrapped in `try/except Exception: logger.exception(...)`.

| Hook | Behavior |
|---|---|
| `on_chain_start` | `_track_run` -> `_classify_chain()` (section 2.9) -> `_tracer.start_span` -> set input/metadata -> `_attach_span` |
| `on_chain_end` | `_detach_span` -> set output -> `span.end()` -> if root: `_reset` |
| `on_chain_error` | `_detach_span` -> set level(ERROR) + status_message -> `span.end()` -> if root: `_reset` |
| `on_chat_model_start` | `_track_run` -> messages -> `convert_messages_to_dicts` -> model name fallback -> model params -> start_span(GENERATION) -> `_attach_span` |
| `on_llm_start` | Same as above but input is prompts string list (legacy completion-style LLM compat) |
| `on_llm_end` | `_detach_span` -> `_extract_response` -> `normalize_usage` (multi-provider) -> set output/usage/model -> `span.end()` |
| `on_llm_error` | `_detach_span` -> set level/status -> `span.end()` |
| `on_llm_new_token` | First token: set `completion_start_time` -> `span.add_llm_token(token)` (triggers LiveSpanProcessor) |
| `on_tool_start` | `_track_run` -> start_span(TOOL) -> set input -> `_attach_span` |
| `on_tool_end` | `_detach_span` -> set output -> `span.end()` |
| `on_tool_error` | `_detach_span` -> set level/status -> `span.end()` |
| `on_retriever_start` | `_track_run` -> start_span(RETRIEVER) -> set input(query) -> `_attach_span` |
| `on_retriever_end` | `_detach_span` -> set output(documents) -> `span.end()` |
| `on_retriever_error` | `_detach_span` -> set level/status -> `span.end()` |
| `on_agent_action` | No new span -> find current run's span -> set `observation.type=AGENT` (overrides initial CHAIN) + add intermediate output(action log). See section 2.9 below for type-mutation handling. |
| `on_agent_finish` | Same -> set output(return values). The actual span end happens in `on_chain_end` (LangChain reuses run_id). |
| `on_retry` | `span.add_event("retry", {attempt, error, wait_seconds})` |
| `on_text` | Ignored (info already covered by other hooks) |

### 2.5 Message Serialization (langchain_utils.py)

```python
MESSAGE_ROLE_MAP = {
    "HumanMessage": "user",
    "AIMessage": "assistant",
    "SystemMessage": "system",
    "ToolMessage": "tool",
    "FunctionMessage": "function",
    "ChatMessage": None,  # use message.role
}

def convert_message_to_dict(message: BaseMessage) -> dict:
    role = MESSAGE_ROLE_MAP.get(type(message).__name__, "unknown")
    if role is None:
        role = getattr(message, "role", "unknown")
    result = {"role": role, "content": message.content}
    if hasattr(message, "tool_calls") and message.tool_calls:
        result["tool_calls"] = message.tool_calls
    if hasattr(message, "tool_call_id"):
        result["tool_call_id"] = message.tool_call_id
    if message.additional_kwargs:
        result.update(message.additional_kwargs)
    return result
```

### 2.6 Token Usage Multi-Provider Normalization

```python
USAGE_KEY_MAP = [
    ("prompt_tokens", "completion_tokens", "total_tokens"),          # OpenAI
    ("input_tokens", "output_tokens", None),                        # Anthropic
    ("promptTokenCount", "candidatesTokenCount", "totalTokenCount"), # Google Vertex
    ("inputTokens", "outputTokens", "totalTokens"),                 # AWS Bedrock
]

def normalize_usage(raw: dict | None) -> dict[str, int]:
    """Returns {"input": N, "output": N, "total": N} regardless of provider."""
    if not raw:
        return {}
    for input_key, output_key, total_key in USAGE_KEY_MAP:
        if input_key in raw:
            inp = int(raw[input_key])
            out = int(raw.get(output_key, 0))
            total = int(raw[total_key]) if total_key and total_key in raw else inp + out
            return {"input": inp, "output": out, "total": total}
    return {}
```

### 2.7 Model Name Extraction Fallback Chain

```
metadata["ls_model_name"]
  -> serialized["kwargs"]["model_name"]
  -> serialized["kwargs"]["model"]
  -> kwargs["invocation_params"]["model_name"]
  -> kwargs["invocation_params"]["model"]
  -> response.llm_output["model_name"]  (at on_llm_end time)
  -> None
```

### 2.8 Error Handling Principles

1. Every `on_*` method body is wrapped in `try/except Exception` — handler crashes never propagate to user code
2. Root span end/error uses `finally: self._reset(root_run_id)` — guarantees state cleanup
3. All `on_*_error` callbacks uniformly set `ObservationLevel.ERROR`
4. `_reset(root_run_id)` clears `_run_states` and `_root_run_states` entries; `_runs` and `_context_tokens` are popped per-run by `_detach_span()` in each `on_*_end`/`on_*_error` callback (not by `_reset`). The root run's `_detach_span` MUST be called before `_reset`.

### 2.9 CHAIN vs AGENT Classification

Replicates the current handler's `_is_worker_dispatch` heuristic so frontend trace viewer behavior is preserved:

```python
def _classify_chain(name: str, serialized: dict) -> ObservationType:
    """Classify chain start as CHAIN or AGENT.

    Preserves the current `_is_worker_dispatch` logic — frontend trace viewer
    distinguishes sub-agents from regular chains by this classification.
    """
    if name and (
        name.startswith("worker:")
        or "SubAgent" in name
        or "CompiledSubAgent" in name
    ):
        return ObservationType.AGENT
    # Fallback: inspect serialized class path for "agent" substring
    if serialized:
        path = serialized.get("id", [])
        if any("agent" in seg.lower() for seg in path if isinstance(seg, str)):
            return ObservationType.AGENT
    return ObservationType.CHAIN
```

### 2.10 Agent Type Mutation (on_agent_action / on_agent_finish)

When `on_agent_action` fires, the chain span has already been started (at `on_chain_start` time) — and `PersistenceProcessor.on_start` has already run, queuing the INSERT. The mutation strategy:

**Defer DB insertion until `on_end`**: `PersistenceProcessor.on_start` does NOT immediately enqueue an insert. Instead it stashes the span reference. `on_end` builds the final Observation record (from the span's terminal attributes) and enqueues a single INSERT with all fields including the final `observation.type`. This eliminates the need for an UPDATE-on-mutation path and ensures the persisted row reflects the final classification.

**Trade-off**: WebSocket `span_open` events fire at OTel `on_start` time and will carry the initial type (CHAIN). The frontend treats `span_update` events that mutate `type` as authoritative. `on_agent_action` triggers `add_intermediate_update({"type": "AGENT"})` which broadcasts a `span_update` event.

Updated PersistenceProcessor behavior:

```python
def on_start(self, span, parent_context):
    # Stash only — defer INSERT until on_end so all attribute mutations are captured
    pass  # OTel still tracks span lifecycle in its own internal state

def on_end(self, span):
    obs = self._build_observation(span, parent_context=None)  # uses span.parent
    self._loop.call_soon_threadsafe(self._queue.put_nowait, ("insert", obs))
    # ... persist non-stream events as before
```

Implication: an Observation row only appears in the DB after its span ends. For long-running spans, this delays visibility in DB queries. **The WebSocket pipeline (BroadcastProcessor) is NOT affected** — it still emits `span_open` immediately. Frontend gets real-time updates; DB is the system-of-record after-the-fact.

## Section 3: ObservationCollector Rewrite

### 3.1 New Collector

```python
class ObservationCollector:
    def __init__(
        self,
        trace_id: uuid.UUID,
        execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
        db_session_factory: Callable,
        broadcast_fn: Callable | None = None,
    ):
        self._provider = ObservationTracerProvider(
            execution_id, trace_id, workspace_id,
            db_session_factory, broadcast_fn,
        )
        self._tracer = self._provider.get_tracer()
        self._trace_id = trace_id
        self._execution_id = execution_id

    def start_span(self, type: ObservationType, name: str, *,
                   parent: ObservationSpan | None = None,
                   input: Any = None, metadata: dict | None = None,
                   level: ObservationLevel = ObservationLevel.DEFAULT) -> ObservationSpan: ...

    def start_agent(self, name: str, **kw) -> ObservationSpan: ...
    def record_generation(self, *, parent: ObservationSpan, **kw): ...
    def record_tool(self, *, parent: ObservationSpan, **kw): ...
    def record_event(self, *, parent: ObservationSpan, **kw): ...

    def create_langchain_handler(self) -> ObservationCallbackHandler:
        return ObservationCallbackHandler(self._tracer, self._provider)

    async def finalize(self, status: str = "complete"):
        await self._provider.shutdown()
```

### 3.2 Orchestrator Integration

```python
# Before (old)
writer = ObservationWriter(db_factory)
broadcaster = ObservationBroadcaster(execution.id, broadcast_fn)
collector = ObservationCollector(trace_id=..., writer=writer, broadcaster=broadcaster)
root_span = await collector.start_agent(name=f"root:{graph_name}")
handler = ObservationCallbackHandler(collector, root_span)
config["callbacks"] = [handler]

# After (new)
collector = ObservationCollector(
    trace_id=execution.id,
    execution_id=execution.id,
    workspace_id=workspace.id,
    db_session_factory=db_factory,
    broadcast_fn=broadcast_fn,
)
root_span = collector.start_span(ObservationType.AGENT, f"root:{graph_name}")
handler = collector.create_langchain_handler()
config["callbacks"] = [handler]
# finally:
await collector.finalize()
```

### 3.3 Other Instrumentation Adaptation

| Component | Changes |
|---|---|
| CLIObservationExtractor | Constructor receives `ObservationCollector` + `ObservationSpan` (replacing old SpanHandle) |
| CopilotObservationExtractor | Same. `flush()` now passes `parent=parent_span` to fix all generations landing at root |
| FileOperationTracker | Minimal: `record_event()` signature adaptation |

### 3.4 Observation ORM — No Schema Changes

All required fields already exist in `model.py`:
- `completion_start_time` (line 77) — `datetime | None`
- `prompt_name` (line 89) — `str | None`
- `prompt_version` (line 90) — `int | None` (note: integer, not string)

No migration needed. The handler will use `prompt_version` as `int` to match the existing schema.

Trace table: no changes.

### 3.5 Trace Row Lifecycle

The current system creates and updates the `Trace` ORM row directly in the collector/orchestrator. In the new design, `ObservationCollector` remains responsible for Trace-level state:

```python
class ObservationCollector:
    async def _create_trace_row(self):
        """Called during __init__. Creates the Trace row with status='running'."""
        trace = Trace(
            id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            status="running",
            start_time=utc_now(),
        )
        await self._db_session_factory().add(trace)
        ...

    async def finalize(self, status: str = "complete"):
        """
        1. Await provider.shutdown() — flushes PersistenceProcessor drain loop
        2. Read aggregates from PersistenceProcessor.get_aggregates()
        3. UPDATE Trace row: total_tokens, total_cost, total_observations,
           status ('error' if has_error else status), end_time, duration_ms
        4. BroadcastProcessor emits trace_complete with aggregates
        """
        await self._provider.shutdown()
        agg = self._provider.get_persistence_aggregates()
        final_status = "error" if agg["has_error"] else status
        await self._update_trace_row(final_status, agg)
        self._provider.broadcast_trace_complete(final_status, agg)
```

This preserves the current behavior where:
- Trace row is created at execution start
- Aggregates (total_tokens, total_cost) are accumulated during span processing
- `finalize()` writes the final state — including `has_error` detection from ERROR-level spans

## Section 4: WebSocket Protocol

### 4.1 Unified Message Format

```typescript
interface ObservationMessage {
  channel: "observation"
  trace_id: string
  seq: number
  event: ObservationEvent
  observation_id: string
  parent_observation_id: string | null
  timestamp: string
  data: Record<string, any>
}

type ObservationEvent =
  | "span_open"
  | "span_close"
  | "span_update"
  | "llm_token"
  | "trace_complete"
```

### 4.2 Event Data Structures

All examples below are the full message including envelope fields from 4.1.

**span_open**
```json
{
  "channel": "observation",
  "trace_id": "abc-123",
  "seq": 1,
  "event": "span_open",
  "observation_id": "obs-456",
  "parent_observation_id": "obs-root",
  "timestamp": "2026-04-29T10:00:00Z",
  "data": {
    "name": "ChatOpenAI",
    "type": "GENERATION",
    "level": "DEFAULT",
    "input": { "messages": [] },
    "metadata": {},
    "model": "gpt-4o",
    "start_time": "2026-04-29T10:00:00Z"
  }
}
```

**span_close**
```json
{
  "channel": "observation",
  "trace_id": "abc-123",
  "seq": 5,
  "event": "span_close",
  "observation_id": "obs-456",
  "parent_observation_id": "obs-root",
  "timestamp": "2026-04-29T10:00:03Z",
  "data": {
    "output": { "role": "assistant", "content": "..." },
    "level": "DEFAULT",
    "end_time": "2026-04-29T10:00:03Z",
    "usage": { "input": 150, "output": 80, "total": 230 },
    "cost": { "total": 0.0012 },
    "status_message": null
  }
}
```

**llm_token**
```json
{
  "channel": "observation",
  "trace_id": "abc-123",
  "seq": 3,
  "event": "llm_token",
  "observation_id": "obs-456",
  "parent_observation_id": "obs-root",
  "timestamp": "2026-04-29T10:00:01Z",
  "data": {
    "token": "Hello",
    "index": 0
  }
}
```

**span_update**
```json
{
  "channel": "observation",
  "trace_id": "abc-123",
  "seq": 4,
  "event": "span_update",
  "observation_id": "obs-789",
  "parent_observation_id": "obs-root",
  "timestamp": "2026-04-29T10:00:02Z",
  "data": {
    "field": "metadata",
    "value": { "progress": "50%" }
  }
}
```

**trace_complete**
```json
{
  "channel": "observation",
  "trace_id": "abc-123",
  "seq": 10,
  "event": "trace_complete",
  "observation_id": null,
  "parent_observation_id": null,
  "timestamp": "2026-04-29T10:00:08Z",
  "data": {
    "status": "complete",
    "total_observations": 12,
    "total_tokens": 1580,
    "total_cost": 0.0045,
    "duration_ms": 8200
  }
}
```

### 4.3 Protocol Migration

**Frontend coordination required**. The current `broadcaster.py` wraps payloads as `{"observation": {...}}`, while the new `BroadcastProcessor._emit` flattens the data into a `data` field per the envelope in 4.1. The frontend trace viewer (`frontend/components/observation/`, see `docs/superpowers/specs/2026-04-28-frontend-observation-viewer-design.md`) currently parses the old shape and must be updated as part of this refactor.

| Old event | New event | Notes |
|---|---|---|
| `span_open` (payload: `{observation: {...}}`) | `span_open` (payload: `{observation_id, data: {...}}`) | Envelope changed; data structure enriched |
| `span_close` (same envelope shift) | `span_close` | Envelope changed; data structure enriched |
| `record` | Removed | Split into `span_update` + `llm_token` |
| `trace_complete` | `trace_complete` | Envelope shift; aggregates moved into `data` |
| — | `llm_token` | New: streaming core |
| — | `span_update` | New: intermediate state including type mutations from `on_agent_action` |

Backend and frontend must land together; no compatibility shim is provided.

### 4.4 Frontend Consumption Model

Frontend maintains `Map<observation_id, ObservationNode>`:

```
span_open      -> Map.set(id, new node) -> render new card/row
llm_token      -> Map.get(id).streamBuffer += token -> real-time text update
span_close     -> Map.get(id).markComplete(data) -> update usage/cost/status icon
trace_complete -> stop spinner, show summary
```

Seq gap detection: if received seq is not contiguous with previous, frontend knows messages were lost and can issue a REST request to backfill.

### 4.5 Backpressure

1. **BroadcastProcessor side**: if `broadcast_fn` throws (WS disconnect), silently discard — never crash the OTel pipeline
2. **Frontend side**: `llm_token` batched via `requestAnimationFrame` — one DOM update per 16ms frame, processing all buffered tokens

## Section 5: Testing Strategy

### 5.1 Test Layers

| Layer | Target | Tool |
|---|---|---|
| Unit | RunState tree, message serialization, usage normalization, model name fallback | pytest |
| Integration | Handler + OTel Provider + Processor full chain | pytest + InMemorySpanExporter |
| End-to-end | Real LangChain chain -> DB write -> WS push | pytest + real PG + mock broadcast |

### 5.2 Key Unit Tests

**test_run_state_tracking**
- Single root, multi-level nesting: root -> chain -> llm RunState correctness
- Multiple concurrent roots: two independent trees don't pollute each other
- `_reset(root)` cleans entire subtree, doesn't affect other roots

**test_message_serialization**
- HumanMessage -> role="user"
- AIMessage with tool_calls -> role="assistant" + tool_calls field
- ToolMessage -> role="tool" + tool_call_id
- ChatMessage(role="custom") -> role="custom"
- additional_kwargs correctly merged

**test_usage_normalization**
- OpenAI format `{prompt_tokens, completion_tokens, total_tokens}` -> `{input, output, total}`
- Anthropic `{input_tokens, output_tokens}` -> `{input, output, total=sum}`
- Vertex `{promptTokenCount, candidatesTokenCount, totalTokenCount}` -> normalized
- Bedrock `{inputTokens, outputTokens}` -> normalized
- Empty/None input -> returns empty dict without crashing

**test_model_name_fallback**
- `metadata.ls_model_name` takes priority
- Falls back through: serialized.kwargs.model_name -> invocation_params.model -> response.llm_output.model_name
- All missing returns None without crashing

### 5.3 Integration Tests (OTel Full Chain)

Use OTel `InMemorySpanExporter` replacing PersistenceProcessor to verify span attributes:

```python
async def test_chat_model_creates_generation_span():
    exporter = InMemorySpanExporter()
    provider = ObservationTracerProvider(...)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    handler = ObservationCallbackHandler(provider.get_tracer(), provider)

    run_id = uuid.uuid4()
    await handler.on_chat_model_start(
        serialized={"id": ["langchain", "chat_models", "ChatOpenAI"]},
        messages=[[HumanMessage(content="hi")]],
        run_id=run_id, parent_run_id=None,
        metadata={"ls_model_name": "gpt-4o"},
    )
    await handler.on_llm_end(
        response=LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="hello"))]],
            llm_output={"token_usage": {"prompt_tokens": 5, "completion_tokens": 3}},
        ),
        run_id=run_id,
    )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["observation.type"] == "GENERATION"
    assert spans[0].attributes["llm.model"] == "gpt-4o"
    assert spans[0].attributes["llm.usage.input"] == 5
    assert spans[0].attributes["llm.usage.output"] == 3
```

### 5.4 Critical Edge Cases

| Scenario | Expected Behavior |
|---|---|
| `on_chat_model_start` called (not `on_llm_start`) | Must create GENERATION span (fixes current biggest bug) |
| Chain throws exception (`on_chain_error`) | Span ends with ERROR level, state correctly cleaned up, no leak |
| Handler internal exception (e.g., serialization failure) | Not propagated to user code, logger records |
| Nested chain -> tool -> chain | parent_observation_id chain correct, OTel context correct attach/detach |
| Concurrent execution of multiple chains | Different run_id trees isolated |
| Streaming: first token | Sets completion_start_time, subsequent tokens don't re-set |
| Streaming: 100 tokens | 100 broadcast events, 0 DB writes |
| broadcast_fn throws exception | Silently discarded, OTel pipeline continues |
| DB write failure | PersistenceProcessor buffer capped at 1000, no unbounded growth |
| collector.finalize() with unclosed spans | Force end + WARNING level + Trace status correct |
| Cross async-task boundary | OTel context propagates via contextvars |

### 5.5 Performance Sanity Check

Not a formal benchmark suite, but run once after implementation:

- 1 generation span + 100 streaming tokens: < 50ms end-to-end
- 100 nested spans: DB write batches <= 11 (10 batch + 1 flush)
- 1000 streaming tokens: memory stable (buffer doesn't accumulate)

### 5.6 Not Tested

- OTel SDK internals (trust upstream)
- PG driver internals
- Mock LangChain chains for end-to-end (InMemorySpanExporter covers logic)
- Load testing (YAGNI, address if issues arise)
