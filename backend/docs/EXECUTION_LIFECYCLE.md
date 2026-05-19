# Execution Lifecycle Architecture

## Overview

The execution lifecycle is the core data flow of JoySafeter: from user trigger to agent execution to observable result. This document describes the architecture after the OTel standardization and dependency inversion refactoring.

## Module Hierarchy

```
app/api/v1/          → HTTP endpoints (Layer 1)
app/services/        → Business logic (Layer 2)
  execution_orchestrator.py   Dispatch strategy: trigger → Run → Engine
  execution_launcher.py       Engine-fire lifecycle: Trace → Context → Engine → Error recovery
  agent_spawn_adapter.py      Sub-agent dispatch for coordinator tools
  dispatch_service.py         API-facing wrapper around orchestrator
app/core/            → Infrastructure (Layer 3)
  engine/protocol.py          ExecutionContext + ExecutionEngine Protocol
  engine/{cli,graph,code,copilot}_engine.py
  observation/                OTel-backed tracing
  events/                     Event bus + subscribers
  state_machines/             Run/Execution status transitions
  ports/                      Protocol interfaces (dependency inversion boundary)
app/models/          → ORM models (Layer 4)
```

**Dependency rule**: Each layer only imports from the layer below. `core/` never imports from `services/` — communication goes through Port protocols.

## Dispatch Flow

```
User action (API / chat / task / scheduler)
  │
  ▼
ExecutionOrchestrator.dispatch_*()
  │  Validates, resolves agent/release/version
  │  Constructs RunSpec (TriggerMedium, RunPurpose enums)
  ▼
_create_run_and_fire(spec: RunSpec)
  │  1. _require_no_active_run (DB partial unique index backstop)
  │  2. Create AgentRun (release_id XOR agent_version_id)
  │  3. Create Execution (attempt_index=1)
  │  4. db.commit()
  │  5. publish_run_status_change(running) → EventBus
  ▼
ExecutionLauncher.launch(spec: LaunchSpec)
  │  Resolves credentials, auto_approve, engine, runtime_binding
  │  Calls safe_create_task(_run_engine) — fire-and-forget
  ▼
_run_engine() [background task]
  │  1. AsyncSessionLocal() — fresh DB session
  │  2. _insert_trace() — Trace row (Trace.id = execution.id)
  │  3. Build ExecutionContext with typed ports:
  │     - model_port: ModelPort (ModelService)
  │     - runner_factory: Callable
  │     - _event_bridge: ContextEventBridge (_Bridge)
  │     - collector: ObservationCollectorPort
  │  4. Create ObservationCollector (OTel trace_id = execution.id)
  │  5. engine.start(ctx, ...) — delegates to specific engine
  │  6. finally: collector.finalize()
  │  7. except: fresh session → EXECUTION_COMPLETED(failed)
```

## Data Structures

### RunSpec
**Lifecycle**: Created by dispatch method, consumed by `_create_run_and_fire`, GC'd on return.

```python
@dataclass
class RunSpec:
    agent: Agent
    version: AgentVersion
    workspace_id: uuid.UUID
    prompt: str
    trigger_medium: TriggerMedium    # StrEnum: system/api/ui
    run_purpose: RunPurpose          # StrEnum: production/draft_test/internal_builder/debug
    user_id: str
    thread_id: uuid.UUID
    release: AgentRelease | None     # None = draft run
    ...
```

### LaunchSpec
**Lifecycle**: Created by orchestrator after Run+Execution are committed, consumed by launcher, GC'd after `safe_create_task`.

```python
@dataclass
class LaunchSpec:
    execution: Execution
    run: AgentRun
    version: AgentVersion
    agent: Agent
    workspace_id: uuid.UUID
    prompt: str
    auto_approve: bool
    release: AgentRelease | None
    ...
```

**Safety**: All ORM fields accessed are column attributes (not relationships), safe to read after session commit.

### ExecutionContext
**Lifecycle**: Created inside `_run_engine` background task, lives for engine execution duration, destroyed when `async with db` exits.

```python
@dataclass
class ExecutionContext:
    db: AsyncSession
    execution_id: uuid.UUID
    run_id: uuid.UUID
    workspace_id: uuid.UUID
    collector: ObservationCollectorPort | None
    model_port: ModelPort | None
    runner_factory: Callable[..., Any] | None
    _event_bridge: ContextEventBridge | None
```

## Port System

All Port protocols live in `core/ports/`. They define the boundary between `core/` and `services/`.

| Port | Consumers | Implementor |
|------|-----------|-------------|
| ExecutionEventPort | ExecutionRunner | execution_event_adapter |
| ExecutionReaderPort | ExecutionRunner | execution_reader_adapter |
| ObservationCollectorPort | ExecutionContext | ObservationCollector |
| ModelPort | graph_engine, model_resolver | ModelService |
| AgentSpawnPort | coordinator_tools | agent_spawn_adapter |
| MemoryPort | MemoryManager | MemoryService |
| ContextEventBridge | ExecutionContext | launcher._Bridge |
| SandboxPort | deep_agents/builder | (fallback to sandbox_manager) |
| SkillPort | deep_agents/skills_loader | (fallback to SkillService) |
| McpServerPort | mcp_tool_utils | (fallback to McpServerService) |

## OTel Tracing Architecture

```
App startup
  └── init_global_provider() → TracerProvider singleton
  └── init_global_processors() → PersistenceProcessor + BroadcastProcessor (global)

HTTP request
  └── TracingMiddleware._handle_http
      └── extract W3C traceparent → start_as_current_span
          → trace_id in logs + response header

WebSocket
  └── TracingMiddleware._handle_websocket
      └── start_as_current_span(ws:{path})

Execution
  └── ObservationCollector.__init__
      │  Forces OTel trace_id = execution_id.int (128-bit alignment)
      │  Registers execution to global processors
      └── All observation spans carry execution.id attribute
          → PersistenceProcessor routes to per-execution bucket → DB
          → BroadcastProcessor routes to per-execution bucket → WebSocket

App shutdown
  └── TracerProvider.shutdown() → flush all drain loops
```

**Trace ID alignment**: `Trace.id` (UUID) = `execution.id` = OTel `trace_id` (128-bit hex). Same 128-bit value, different formats. Zero-hop correlation between logs, Jaeger, and DB.

## Error Handling & Safety Nets

| Scenario | Primary Handler | Safety Net |
|----------|----------------|------------|
| Engine failure | launcher: fresh session → EXECUTION_COMPLETED(failed) | — |
| Launch failure (sync) | orchestrator: _publish_launch_failure | — |
| Engine hang | — | execution_reaper (10 min) |
| Collector finalize failure | — | _reap_orphan_traces (30s) |
| Bucket leak | — | reap_stale (30 min) |
| Concurrent dispatch | IntegrityError catch | DB partial unique index |
| Concurrent retry | SELECT ... FOR UPDATE | — |
| App shutdown | TracerProvider.shutdown() | — |
| Queue overflow | QueueFull catch + warning | Designed degradation |

## Event System

```
ExecutionEventEnvelope → ExecutionEventBus
  Phase 1 (sequential, shared transaction):
    PersistenceSubscriber  → writes ExecutionEvent row
    StateTransitionSubscriber → validates + transitions Execution/Run status
  Phase 2 (parallel, independent sessions):
    WebSocketSubscriber → broadcasts to frontend
    TaskSyncSubscriber → syncs Task status from Run
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (unset) | OTLP gRPC endpoint for trace export |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http/protobuf` |
| `DATABASE_POOL_SIZE` | 10 | Connection pool size |
| `DATABASE_MAX_OVERFLOW` | 20 | Max overflow connections |
