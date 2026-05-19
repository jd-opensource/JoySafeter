# OTel Observability Architecture

## Overview

JoySafeter uses OpenTelemetry (OTel) as the single tracing infrastructure. All HTTP requests, WebSocket connections, and agent executions produce OTel spans that flow through a unified global TracerProvider.

## Architecture

```
                    ┌─────────────────────────────┐
                    │   Global TracerProvider      │
                    │   (init at app startup)      │
                    ├─────────────────────────────┤
                    │ PersistenceProcessor        │──→ DB (Observation rows)
                    │ BroadcastProcessor          │──→ WebSocket (live events)
                    │ [Optional] OTLPSpanExporter  │──→ Jaeger / Tempo / Datadog
                    └─────────────────────────────┘
                              ▲
          ┌───────────────────┼───────────────────┐
          │                   │                   │
  TracingMiddleware    ObservationCollector   trace.get_tracer()
  (HTTP + WS spans)   (execution spans)      (any manual span)
```

## Trace ID Strategy

**Domain-driven identity**: OTel trace_id = execution.id (128-bit aligned).

```
execution.id (UUID):  550e8400-e29b-41d4-a716-446655440000
OTel trace_id (hex):  550e8400e29b41d4a716446655440000
DB Trace.id (UUID):   550e8400-e29b-41d4-a716-446655440000
Log trace_id:         550e8400e29b41d4a716446655440000
A2A traceparent:      00-550e8400e29b41d4a716446655440000-...-01
```

Same 128-bit value everywhere. Zero-hop correlation.

HTTP requests get their own auto-generated trace_id (separate concern from execution).

## Components

### TracingMiddleware (`common/logging.py`)
- Wraps **both** HTTP and WebSocket at the ASGI layer
- HTTP: extracts inbound `traceparent`, creates root span, injects `x-trace-id` response header
- WebSocket: creates connection-level span (`ws:{path}`)
- loguru patcher reads trace_id from `get_current_span()` for every log line

### Global Processors (`observation/otel/`)

**BucketRegistry** (`processor_base.py`): Thread-safe `dict[str, B]` with lock. Shared by both processors.

**PersistenceProcessor** (`persistence_processor.py`):
- Global singleton, routes spans by `execution.id` attribute to per-execution `_ExecutionBucket`
- Each bucket has an async drain loop that batches Observation rows to PostgreSQL
- `reap_stale(1800)` cleans orphan buckets after 30 minutes

**BroadcastProcessor** (`broadcast_processor.py`):
- Global singleton, routes spans to per-execution `_BroadcastBucket`
- Fire-and-forget WebSocket broadcast via `asyncio.run_coroutine_threadsafe`
- `reap_stale(1800)` cleans orphan buckets

### ObservationCollector (`observation/collector.py`)
- Per-execution facade created in `ExecutionLauncher._run_engine`
- Forces OTel trace_id = execution_id via `SpanContext` construction
- Attaches context span so `get_current_span()` works in engine tasks
- `finalize()`: aggregates → broadcast trace_complete → shutdown processors → end span → detach context → update Trace row

### ObservationTracerProvider (`observation/otel/provider.py`)
- Per-execution facade over global TracerProvider
- Registers/unregisters execution with global processors
- Dispatches live streaming events (token-by-token)
- `init_global_processors()`: creates and attaches processors to global provider

### OTLP Export (`observation/otel/global_provider.py`)
- `OTEL_EXPORTER_OTLP_ENDPOINT`: when set, attaches `BatchSpanProcessor` + `OTLPSpanExporter`
- Graceful fallback: if exporter package not installed, logs warning and continues
- Supports `grpc` and `http/protobuf` protocols

## Thread Safety

- `BucketRegistry`: `threading.Lock` around dict operations
- `_ExecutionBucket`: per-bucket `threading.Lock` for aggregation counters + span-id mapping (single acquisition in `on_end`)
- `_BroadcastBucket`: per-bucket `threading.Lock` for span-id mapping
- No nested locks, no deadlock possibility (single-level lock ordering)

## Lifecycle

```
App startup:
  init_global_provider() → init_global_processors()

Per execution:
  ObservationCollector.__init__()
    → register to PersistenceProcessor + BroadcastProcessor
    → attach context span (forced trace_id)
  engine runs → spans created → processors route to buckets
  collector.finalize()
    → drain + pop buckets
    → end span + detach context
    → update Trace row

Safety nets:
  reap_stale() every 30s (scheduler) → 30 min TTL
  _reap_orphan_traces() → fixes Trace rows stuck in 'running'

App shutdown:
  TracerProvider.shutdown() → flush all drain loops
```
