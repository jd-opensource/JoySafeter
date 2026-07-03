# Rust Orchestrator Design — `joysafeter_orchestrator_rs`

> **Status (2026-07-03): Historical / experimental design.** The current checkout does **not**
> contain `backend/app/joysafeter_orchestrator_rs`, although `deploy/docker-compose.yml` and
> `deploy/docker/orchestrator-rs.Dockerfile` still reference it. Treat this document as design
> history unless the Rust orchestrator source directory is restored.

## Overview

Rust reimplementation of `backend/app/joysafeter_orchestrator/` that coexists with the Python version. Both share the same Postgres DB and Redis, using identical table schemas (managed by Python Alembic migrations). Deployment selects one version via config.

## Location

```
backend/app/joysafeter_orchestrator_rs/   # Rust workspace, peer to joysafeter_orchestrator/
```

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │    joysafeter_orchestrator_rs        │
                    │                                     │
  Postgres ◄───────┤  db/        (sqlx, raw SQL)         │
                    │  config/    (env + TOML)            │
                    │  grpc/      (tonic, AgentBridge)    │───── gRPC ────► sandbox-runner
                    │  kernel/    (scheduler, sandbox,    │
  Redis ◄──────────┤             queue, task lifecycle)   │
                    │  events/    (bus, persist, broadcast)│
                    │  sandbox/   (Docker via bollard)    │
                    │  runtime/   (adapter trait)         │
                    └─────────────────────────────────────┘
```

## Key Design Decisions

1. **Independent Rust workspace** — own `Cargo.toml`, own proto compilation, no dependency on `sandbox-runner/` crates
2. **Shared proto source** — references `../../proto/joysafeter.proto` via `build.rs`
3. **No ORM** — `sqlx` with raw SQL, compile-time checked queries
4. **No migrations** — table DDL owned by Python Alembic; Rust only reads/writes
5. **Tokio async runtime** — multi-thread, mirrors Python asyncio
6. **Same DB tables** — `joysafeter_tasks`, `joysafeter_sessions`, `joysafeter_sandboxes`, `joysafeter_session_events`, etc.
7. **Same Redis keys** — `joysafeter:*` namespace, identical pub/sub channels
8. **Deployment switch** — `ORCHESTRATOR_IMPL=rust|python` in docker-compose

## Batch Plan

### Batch 1 — Core skeleton (run a single task end-to-end)
- Project scaffold (Cargo.toml, build.rs, proto compilation)
- Config loading (env vars matching `JOYSAFETER_*`)
- DB layer (sqlx pool, core models, task/session/sandbox queries)
- gRPC server (AgentBridge bidirectional streaming)
- Event bus (in-process pub/sub, DB persist subscriber)
- TaskScheduler (poll DB → claim → resolve sandbox → dispatch)
- SandboxResolver (reuse session sandbox or create new Docker container)
- Docker sandbox provider (bollard)
- Task runner (event loop: StartTask → stream events → handle Result)

### Batch 2 — Production ready
- Redis coordinator (cross-instance HA, ownership, locks)
- Command listener (Redis pub/sub for cancel/input relay)
- SessionBroadcaster (Redis pub/sub → SSE/WebSocket fan-out)
- HITL (requires_action pause/resume with confirmation events)
- Sandbox pool management (warm pool, idle sweep, orphan cleanup)
- TaskController (startup recovery, overdue detection, failover/retry)

### Batch 3 — Full parity
- Daytona / E2b sandbox providers
- Memory sync (FUSE-like subscriber registry, MemoryFileUpdate relay)
- Codex adapter support
- Runtime config hot-reload (SIGHUP handler)
- Envoy network isolation manager
- Image builder
- File injection strategies

## Crate Dependencies

```toml
[dependencies]
tokio = { version = "1", features = ["full"] }
tonic = "0.12"
prost = "0.13"
sqlx = { version = "0.8", features = ["runtime-tokio", "tls-rustls", "postgres", "uuid", "chrono", "json"] }
redis = { version = "0.27", features = ["tokio-comp", "aio"] }
bollard = "0.18"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
uuid = { version = "1", features = ["v7", "serde"] }
chrono = { version = "0.4", features = ["serde"] }
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json"] }
anyhow = "1"
thiserror = "2"
config = "0.14"
sha2 = "0.10"
base64 = "0.22"

[build-dependencies]
tonic-build = "0.12"
```

## File Structure

```
backend/app/joysafeter_orchestrator_rs/
├── Cargo.toml
├── build.rs
├── src/
│   ├── main.rs
│   ├── config.rs
│   ├── error.rs
│   ├── proto.rs              # re-export generated types
│   ├── db/
│   │   ├── mod.rs
│   │   ├── pool.rs
│   │   └── models.rs
│   ├── grpc/
│   │   ├── mod.rs
│   │   └── server.rs
│   ├── kernel/
│   │   ├── mod.rs
│   │   ├── scheduler.rs
│   │   ├── sandbox_bridge.rs
│   │   ├── sandbox_controller.rs
│   │   ├── sandbox_resolver.rs
│   │   ├── task_runner.rs
│   │   ├── task_controller.rs
│   │   ├── queue.rs
│   │   ├── harness_input_builder.rs
│   │   ├── redis_coordinator.rs
│   │   ├── command_listener.rs
│   │   └── memory_sync.rs
│   ├── events/
│   │   ├── mod.rs
│   │   ├── bus.rs
│   │   ├── envelope.rs
│   │   ├── mapping.rs
│   │   ├── persist.rs
│   │   ├── session_state.rs
│   │   ├── session_broadcast.rs
│   │   ├── stream_publisher.rs
│   │   └── task_broadcast.rs
│   ├── sandbox/
│   │   ├── mod.rs
│   │   ├── provider.rs
│   │   ├── docker.rs
│   │   ├── daytona.rs
│   │   ├── e2b.rs
│   │   ├── envoy.rs
│   │   ├── image_builder.rs
│   │   └── file_injection.rs
│   └── runtime/
│       ├── mod.rs
│       ├── adapter.rs
│       └── registry.rs
└── tests/
    └── integration/
```
