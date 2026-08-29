# Architecture

This document describes the current runtime architecture. Source code and automated tests are the final authority.

JoySafeter is an AI-agent orchestration platform for security work. A user defines
an **Agent** (engine + model + system prompt + tools + skills + MCP servers), opens a
**Session** (a conversation), and sends messages. Each message becomes a **Task** that
the platform schedules onto an isolated **sandbox** container, where a coding-agent
harness (Claude Code / Codex / a self-developed `ccb` runner) executes with the agent's
configured capabilities. Everything the harness does — text, thinking, tool calls,
tool results, model requests, sub-agent lifecycle — is streamed back as **events**,
persisted, and pushed to the browser live over **SSE**.

---

## 1. Deployment topology

JoySafeter runs as **two Python FastAPI services, one Rust orchestrator, and supporting
infrastructure**. The Python API and Worker share one codebase and select behavior at boot
from `JOYSAFETER_SERVICE_ROLE` (`api` / `worker`). The orchestrator is the Rust binary in
`app/joysafeter_orchestrator_rs`.

```mermaid
flowchart TB
    FE["Frontend Browser<br/>Next.js 16 / React 19"]

    subgraph API_S["API service　role=api"]
        API["REST /api/v1/* · auth"]
        BC["SSE endpoint<br/>SessionBroadcaster"]
    end

    subgraph ORCH_S["Rust Orchestrator service"]
        SCHED["Task scheduler<br/>DB pull · FOR UPDATE SKIP LOCKED"]
        GRPC["gRPC AgentBridge :9090"]
        XDS["Authenticated Delta ADS :9092"]
        BUS["Two-phase event bus<br/>persist ∥ broadcast"]
    end

    WK["Worker service　role=worker<br/>Stream consume → persist → republish"]

    subgraph REDIS["Redis (three mechanisms)"]
        RLIST[("list<br/>global_queue")]
        RSTREAM[("stream<br/>orchestrator:events")]
        RPUB[("pub/sub<br/>session_events:{id}")]
    end
    PG[("PostgreSQL<br/>source of truth + event log")]
    SKILLSPECTOR["skillspector<br/>skill security scan"]

    subgraph SBX["Sandbox container (per session, NetworkMode=none)"]
        RUN["Rust sandbox-runner<br/>+ claude / codex / ccb harness"]
    end
    ENVOY["Envoy<br/>sandbox's sole network conduit"]
    EXT["External: model API · MCP · targets<br/>(domain allowlist)"]

    %% submit & schedule
    FE -->|"POST /sessions/{id}/events"| API
    API -->|"create Task + rpush"| RLIST
    API -->|"read/write"| PG
    API -->|"scan on write"| SKILLSPECTOR
    RLIST -.->|"wakeup signal"| SCHED
    SCHED -->|"claim pending (DB authoritative)"| PG
    SCHED -->|"provision container"| SBX

    %% all sandbox traffic goes through Envoy
    RUN <-->|"gRPC AgentBridge"| ENVOY
    ENVOY <-->|"unix socket → TCP"| GRPC
    RUN -->|"outbound HTTP"| ENVOY
    ENVOY -->|"allowlist"| EXT

    %% two-phase event bus
    GRPC -->|"harness events"| BUS
    BUS -->|"① persist phase XADD"| RSTREAM
    BUS -->|"② broadcast phase PUBLISH"| RPUB
    RSTREAM -->|"XREADGROUP (consumer group)"| WK
    WK -->|"persist (seq/dedup)"| PG
    WK -.->|"republish"| RPUB

    %% SSE return path to the browser
    RPUB -->|"subscribe"| BC
    BC -->|"SSE stream (?after_seq replay)"| FE

    style API fill:#e1f5ff
    style BC fill:#e1f5ff
    style SCHED fill:#fff3e0
    style GRPC fill:#fff3e0
    style BUS fill:#fff3e0
    style WK fill:#fce4ec
    style RLIST fill:#ffebee
    style RSTREAM fill:#ffebee
    style RPUB fill:#ffebee
    style RUN fill:#e8f5e8
    style ENVOY fill:#ede7f6
```

### Services & containers

| Component | Compose service | Role | Key responsibility |
|---|---|---|---|
| **API** | `api` | `JOYSAFETER_SERVICE_ROLE=api` | REST `/api/v1/*`, SSE execution stream, notification WebSocket, auth |
| **Orchestrator (Rust)** | `orchestrator-rs` (profile `rust-orchestrator`) | — | gRPC `AgentBridge` server, task scheduler, sandbox lifecycle, event bus |
| **Worker** | `worker` | `worker` | Consumes the Redis event Stream, batch-persists events to `joysafeter_session_events`, republishes for SSE |
| **Frontend** | `frontend` | — | Next.js App Router UI |
| **PostgreSQL** | `db` | — | System of record for all state |
| **Redis** | `redis` (profile `local-redis`) or external | — | Event Streams, Pub/Sub fan-out, task queue, coordination |
| **Envoy** | `joysafeter-envoy` | — | Fronts each sandbox's unix socket; enforces per-sandbox egress allowlist |
| **skillspector** | `skillspector` | — | Standalone skill security-scanning service; advisory by default, optionally enforced only when publishing a version |
| **db-init** | `db-init` (profile `init`) | — | One-shot Alembic migrations |

Use the deployment helper for the supported local stack:
`cd deploy && ./deploy.sh doctor && ./deploy.sh local`.

### Collaboration contracts

Each service has one clear ownership boundary. Cross-service calls should preserve these
contracts instead of recreating older in-process shortcuts.

| Actor | Owns | Consumes | Publishes / mutates | Must not do |
|---|---|---|---|---|
| Frontend | Product UI state, auth redirects, SSE subscriptions | REST responses, SSE events, notification WS | User commands through REST | Talk to Redis, Postgres, orchestrator gRPC, or sandbox containers directly |
| API | Auth/RBAC, REST validation, CRUD, task creation, SSE replay/live bridge, skill write-time scan calls | Browser requests, DB state, Redis Pub/Sub for live events | DB rows, Redis task wakeup, Redis command relay | Run agent harnesses, create sandboxes, consume durable event streams |
| Rust orchestrator | Scheduling, task leases, sandbox lifecycle, runner gRPC, the elected xDS authority, control ACKs, event emission | Pending DB tasks, Redis wakeups/commands, runner gRPC streams, Envoy ACK/NACK | Task/sandbox/session state, Redis Stream events, Redis Pub/Sub broadcasts, leader-owned xDS resources | Serve product REST APIs, own browser auth, batch-persist event logs as the primary path, or let non-authority replicas mutate provider-local xDS state |
| Sandbox runner | In-container harness execution, tool/MCP invocation, memory/file sync from inside the sandbox | `SetupSandbox` and `StartTask` over gRPC, sandbox env, task-scoped files | Runner events/results over gRPC, memory sync messages | Receive generic secret maps or remote MCP authentication material, reach the host network directly, mutate platform DB/Redis, bypass Envoy egress policy |
| Worker | Durable event persistence, `seq` assignment, Redis Stream recovery/redelivery | Redis Stream consumer group | `joysafeter_session_events`, replay Pub/Sub after DB write | Schedule tasks, create sandboxes, expose user-facing APIs |
| SkillSpector | Static skill security scanning service | Skill content sent by API/domain service | Advisory verdicts and optional publish-time enforcement | Decide runtime packaging or invalidate already-published versions |
| PostgreSQL | Source of truth for domain state, task/session/sandbox FSMs, event log | Writes from API/orchestrator/worker/db-init | Durable rows | Act as a queue or live fan-out bus |
| Redis | Wakeups, Streams, Pub/Sub, command relay, ownership/heartbeat coordination | API/orchestrator/worker pub/sub/list/stream traffic | Ephemeral and durable-stream messages | Be treated as scheduling or network-policy truth; PostgreSQL rows are authoritative |

### Failure ownership

| Symptom | Primary owner | First checks |
|---|---|---|
| User cannot log in or CRUD resources | API | `api` logs, auth config, database connectivity |
| Session created but task never starts | Orchestrator | pending task row, `global_queue` wakeup, orchestrator logs, DB lease/fencing settings |
| Sandbox never becomes ready | Orchestrator + Docker host | Docker socket mount, sandbox image, workspace volume, runner `RunnerReady` timeout |
| Agent runs but browser misses live events | API SSE bridge + Redis Pub/Sub | API `SessionBroadcaster`, Redis Pub/Sub, browser `?after_seq` replay |
| Events appear live but disappear after refresh | Orchestrator event persister + Worker fallback | Orchestrator DB persist logs, Redis Stream pending entries, worker logs, Postgres insert errors, advisory-lock contention |
| Skill cannot be used at runtime | Skill domain | referenced version exists and has immutable version files |
| Sandbox cannot reach model/MCP/target | Envoy + orchestrator sandbox config | allowlist, Envoy config files, `JOYSAFETER_GRPC_PUBLIC_URL`, target DNS/network policy |

---

## 2. The core loop — from message to live events

This is the single most important flow. Follow it once and the rest of the architecture
falls into place.

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as API service
    participant Q as Redis (list + streams + pubsub)
    participant ORCH as Orchestrator
    participant RUN as Sandbox runner (Rust + harness)
    participant WK as Worker
    participant PG as PostgreSQL

    FE->>API: POST /sessions/{id}/events (user.message + Idempotency-Key)
    API->>PG: persist user.message event
    API->>API: TaskSubmissionService admission/idempotency boundary
    API->>PG: create JoySafeterTask (status=pending)
    API->>PG: session → running (+ status event)
    API->>Q: rpush joysafeter:global_queue <bare-task-uuid>

    Note over ORCH: scheduler claims pending task (DB is source of truth)
    ORCH->>PG: task pending → scheduling → running
    ORCH->>RUN: provision sandbox (Docker) if needed
    RUN->>ORCH: gRPC AgentBridge: RunnerReady
    ORCH->>RUN: SetupSandbox (stable sandbox config and memory mounts)
    ORCH->>RUN: StartTask (prompt, task resources, files, ...)

    loop harness execution
        RUN->>ORCH: RunnerHarnessEvent (text / thinking / tool_use / tool_result / model_request_* / task_notification)
        ORCH->>ORCH: map_harness_event → JoySafeterEventEnvelope
        ORCH->>PG: direct event persist (primary durable path)
        ORCH->>Q: XADD joysafeter:orchestrator:events (worker fallback/fan-out)
        ORCH->>Q: PUBLISH joysafeter:session_events:{id} (broadcast phase)
        Q-->>API: pub/sub → SessionBroadcaster
        API-->>FE: SSE event (assigned seq)
    end

    RUN->>ORCH: RunnerHarnessResult (status, usage) + RunnerIdle
    ORCH->>PG: task → terminal, session → idle

    Note over WK: fallback/backfill path
    Q-->>WK: XREADGROUP joysafeter:orchestrator:events
    WK->>PG: batch insert JoySafeterSessionEvent (dedup by event id)
    WK->>Q: publish_session_event_realtime → SSE fan-out
```

Core ownership rules:

1. **The DB is the source of truth for scheduling.** The Redis list
   (`joysafeter:global_queue`) is only a *wakeup signal*; the orchestrator claims work by
   querying `joysafeter_tasks` with `FOR UPDATE SKIP LOCKED`. If Redis loses a signal, the
   scheduler still finds the pending row.

2. **Task submission has one owner.** API routes, follow-up chat messages, manual
   trigger runs, and worker-fired cron triggers submit through
   `TaskSubmissionService`. That service owns idempotency replay, admission control,
   task creation, session running/idle transitions, enqueue, and enqueue-failure
   compensation. Routes may validate request-specific inputs, but they should not
   hand-roll task dispatch.

3. **Session resources have one owner.** File and git-repository resources mounted
   into sessions are validated, normalized, encrypted, listed, added, deleted, and
   rotated through `SessionResourceService`. Routes may discriminate the request
   body shape, but they should not write `SessionFile` / `SessionRepo` rows or
   encrypt clone tokens inline.

4. **Task cancellation has one owner.** API cancel requests and scheduler
   replacement policy cancel through `TaskCancellationService`. That service owns
   runtime cancel relay, task state transition, linked session idle transition,
   and the `session.status_idle` event. Routes and schedulers should not mark a
   task cancelled or write session-idle compensation inline.

5. **Project lifecycle has one owner.** Project create/list/default/restore/archive
   state transitions go through `ProjectService`. Project archive owns the full
   closed loop: default-project guard, active-task gate, session sandbox destroy
   relay, sandbox state sync, session archival, trigger pause, and the final
   project archive timestamp. Routes should not recreate that chain inline.

6. **Sandbox status writes are compare-and-swap.** Rust runtime state changes use
   `transition_sandbox_cas(expected_status, new_status)`, which validates the documented
   sandbox FSM before issuing the fenced update. There is no read-then-write compatibility
   transition API, so stale observers cannot select their own expected state.

6. **Organization membership has one owner.** Organization creation/deletion and
   member role lifecycle go through `OrganizationService` and
   `OrganizationMemberService`. Those services own owner membership bootstrap,
   default project bootstrap, owner/admin gates, role normalization, owner
   transfer, duplicate member checks, member removal, and route-specific error
   contracts. Routes may shape responses and audit events, but should not write
   `Member` rows or duplicate role policy inline.

7. **Persistence and live delivery are decoupled.** The orchestrator writes events
   directly to Postgres as the primary durable path and also publishes to Redis Stream
   for worker fallback/backfill and to Redis Pub/Sub for live SSE fan-out. The browser
   gets events fast; durable rows let a reconnecting client replay from `?after_seq`.

---

## 3. Transport map — what talks to what, and how

Runtime communication uses several purpose-built channels. This table is the definitive reference.

| Channel | Mechanism | Purpose | Anchor |
|---|---|---|---|
| Browser → API | HTTPS REST `/api/v1/*` | All CRUD + commands | `joysafeter_api/api/v1/router.py` |
| **Live events → browser** | **SSE** `GET /sessions/{id}/events/stream` | Primary execution stream (DB replay via `?after_seq`, then live) | `joysafeter_api/api/v1/sessions.py` |
| Notifications → browser | WebSocket `/ws/notifications` | User-level notifications (in-memory `NotificationManager`) | `joysafeter_api/app.py`, `joysafeter_api/websocket/notification_manager.py` |
| Per-task stream | WebSocket `/tasks/{id}/stream` | Per-task output (bridge queue → Redis fallback) | `joysafeter_api/api/v1/tasks.py` |
| Task enqueue | Redis **list** `joysafeter:global_queue` | API `rpush` → Rust orchestrator scheduler pops | `joysafeter_api/services.py`, `joysafeter_orchestrator_rs/src/kernel/queue.rs` |
| **Durable event bus** | Redis **Streams** `joysafeter:orchestrator:events` + consumer group | Orchestrator `XADD` → Worker `XREADGROUP` → DB persist | `joysafeter_orchestrator_rs/src/events/stream_publisher.rs`, `joysafeter_worker/events/stream_consumer.py` |
| **Live event fan-out** | Redis **Pub/Sub** `joysafeter:session_events:{id}` | Cross-instance SSE delivery via `SessionBroadcaster` | `joysafeter_orchestrator_rs/src/kernel/session_broadcaster.rs`, `joysafeter_shared/orchestrator_bridge/session_broadcaster.py` |
| Control/cancel relay | Redis **Pub/Sub** `joysafeter:cmd:{instance}` | Route cancel/input/shutdown to the instance owning the sandbox | `joysafeter_shared/orchestrator_bridge/runtime_commands.py`, `joysafeter_orchestrator_rs/src/kernel/command_listener.rs` |
| Network-policy wakeup | Redis **Stream** `joysafeter:network-policy:requests` | Wake the elected xDS authority for an exact PostgreSQL policy generation or teardown | `joysafeter_orchestrator_rs/src/kernel/ha/redis_impl.rs`, `joysafeter_orchestrator_rs/src/xds/authority.rs` |
| Orchestrator ↔ runner | **gRPC** `AgentBridge` (bidi stream, :9090) | The agent execution protocol | `proto/joysafeter.proto`, `joysafeter_orchestrator_rs/src/grpc/server.rs` |
| Runner egress | Envoy proxy (unix socket) | Per-sandbox domain allowlist, deny-all default | `joysafeter_orchestrator_rs/src/sandbox/envoy.rs` |
| Skill scan | HTTP → skillspector `:8010` | Informational scans on writes; optional fresh fail-closed scan only when publishing | `joysafeter_skill_security.py` |

**API ↔ orchestrator is Redis, not direct gRPC.** Python API/worker processes use
`joysafeter_shared.orchestrator_bridge` only for lightweight API-side helpers and optional test seams; runtime control flows through
Redis command relay and ACKs. gRPC is used *only* for the Rust orchestrator ↔ in-sandbox-runner hop.

---

## 4. Services in detail

### 4.1 API service (`app/joysafeter_api/`)

The API surface. Assembles a FastAPI app (`app.py`), wraps every `/api/v1` JSON response in
a `{success, code, message, data}` envelope via `ApiV1ResponseWrapperMiddleware`
(`api/v1/middleware.py`) — the middleware **skips** any `/stream` path and any
`StreamingResponse`, which is why SSE emits raw `text/event-stream`.

**Auth** (`app/joysafeter_shared/common/joysafeter_auth/dependencies.py`) resolves a
request in priority order: `X-Api-Key` header → JWT (from `Authorization` or cookie, with
real-time DB re-verification of org/project membership) → cookie/session fallback
(auto-provisions a default org+project on first login). Every project-scoped route filters
by `auth_ctx.project_id` for multi-tenant isolation. WebSocket connections authenticate via
a short-lived token from `GET /auth/ws-token`.

**Startup** is deliberately small: `run_api_startup()` only wires the `SessionBroadcaster` for SSE.

The full REST inventory is in [§8 API surface](#8-api-surface).

### 4.2 Orchestrator service (`app/joysafeter_orchestrator_rs/`)

The engine room. Hosts the gRPC `AgentBridge` server and a set of DB-driven control loops.
Agent code does **not** run in this process — it runs inside the sandbox runner, reached
over gRPC.

| Subsystem | Module | Responsibility |
|---|---|---|
| Runner server | `src/grpc/server.rs` | Binds the Runner TCP/UDS listeners, configures tonic limits/keepalive, and owns only server-task lifecycle |
| Runner transport | `src/grpc/transport.rs` | Adapts the closed protobuf `AgentBridge.Session` stream, enforces connection limits, and delegates typed messages |
| Runner session | `src/kernel/runner/session.rs` | Authenticates runners, performs the handshake, registers/displaces bridges, and delegates work through `RunnerFlowSet` |
| Runner child flows | `src/kernel/runner/{setup,task_lifecycle,execution,recovery,memory_sync,cleanup}.rs` | Own setup, durable task transitions, execution/event handling, reconnect recovery, memory synchronization, and disconnect cleanup independently |
| xDS control plane | `src/xds/control_plane.rs`, `src/xds/resource_store.rs`, `src/xds/node_ownership.rs`, `src/xds/delta.rs` | One process-level composition root, atomic explicitly-owned resource world, complete sandbox-to-node lifecycle, and Delta reconciliation |
| xDS transport | `src/xds/auth.rs`, `src/xds/transport.rs` | Dedicated `:9092` ADS listener, keyring authentication, and transport isolation from runner gRPC |
| xDS authority | `src/xds/authority.rs`, `src/xds/leader.rs` | Single `Standby → Staging → RecoveryServing → Ready → Revoked` lifecycle, epoch-fenced recovery/mutation guards, ADS admission, and leader endpoint publication |
| Task scheduler | `src/kernel/scheduler.rs` | Claims pending tasks (`FOR UPDATE SKIP LOCKED`), resolves a sandbox, pushes to the sandbox queue |
| Task controller | `src/kernel/task_controller.rs` | Lifecycle, startup recovery, failover/retry |
| Sandbox controller | `src/kernel/sandbox_controller.rs` | Timer/notification orchestration over isolated idle, provisioning, pool, orphan, and task-recovery capabilities |
| Sandbox resolution | `src/kernel/sandbox_resolver.rs`, `src/kernel/sandbox_resolver/*` | Reuse/restart → pool claim → create orchestration over explicit context, lifecycle, networking, provisioning, pool, and identity-policy capabilities |
| Sandbox bridge | `src/kernel/sandbox_bridge.rs` | Per-sandbox in-memory state: runner stream, status, subscribers, control queue |
| Redis coordinator | `src/kernel/redis_coordinator.rs` | Cross-instance HA: owner mapping, heartbeats, queues, event publishing |
| Command listener | `src/kernel/command_listener.rs` | Redis command relay for cancel/input/shutdown/memory updates with ACKs |
| Event bus | `src/events/bus.rs` | In-process event bus feeding stream persistence and realtime fan-out |
| Session broadcaster | `src/kernel/session_broadcaster.rs` | Live SSE fan-out via Redis Pub/Sub |

Startup order (`src/bootstrap/application.rs`; `src/main.rs` only delegates): config + database + Redis coordinator → one process-wide xDS authority and
`XdsControlPlane` → provider adapters receive the control plane → dedicated authenticated ADS on `:9092` → provider initialization →
`Staging` / `RecoveryServing` PostgreSQL recovery → `Ready` → runner `AgentBridge` on `:9090` → task and
lifecycle background loops. In multi mode, the Lease owner publishes its endpoint at `RecoveryServing` so
Envoy can ACK recovery; mutation guards remain unavailable until `Ready`. Lease loss and shutdown enter
`Revoked` before endpoint removal and transport shutdown. Multi mode fails closed when managed egress is
enabled without the Kubernetes leader-only xDS authority.

#### Orchestrator ownership and extension boundaries

The orchestrator has one composition root and several independently replaceable child flows. The main
flow may select implementations, connect ports, start them in dependency order, and supervise shutdown;
it must not reproduce provider, network-policy, xDS, or transport decisions. Concrete provider selection
is therefore registry-driven rather than hard-coded through branches in `main.rs` or business services.

| Area | Module | Owns | Inputs → outputs | May depend on | Failure owner |
|---|---|---|---|---|---|
| Process entry | `src/main.rs` | Logging/config entry and delegation only | environment → `JoySafeterConfig` → `OrchestratorApplication` | `bootstrap` | Invalid process configuration |
| Composition root | `src/bootstrap/application.rs` | Process-wide object graph, startup order, background-loop startup, coordinated shutdown | validated config → initialized ports, services, and handles | config, DB/Redis constructors, registries, application services, transports | Missing required infrastructure or an invalid cross-component topology |
| Provider registry | `src/bootstrap/registry.rs` | Normalized provider-name lookup and factory dispatch | provider name + factory context → `RuntimeComponents` | factory interfaces only | Unknown/disabled provider and factory construction errors |
| Runtime factories | `src/bootstrap/runtime_factories.rs` | Concrete adapter construction, `RunnerFlowSet`, the single production `SandboxRuntimeServices` capability graph, and composition-only event handlers | config + shared infrastructure → provider/runtime adapters and application ports | concrete adapters and fixed core-flow constructors, never business callers | Construction errors and invalid capability combinations |
| Supervision | `src/bootstrap/supervisor.rs` | OS shutdown signal and health/metrics HTTP exposure | readiness + xDS snapshots → process lifecycle/HTTP responses | stable health interfaces | Listener failure is reported here; domain failures remain with their owner |
| Material adapter | `src/bootstrap/network_policy_material.rs` | PostgreSQL/credential implementation of the domain material port | `SandboxId` → validated `DesiredNetworkPolicy` inputs | DB queries and credential projection | Missing sandbox, credential reconstruction, or material-loading failure |

`ProviderFactoryRegistry` is the extension point for a new sandbox backend. A new provider registers a
`ProviderFactory` that returns a `SandboxProvider` plus the optional policy-runtime, socket-provisioning,
Envoy-process, and placement-reconciliation capabilities supported by that backend. Callers consume those
ports and handles and do not downcast or branch on provider type.
The registry is confined to bootstrap so business code cannot become a service locator.

Registration and factories have deliberately different roles. Replaceable provider implementations use
`ProviderFactoryRegistry`; fixed application flows use explicit bootstrap factories. A core flow is not
looked up dynamically merely to avoid a constructor: `build_runner_flows` and
`build_sandbox_runtime_services` make the complete production graph reviewable and type-checked, while
consumers receive only their narrow ports. `application.rs` controls startup order and supervision but
does not instantiate child-flow implementations itself.

#### Sandbox application capabilities

`SandboxRuntimeServices` is the only production composition point for sandbox application capabilities.
It creates one shared set of immutable handles and hands each consumer only the capability it needs:

| Capability | Owner | Input → output | Direct dependencies | Failure owner |
|---|---|---|---|---|
| `ResolveContextBuilder` | `sandbox_resolver/context.rs` | task/session/agent/project IDs → immutable `ResolveContext` snapshot | PostgreSQL reads, identity material, MCP/runtime projections | Missing or inconsistent material; no provider side effect has started |
| `SandboxNetworkingService` | `sandbox_resolver/networking.rs` | validated desired policy/generation → ready or failed network state | `NetworkPolicyService`, PostgreSQL generation state, bounded ready cache | Network-policy validation/application/delivery failure |
| `SandboxLifecycleService` | `sandbox_resolver/lifecycle.rs` | observed sandbox state + external ID → CAS-fenced restart/destroy/compensation result | PostgreSQL, `SandboxProvider`, networking teardown | Lifecycle transition or compensation failure |
| `SandboxProvisioningService` | `sandbox_resolver/provisioning.rs` | task ID + immutable context → newly created `ResolvedSandbox` | provider port, lifecycle compensation, networking capability | Create/start/file-injection/generation/CAS failure; compensates partial runtime creation |
| `SandboxPoolService` / `PoolSandboxProvisioner` | `sandbox_resolver/pool.rs` | claim context or image → claimed/provisioned pool sandbox | PostgreSQL, provider port, networking capability | Claim race, stale pool runtime, or pool provisioning failure |
| `SandboxResolver` / `SandboxResolution` | `sandbox_resolver.rs`, `sandbox_resolver/ports.rs` | typed IDs → `ResolvedSandbox` | context, lifecycle, pool, provisioning capabilities only | Stage-selection failure; it owns no provider construction or identity-policy side channel |
| `SandboxIdentityPolicyService` / `SandboxIdentityPolicy` | `sandbox_resolver/identity_policy.rs` | sandbox/task identity lifecycle → refresh delay, refreshed policy, or cleared lease | context snapshot, networking, lifecycle | Identity lease/material/policy refresh failure |

`SandboxResolution` is consumed by the scheduler. `SandboxIdentityPolicy` is consumed by runner execution
and recovery. Runner code never depends on `SandboxResolver`, and the resolver does not re-export pool
provisioning, identity refresh, provider creation, or network-policy internals. Context objects are built
per resolve request and passed immutably; child services share cloneable handles, not mutable request
state.

`SandboxController` is a loop coordinator, not a bag of infrastructure dependencies. Its internal fixed
flows are composed once and have disjoint dependency sets:

| Child flow | Owns | Must not own | Failure behavior |
|---|---|---|---|
| `IdleSandboxMaintenance` | bridge health, idle/disconnect/hard-timeout reap, stuck-stop recovery, stopped/error TTL cleanup | pool provisioning or provisioning progress | Each phase reports independently; one sandbox or phase failure does not suppress later cycles |
| `ProvisioningSandboxMaintenance` | provisioning progress, timeout CAS, provider stop/destroy after claim | idle policy, pool sizing, orphan inventory | A failed CAS means another actor owns the new state; external cleanup follows only a successful claim |
| `SandboxPoolMaintenance` | HA-locked pool sizing, bounded parallel top-up, stale-pool cleanup | session resolution or task identity | Per-create failures are isolated; the HA lock is released on every result path |
| `SandboxOrphanMaintenance` | provider↔PostgreSQL inventory comparison and missing-runtime cleanup | pool sizing or xDS inventory | Recent uncommitted runtimes are protected; DB task recovery precedes durable sandbox destruction |
| `SandboxTaskRecovery` | queue drain/requeue, retry exhaustion, task/session durable transitions and events | provider/network/xDS operations | PostgreSQL is authoritative; queue publication is best effort after durable transition |

Bootstrap supervises `sandbox-idle-sweep` and `sandbox-provisioning-monitor` as critical tasks,
`sandbox-pool-orphan-maintenance` as degradable, and registers the network-policy reconciler separately
only for providers with egress management. The Controller neither holds `NetworkPolicyService` nor imports
xDS types.

#### Runner application capabilities

`RunnerSessionCoordinator` owns only authentication, handshake, bridge displacement/registration, and
connection lifetime. Bootstrap injects a `RunnerFlowSet`; the coordinator does not construct concrete
flows. Setup, task lifecycle, execution, recovery, memory synchronization, and cleanup exchange typed
inputs through the coordinator and do not share request-scoped mutable context. Transport failures belong
to `grpc/transport.rs`; authentication/connection failures belong to the coordinator; task/event/artifact
failures belong to execution; reconnect classification and orphan recovery belong to recovery; disconnect
state release belongs to cleanup.

#### Network-policy domain and application flow

`src/kernel/network_policy/` owns desired egress intent, deterministic revisioning, exact generation
orchestration, and the rules for converting runtime outcomes into PostgreSQL state transitions. It does
not own containers, Pods, ADS sessions, or protobuf/JSON encoding.

| Module | Responsibility and public capability | Dependencies and boundary |
|---|---|---|
| `mod.rs` | `DesiredNetworkPolicy`, canonical redacted revision, and `NetworkPolicyGeneration` value types | Pure domain inputs; no provider or transport access |
| `envoy_model.rs` | Validated, transport-neutral listener/cluster/credential policy model | Pure model/validation; renderers consume it but it does not consume renderers |
| `material.rs` | `NetworkPolicyMaterialResolver` input port | Implemented in bootstrap; domain callers see only `SandboxId → DesiredNetworkPolicy` |
| `ports.rs` | `NetworkPolicyRuntime` execution port and `NetworkPolicyRequestQueue` wakeup port | Infrastructure implements the ports; PostgreSQL remains authoritative |
| `request.rs` | Neutral reconcile/remove command carrying an exact generation where required | Safe to transport through Redis without embedding runtime state |
| `application.rs` | Prepare generation, validate material, apply/remove, wait for delivery, and persist exact CAS outcomes | Uses DB queries, domain ports, and authority guards; never constructs providers or xDS servers |
| `service.rs` | Crate-private application facade that owns policy capability composition and exposes ensure/reconcile/recover/teardown operations | Delegates domain decisions to `application.rs`/`recovery.rs`, adapters through ports, and durable transitions through DB queries; defines no second generation model |
| `authority.rs` | `NetworkPolicyAuthorityHandler`, adapting domain work to the generic elected-authority worker | Delegates only to `NetworkPolicyService`; owns no inventory, rendering, or persistence logic |
| `recovery.rs` | Rebuild and validate live limited-network inventory; classify ready, deferred, and quarantined entries | Reads PostgreSQL, invokes the runtime recovery port, persists exact recovery outcomes |

Normal reconcile follows one data path:

```text
business trigger
  → NetworkPolicyMaterialResolver.resolve(sandbox_id)
  → DesiredNetworkPolicy.revision/render_for
  → PostgreSQL prepare_generation(hash, version)
  → local authority apply OR Redis exact-generation wakeup
  → NetworkPolicyRuntime.apply
  → Envoy exact CDS/LDS ACK quorum
  → PostgreSQL mark_generation_applied CAS
```

Validation/material errors belong to the network-policy application boundary; stale or missing rows are
PostgreSQL concurrency outcomes; provider/render/delivery errors belong to `NetworkPolicyRuntime`; NACK and
timeout belong to xDS delivery. None may be hidden by changing a generation to ready, retrying with a
different generation, or treating Redis as truth. Recovery uses the same policy material and generation
rules, but installs one atomic resource world before persisting ready entries.

#### xDS domain, authority, and transport

`src/xds/` owns the in-memory xDS authority and protocol state. It accepts already validated resources and
explicit ownership; it does not load business credentials, decide desired policy, manage containers/Pods,
or persist sandbox lifecycle state.

| Module | Owns | Input → output / failure behavior |
|---|---|---|
| `authority.rs` | Authority FSM, epochs, recovery/mutation guards, application serialization, revocation | Lease/lifecycle events → fenced capability guards; stale epochs fail closed |
| `leader.rs` | Kubernetes Lease observation and leader-only Pod label publication | Lease + authority phase → xDS Service endpoint eligibility; API failures retry without granting authority |
| `authority_worker.rs` | Generic recover/reconcile/apply loop independent of Redis and network-policy details | request source + `AuthorityWork` handler → serialized guarded work |
| `control_plane.rs` | Stable process-local facade combining resource, ownership, delivery, and ADS services | explicit sandbox resources/placement → delivery attempts and snapshots |
| `model.rs` | Resource type, explicit owner, managed resource, sandbox bundle | Typed values only; no naming-based ownership inference |
| `resource_store.rs` | Atomic resource world and bounded revision log | owned resource batches → monotonic world revisions |
| `node_ownership.rs` | Sandbox-to-node truth and ownership transitions | neutral placement facts → scoped visibility revisions |
| `inventory.rs` | Atomic recovery inventory validation/install result | complete recovered world → installed/deferred inventory |
| `delivery.rs` | Exact generation delivery attempts and CDS/LDS quorum completion | world revision + node session ACK/NACK → terminal attempt result |
| `delta.rs` | Delta ADS subscriptions, reconnect reconciliation, per-node sessions, stream closure | authenticated protocol messages ↔ resource deltas/ACK/NACK updates |
| `auth.rs` | Shared-token keyring parsing and client principal authentication | request metadata → principal or `Unauthenticated` |
| `transport.rs` | Dedicated tonic ADS listener only | `XdsControlPlane` + authenticator → `:9092` server handle |
| `metrics.rs` | Bounded-cardinality health and Prometheus projection | internal counters/state → health/metrics snapshots |

The authority lifecycle is the sole permission model for xDS mutation. `RecoveryAuthorityGuard` permits
atomic startup reconstruction; `MutationAuthorityGuard` exists only in `Ready`. Lease loss revokes the
epoch, closes established ADS streams, and invalidates in-flight work. Resource storage, node ownership,
delivery quorum, and ADS sessions remain separate so a change to one state machine cannot silently mutate
another through shared ad-hoc context.

#### Sandbox and transport adapters

| Module | Owns | Explicit non-responsibilities |
|---|---|---|
| `src/sandbox/provider.rs` | Replaceable lifecycle/capability port for create/start/stop/destroy/status/exec/files | No PostgreSQL generation transitions and no xDS authority access |
| `src/sandbox/docker.rs` | Docker container, mount, socket, and runtime facts | Does not publish/remove xDS resources directly |
| `src/sandbox/k8s.rs` | Pod/PVC/spec lifecycle and watcher setup | Does not decide ownership or mutate xDS state |
| `src/sandbox/pod_watcher.rs` | Kubernetes Pod observation and neutral `PlacementEvent` emission | No dependency on `XdsControlPlane` or policy application |
| `src/sandbox/runtime.rs` | Small infrastructure ports for socket preparation and placement events | Contains no provider or xDS implementation |
| `src/sandbox/envoy.rs` | Composition facade that wires disjoint Envoy capabilities | Owns no process, socket, policy-delivery, desired-policy, or ADS mutable state |
| `src/sandbox/envoy/process.rs` | Bootstrap file lifecycle, managed Envoy process health, restart, and authority revocation on process failure | Does not render sandbox resources or own per-sandbox policy state |
| `src/sandbox/envoy/socket.rs` | Per-sandbox socket-directory preparation and readiness checks | Does not publish resources, mutate generations, or manage the Envoy process |
| `src/sandbox/envoy/policy_runtime.rs` | `NetworkPolicyRuntime` adapter, per-sandbox serialization, delivery wait/recovery/prune/removal | Does not own desired policy, durable generation, process lifecycle, or ADS protocol state |
| `src/sandbox/envoy_render/{json,proto}.rs` | Pure conversion from validated listener/cluster specs to Envoy JSON/protobuf | No I/O, DB, authority, delivery, or provider lifecycle |
| `src/sandbox/envoy_delivery.rs` | Provider-facing `EnvoyDelivery` port and `XdsControlPlane` adapter | No desired-policy decisions or implicit owner inference |
| `src/sandbox/envoy_filesystem.rs` | Limited local filesystem delivery adapter | Cannot claim atomic non-empty recovery or full CDS/LDS semantics |
| `src/grpc/server.rs` | Runner TCP/UDS binding and tonic server lifecycle | No authentication, SQL, Redis, task FSM, artifact, or recovery behavior |
| `src/grpc/transport.rs` | Protobuf stream adaptation and connection admission | No SQL/Redis access or task/session state transitions |
| `src/kernel/runner/session.rs` | Runner authentication, bridge registration, displacement, and disconnect lifecycle | Delegates task execution and reconnect policy; never binds sockets |
| `src/kernel/runner/execution.rs` | Task dispatch/event/result/artifact flow and execution concurrency | Does not authenticate transports or own reconnect policy |
| `src/kernel/runner/recovery.rs` | Reconnect classification, active-task resume, and orphan recovery | Does not bind transport or select sandbox providers |

The xDS domain owns `DeliveryGeneration`; the network-policy domain owns
`NetworkPolicyGeneration`. `sandbox/envoy_delivery.rs` is the only mapping boundary between them,
so xDS does not import business-domain generation types. Registry and factory implementations are
crate-private bootstrap details; normal consumers receive only `OrchestratorApplication`.

The Kubernetes placement path is deliberately inverted: the watcher emits `PlacementEvent`; the bootstrap
factory installs a handler that translates it into `XdsControlPlane` ownership calls. This keeps Kubernetes
facts replaceable and prevents the provider from acquiring xDS context. Runner gRPC and ADS use different
servers and ports (`:9090`/`:9091` versus `:9092`), so protocol changes, authentication, limits, and failure
handling cannot leak between execution and control-plane transports.

### 4.3 Worker service (`app/joysafeter_worker/`)

The durable persistence tier. Runs exactly one loop: `EventStreamWorker`
(`events/stream_consumer.py`) consumes the Redis Stream via a consumer group.

- `XREADGROUP` for new events; `XAUTOCLAIM` for messages idle > 60s (crash recovery / redelivery).
- Each event → `EventBatchSender` (`events/batch_writer.py`): groups by `session_id`, takes a
  Postgres advisory lock per session, computes the next `seq` from `MAX(seq)`, dedups, inserts
  `JoySafeterSessionEvent` rows.
- After insert, calls `publish_session_event_realtime()` → SSE fan-out.
- **ACK only after a successful DB write** — if persistence fails, the message is redelivered.

> **Note:** `event_stream_enabled` defaults to **false** in raw settings, but the supported
> Compose stack enables it. In the current split runtime, Rust `orchestrator-rs` emits events
> to Redis Stream and the Worker persists them; `JOYSAFETER_EVENT_STREAM_FALLBACK_TO_DB=true`
> allows the orchestrator to fall back to direct DB persistence if Redis Stream publishing fails.

---

## 5. The agent execution protocol — gRPC `AgentBridge`

Defined in `proto/joysafeter.proto`. One bidirectional streaming RPC:
`rpc Session(stream RunnerMessage) returns (stream OrchestratorMessage)`. The orchestrator
is the server; the in-sandbox Rust runner is the client. The DB is the source of truth — the
gRPC stream carries execution, not scheduling.

### Runner → Orchestrator (`RunnerMessage`)

| Message | Meaning |
|---|---|
| `RunnerReady` | First message; carries `sandbox_id`, `runner_token` (HMAC-verified), available providers, reconnect state |
| `RunnerHarnessEvent` | The live event stream (see below) |
| `RunnerHarnessResult` | Terminal result: `status`, `output`, `error`, `TokenUsage` (with per-model breakdown), `duration_ms` |
| `RunnerHeartbeat` | Liveness (also, any message resets the heartbeat deadline; 120s timeout) |
| `RunnerIdle` | Harness went idle; persists `harness_session_id` / `work_dir` back to the session |
| `MemoryFileSync` | Agent wrote a memory file inside the sandbox → sync back |

**`RunnerHarnessEvent`** carries `seq` + `timestamp_ms` + a `oneof`:
`TextEvent` · `ThinkingEvent` · `ToolUseEvent` (`tool`, `call_id`, `input_json`,
`is_control_request`) · `ToolResultEvent` · `ErrorEvent` · `StatusEvent` · `LogEvent` ·
`ModelRequestStartEvent` (`model`) · `ModelRequestEndEvent` (`model` + 4 token counters) ·
`TaskNotificationEvent` (background sub-agent lifecycle: phase, description, status, summary,
result, token/tool metrics).

### Orchestrator → Runner (`OrchestratorMessage`)

| Message | Payload |
|---|---|
| `SetupSandbox` | One-time prep: stable sandbox `skills[]`, `mcp_servers[]`, `custom_tools[]`, `setup_commands[]`, `memory_mounts[]`, `repos[]`, tool policy lists, `provider`, `model`, env |
| `StartTask` | Authoritative task snapshot: `task_id`, prompt/system prompt, provider/model, limits, env, per-task `mcp_servers`/`repos`/`skills`/`custom_tools`, tool policy lists, and `files[]`/`file_refs[]` |
| `CancelTask` | `reason` |
| `SendInput` | `content` (control-request reply / interrupt injection) |
| `Shutdown` | `reason` |
| `MemoryFileUpdate` | Push a memory-store file change into the sandbox |

> The protocol has no generic `secrets` map. Managed MCP credentials and limited-networking
> model credentials remain at the Envoy boundary. Unrestricted-network model credentials are
> supplied only through sandbox creation env, while repository clone credentials use the narrow,
> clone-only `RepoConfig.authorization_token` field rather than a reusable secret bag.

---

## 6. Engines, sandboxes, and the runner

### 6.1 Where engines actually run

Engine selection is just a string — the agent's `engine_kind` (`claude` / `codex` / `native` / `pi`)
travels as the `provider` field in `SetupSandbox`/`StartTask`, and the **in-sandbox Rust
runner** picks the matching harness. It also selects the Docker image
(`image_claude` / `image_codex` / `image_native` / `image_pi`).

The Rust runner is the only harness execution path. Python services do not retain a parallel
adapter or task-runner implementation.

### 6.2 The Rust sandbox-runner (`sandbox-runner/`)

A Cargo workspace (edition 2024, tonic/prost gRPC). Four crates:

| Crate | Role |
|---|---|
| `joysafeter-types` | Shared types + the `HarnessAdapter` trait SPI (`start`/`cancel`/`send_input`/`provider`/`is_available`), `HarnessInput`, `HarnessEvent` (mirrors the proto oneof) |
| `joysafeter-runtime` | `AdapterRegistry` + the concrete engine adapters (claude / codex / native / pi / mock) |
| `joysafeter-runner` | The in-sandbox binary that speaks gRPC `AgentBridge` back to the orchestrator |
| `joysafeter-ctl` | `joysafeterctl` operator/dev CLI (declarative REST client) |

The runner boots from env (`JOYSAFETER_ORCHESTRATOR_URL`, `JOYSAFETER_SANDBOX_ID`,
`JOYSAFETER_RUNNER_TOKEN`), dials the orchestrator (TCP or unix socket via Envoy), sends
`RunnerReady`, and services `StartTask`/`Setup`/`Cancel`/`Input`/`Shutdown`. For each task it
picks the adapter by `provider`, unpacks skills, runs setup commands, clones repos, writes
`.claude/settings.json` (MCP + tools + tool rules), builds `HarnessInput`, and launches the
harness as a persistent subprocess:

| `provider` | Adapter | Launches | Protocol |
|---|---|---|---|
| `claude` | `ClaudeAdapter` | `claude` CLI | stream-json over stdin/stdout, `--permission-prompt-tool stdio` |
| `codex` | `CodexAdapter` | `codex app-server --listen stdio://` | JSON-RPC |
| `native` | `NativeAdapter` | **`ccb`** binary | claude-style stream-json — the self-developed "Harness-Core" engine |
| `pi` | `PiAdapter` | `pi` CLI | provider-configured OpenAI Responses / Chat Completions / Anthropic messages |
| `mock` | `MockAdapter` | test double | env-gated |

### 6.3 Sandbox providers (`app/joysafeter_orchestrator_rs/src/sandbox/`)

Selected by `JOYSAFETER_SANDBOX_PROVIDER` (default `docker`). SPI: `SandboxProvider`
(`create/start/stop/destroy/status/exec/inject_files/setup_networking/...`).

| Provider | Backing | Notes |
|---|---|---|
| **Docker** | local `aiodocker` | Default. Mounts `work_dir:/workspace`, memory under `/mnt/memory/<name>`. Hardened: `CapDrop ALL`, no-new-privileges, PidsLimit, non-root user. Restricted networking → `NetworkMode=none` + Envoy unix socket |
| **E2B** | E2B REST (Firecracker VMs) | Requires `E2B_API_KEY` + `E2B_TEMPLATE_ID` |
| **Daytona** | Daytona REST | Requires `DAYTONA_API_URL` + `DAYTONA_API_KEY` |

**Envoy** gives each limited-networking sandbox no direct egress. The runner reaches the
orchestrator through its control channel, and outbound HTTP goes through a per-sandbox Envoy
listener with a deny-all-by-default policy. The module boundary is explicit:

- `src/sandbox/envoy.rs` owns sandbox networking lifecycle orchestration only;
- `src/kernel/network_policy/envoy_model.rs` owns validated provider-neutral policy and Envoy-facing value models;
- `src/sandbox/envoy_render/{json,proto}.rs` purely renders those validated models;
- `src/sandbox/envoy_delivery.rs` defines the single `EnvoyDelivery` provider port and adapts it to
  `XdsControlPlane`;
- `src/sandbox/envoy_filesystem.rs` is a non-atomic local compatibility adapter and deliberately
  refuses non-empty recovery or credential-bearing cluster/listener batches;
- `src/xds/control_plane.rs` is the in-process composition root, `resource_store.rs` is the only
  in-memory xDS resource truth, `node_ownership.rs` is the only sandbox-to-node truth, and
  `delta.rs` owns protocol reconciliation.

Provider code submits explicitly owned resources through `EnvoyDelivery`; it neither reaches into
Delta transport internals nor infers ownership from listener or cluster names. The removed
`sandbox/lds_backend.rs` compatibility facade must not be reintroduced.

### 6.4 MCP runtime plan and xDS authority

The Rust orchestrator resolves each agent's MCP configuration into one immutable runtime plan.
The plan is the common source for the runner-safe projection and the secret-bearing Envoy
projection; callers must not independently reinterpret MCP transport, endpoint, authentication,
or network mode.

- Remote MCP transports are `streamable_http` and `sse`; local processes use `local_stdio`.
- Agents own every MCP server declaration. Project-scoped credential groups own encrypted HTTP
  authentication material, and Sessions own the `credential_group_ids` authorized for that run.
- The planner matches selected active credentials to Agent endpoints by canonical normalized URL:
  `required` needs exactly one match, `optional` accepts zero or one, and `none` ignores matches.
  Duplicate credentials are errors only when they match an Agent endpoint eligible for injection.
- Managed credential injection is supported only for `streamable_http`. `sse` must use
  `auth_requirement: none`; `local_stdio.env` is ordinary Agent configuration and must not contain secrets.
- Limited-networking sandboxes receive only opaque `mcp-egress.internal/r/<route-key>/` URLs.
  Real upstream authorities and authentication material remain at the Envoy boundary.
- MCP credentials support the closed runtime schemes `static_bearer`, `header_api_key`, and
  `custom_header`. Reserved or unsafe headers, userinfo, malformed URLs, and disallowed resolved
  addresses fail before listener publication.
- `runtime_config_generation` and sandbox `networking_policy_hash/version/status` in PostgreSQL
  are durable truth. A sandbox is executable only when the captured runtime generation still
  matches and the exact network-policy generation is `ready`.

Multi-replica xDS follows one topology only:

```text
PostgreSQL desired generation/status
        ↓
Redis network-policy wakeup (not state)
        ↓
single Kubernetes Lease-elected xDS authority
        ↓
Envoy ACK/NACK
        ↓
PostgreSQL generation CAS
```

All orchestrator replicas may schedule tasks, own runner bridges, and publish exact-generation
wakeups. Only the authority replica may recover, apply, remove, or prune provider-local xDS
resources. Envoy DaemonSet pods connect to `joysafeter-orchestrator-xds`, whose selector contains
`joysafeter-xds-leader=true`; runner traffic continues through the ordinary load-balanced
orchestrator Service.

Authority activation is ordered and fenced: the pod acquires the dedicated Lease, enters `Staging`,
recovers the complete live limited-networking inventory from PostgreSQL, atomically installs that
world, enters `RecoveryServing`, publishes the leader endpoint, waits for Envoy ACKs, and then marks
the epoch `Ready`. A valid recovery generation whose Kubernetes data plane is not initialized is
excluded from the active resource world and classified as deferred, not quarantined; its exact
generation remains `pending` for the PostgreSQL-driven degraded-policy reconciler. Quarantine is
reserved for invalid policy state or terminal delivery failure. Standby and `Staging` ADS calls fail closed. Losing the Lease or shutting down
revokes the epoch, disables ADS, actively closes existing ADS streams, and removes the label; the
design does not rely on Kubernetes endpoint removal to terminate established HTTP/2 connections.
Every mutation is serialized by one authority application lock and carries an epoch guard. ACK and
NACK persistence are terminal compare-and-set transitions from `pending`, so a late failure cannot
overwrite an acknowledged generation. Teardown requests are revalidated against the sandbox's
current PostgreSQL lifecycle/network mode before touching provider-local xDS state. NACK, timeout,
generation drift, or persistence failure leaves the sandbox non-ready.

Redis delivery is deliberately non-authoritative. Missed reconcile messages are repaired by the
leader-only degraded-policy loop using PostgreSQL. Missed teardown messages are bounded by the
authority's periodic prune, which removes only xDS resources absent from the live PostgreSQL
inventory without republishing healthy generations. A new leader always rebuilds from PostgreSQL
and never depends on replaying Redis history.

The health port exposes `/healthz/xds` and `/metrics`. `/healthz/xds` is 200 only in `Ready`; all
other authority phases and disabled xDS return 503. Metrics use bounded labels and cover authority
phase/epoch, recovery result and duration, authenticated/rejected ADS streams, active Envoy nodes,
pending delivery age, ACK/NACK totals, reconnect removals, ownership transitions, stale-session
closures, and durable degraded inventory. Sandbox IDs, resource names, hashes, tokens, payloads,
and error text are never metric labels.

xDS currently uses a dedicated shared-token keyring; mTLS is intentionally not enabled. The server
accepts every token in `JOYSAFETER_XDS_AUTH_KEYRING`, while generated Envoy bootstrap uses the token
selected by `JOYSAFETER_XDS_AUTH_WRITE_KEY_ID` and supplied as `JOYSAFETER_XDS_AUTH_TOKEN`. Rotate
without downtime in three rollouts: add the new token while retaining the old write key; switch the
write key and Envoy token after every authority accepts both; then remove the old token only after
all Envoy pods have reconnected and authentication/rejection metrics are healthy.

---

## 7. Domain model

Persisted in PostgreSQL via async SQLAlchemy 2.0. There is **no `execution`, `run`, or `mission` table**.
The run unit is `JoySafeterTask`; the
conversation unit is `JoySafeterSession` with an append-only event log.

### 7.1 Central entities

| Entity | Table | Role |
|---|---|---|
| `JoySafeterAgent` | `joysafeter_agents` | Agent definition. Capabilities (`skills`, `tools`, `mcp_servers`, `model`, `agents`, `commands`) stored **denormalized as JSONB** on the row, not join tables. Versioned via `joysafeter_agent_versions` |
| `JoySafeterSession` | `joysafeter_sessions` | Conversation/thread. Accumulates token usage; snapshots the agent at creation |
| `JoySafeterSessionEvent` | `joysafeter_session_events` | **Append-only event log**, `unique(session_id, seq)`. The persisted event stream |
| `JoySafeterTask` | `joysafeter_tasks` | The run/execution unit. Links to a session via `chat_session_id` |
| `JoySafeterSandbox` | `joysafeter_sandboxes` | Sandbox lifecycle record; ≤1 active sandbox per session |
| `JoySafeterCredential` | `joysafeter_credentials` | Unified model, service, and MCP credential records; values are **AES-256-GCM encrypted** and resolved for authorized runtime use |
| `JoySafeterCredentialGroup` | `joysafeter_credential_groups` | Project-scoped groups for organizing MCP credentials; session bindings live in `joysafeter_session_credential_groups` |
| `JoySafeterSkill` (+ versions, files, scans, collaborators, usage) | `joysafeter_skills*` | Full skill subsystem: 4-tier visibility, lifecycle FSM, security scans, versioned snapshots |
| `JoySafeterMemoryStore` / `Memory` / `MemoryVersion` | `joysafeter_memory*` | Agent-writable KV stores with append-only version history |
| `JoySafeterFile` / `SessionFile` / `SessionRepo` | `joysafeter_files*` | Uploaded files & git repos mounted into sessions |
| Identity | `joysafeter_users`, `_auth_sessions`, `_oauth_account`, `_organizations`, `_organization_members`, `_organization_projects`, `_project_members`, `_api_keys` | Users, sessions, OAuth links, orgs, projects, membership, API keys |

Persistence pattern: a thin `BaseRepository[T]` exists for auth/skills, but most services issue
SQLAlchemy statements directly against a per-request `AsyncSession` and commit inside the
service method (no unit-of-work).

### 7.2 State machines

Four distinct FSMs govern lifecycle. Transitions are guarded (conditional `UPDATE ... WHERE
status = ...` or advisory-locked) so concurrent writers can't corrupt state.

| FSM | Entity | States | Terminal |
|---|---|---|---|
| **Task** | `JoySafeterTask` | `pending → scheduling → running → {completed, failed, aborted, timeout, cancelled}` (+ retry → `pending`) | the 5 outcomes |
| **Session** | `JoySafeterSession` | `idle ↔ running ↔ rescheduling`, any → `terminated` | `terminated` (reactivatable) |
| **Sandbox** | `JoySafeterSandbox` | `creating → provisioning → pooled → idle ↔ running → stopping → stopped / error → destroyed` | `destroyed` |
| **Skill lifecycle** | `JoySafeterSkill` | `draft → pending_review → {approved, rejected}`, `approved → archived`, reopen/unarchive edges | — |

Publishing requires the mutable Skill to be `approved`. After a version is published, Agent
references, runtime packing, and promotion depend on that immutable published version rather
than the parent Skill's later lifecycle or scan state.

---

## 8. API surface

All paths are under `/api/v1`. Routers are wired in `joysafeter_api/api/v1/router.py`. There
are **no** standalone `models` / `mcp` / `tools` / `copilot` / `graphs` routers — those
concepts live inside the agent (JSONB fields) or in unified credentials and credential groups.

### 8.1 Typed entity identifiers

Public APIs, persisted JSON/JSONB references, logs, and frontend state use canonical prefixed IDs. The
prefix is a semantic discriminator, not decoration: it makes cross-entity mistakes rejectable before a
UUID reaches domain logic. Application/domain code uses the matching typed ID; it does not strip and
rebuild prefixes.

This is the authoritative UUID-backed entity inventory:

| Entity type | Public prefix | Entity type | Public prefix |
|---|---|---|---|
| `AgentId` | `agent_` | `AgentVersionId` | `agentver_` |
| `ApiKeyId` | `apikey_` | `SessionId` | `sess_` |
| `TaskId` | `task_` | `TriggerId` | `trig_` |
| `EnvironmentId` | `env_` | `CredentialId` | `cred_` |
| `CredentialGroupId` | `credgrp_` | `SandboxId` | `sbx_` |
| `MemoryStoreId` | `memstore_` | `MemoryId` | `mem_` |
| `MemoryVersionId` | `memver_` | `SkillId` | `skill_` |
| `SkillFileId` | `sklfile_` | `SkillSecurityScanId` | `sklscan_` |
| `SkillVersionId` | `sklver_` | `SkillVersionFileId` | `sklvfile_` |
| `SkillUsageId` | `skluse_` | `EventId` | `evt_` |
| `FileId` | `file_` | `SessionResourceId` | `sesrsc_` |
| `StorageVolumeId` | `vol_` | `StorageGrantId` | `stgrant_` |
| `StorageMountAuditId` | `staudit_` | `UserId` | `user_` |
| `OrganizationId` | `org_` | `OrganizationMemberId` | `orgmem_` |
| `ProjectId` | `proj_` | `ProjectMemberId` | `projmem_` |
| `OAuthAccountId` | `oauthacct_` | `AuthSessionId` | `authsess_` |
| `CredentialAccessAuditId` | `credaudit_` | `SecurityAuditId` | `secaudit_` |
| `SandboxNetworkPolicyId` | `sbxnetpol_` |  |  |

Bare UUIDs are retained only at these reviewed physical boundaries:

| Physical boundary | Bare UUID contract |
|---|---|
| SQL UUID bind/result | SQLAlchemy `EntityIdType` and transparent SQLx wrappers bind native UUID columns and hydrate the concrete typed ID immediately on read. |
| PostgreSQL advisory locks | Lock-key derivation uses UUID bytes solely to produce the database's signed 64-bit lock key. |
| Redis queues, channels, and payloads | Queue members, channel/key suffixes, ownership values, and event/runtime payload fields use bare UUID strings when both producer and consumer explicitly restore the concrete ID type. |
| Runner/protobuf fields | Runner commands and protobuf messages whose schemas define UUID strings unwrap at construction and restore typed IDs when re-entering application code. |
| OpenTelemetry identities | Trace, span, execution, and observation UUIDs are telemetry/storage identities rather than public JoySafeter entity-ID contracts. |
| Object-storage keys | File object keys use the bare `FileId` UUID; public file metadata and routes retain `file_<uuid>`. |
| Physical resource naming | Runner environment variables plus sandbox-provider labels, pod/container names, and Envoy resource names may derive bare UUID text from a typed ID solely for stable infrastructure naming. These are deployment/runtime names, not third-party API schemas. |
| Third-party UUID contracts | An external API may receive or return a bare UUID only when its independently documented schema requires UUID text; the adapter restores the concrete typed ID before application use. |

The architecture scanner also reviews three explicit native-UUID conversion categories that do not
create a retained bare-string contract: the typed-ID codec implementation itself, strict validation
probes that intentionally attempt native UUID parsing to reject bare public input, and deterministic
non-identity derivations such as advisory hashes or jitter seeds. Their allowlist entries are scoped by
stable file/function or file/count keys and any new occurrence fails architecture tests until classified.

Rust ID newtypes do not implement `Deref<Uuid>`; a physical adapter must call `.as_uuid()` explicitly.
Agent, Session, Trigger, and execution-snapshot environment bindings use `environment_id` exclusively.
Public and persisted JSON require canonical `env_<uuid>` values, while PostgreSQL stores the native UUID
behind a foreign key to the Environment lifecycle owner. Environment names are display and lookup metadata,
not identity inputs. Current contracts use `model_credential_id`,
`environment_credential_ids`, `credential_ref`, `credential_field`, and `credential_group_ids`.
Persisted snapshots use `joysafeter.agent_execution_snapshot.v2`. Earlier aliases and snapshot schemas
must be rewritten by migration before deployment; runtime readers reject them rather than bridging them.

Memory synchronization, Session events, Skills, Files, Session resources, and storage resources follow
the same rule: API paths, schemas, JSON, logs, and frontend state retain their canonical prefix, while
only a listed physical adapter may unwrap to a UUID. Draft Skill authoring files remain identity-free
until persisted and must not use empty or fabricated `SkillFileId` values.
Session memory-store attachments are public Session resources: their rows and responses use
`SessionResourceId` / `sesrsc_` and `type=session_memory_store`; the referenced store remains a
separate `MemoryStoreId` / `memstore_` identity.

| Group | Prefix | Highlights |
|---|---|---|
| **Auth** | `/auth` | sign-up/in, logout, refresh, password reset, email verify, `ws-token`, `switch-context`, projects, api-keys, members |
| **OAuth / SSO** | `/auth/oauth` | provider list, authorize, callback, account link/unlink |
| **Agents** | `/agents` | CRUD, archive, versions, `/tasks`, `/sessions` |
| **Tasks** | `/tasks` | create+enqueue, list, get, cancel, **WS** `/tasks/{id}/stream` |
| **Sessions** | `/sessions` | CRUD, archive, stop, `POST /events` (send), `GET /events` (history), **SSE** `/events/stream`, resources (files/repos) |
| **Triggers** | `/triggers` | Cron/webhook trigger CRUD, manual `/run`, run history, inbound `/webhook` (+ signed `/webhook-sample`, `/test`) |
| **Environments** | `/environments` | Sandbox image/config CRUD |
| **Credentials** | `/credentials` | Model connections, service credentials, MCP members, lifecycle, testing, references, and default selection |
| **Credential groups** | `/credential-groups` | MCP credential grouping, lifecycle, membership, and references |
| **LLM** | `/llm` | Model `/catalog` (OpenAI-compatible provider models) |
| **Skills** | `/skills` | CRUD, `import-zip`, files, versions, security-scans, lifecycle transitions, admin rescan |
| **Skills AI authoring** | `/skills/ai-authoring` | **SSE** `/chat` (LLM authoring turn), `/save-draft` |
| **Sandboxes** | `/sandboxes` | list, get, stop |
| **Network policies** | `/network-policies` | Egress `/diagnostics`, per-session policy `/sessions/{id}` |
| **Memory stores** | `/memory_stores` | store + memory CRUD, versions, redact; sandbox memory sync is relayed through the Rust runtime |
| **Files** | `/files` | upload, list, metadata, download, delete |
| **Storage volumes** | `/storage-volumes` | Volume `/catalog` + CRUD, project & organization grants, `/audit/logs` |
| **Organizations** | `/organizations` | org + member CRUD, transfer-ownership |
| **Analytics** | `/analytics` | Usage analytics: summary, timeseries, engine share, calls, agent comparison/ranking, latency/error stats |
| **Quickstart** | `/quickstart` | **SSE** `/chat` — guided onboarding LLM proxy |
| **Health** | `/health` | readiness (Postgres + Redis), liveness |

---

## 9. Cross-cutting concerns

### 9.1 Multi-model — the "unified protocol"

There is **no coded multi-provider adapter registry** in the backend. The shared LLM layer
(`joysafeter_shared/llm/openai_stream.py`) is a single OpenAI-compatible SSE streaming helper:
credentials (`api_key`, `base_url`, `model`) are passed in, never resolved there. Any provider
— OpenAI, Claude, Gemini, DeepSeek, Qwen, etc. — is reached generically by pointing `base_url`
at its OpenAI-compatible gateway. This helper backs only first-party features (skill authoring,
quickstart). **Agent-workload model traffic is delegated to the CLI harness inside the
sandbox** (Claude Code / Codex / `ccb`), so real-world model routing, retry, and fallback live
in the runner and the CLIs, not in Python. Model config and credentials are DB-driven
(`joysafeter_credentials`, encrypted), managed through the unified Credentials UI.

### 9.2 Skills — the capability layer

Skills are versioned plugin packs (4 in-repo: `pptx` and `xlsx` document utilities, plus
`skill-creator` and `skill-security-auditor`), each
a `SKILL.md`-fronted directory. The pipeline spans three layers:

1. **Parse & validate** (`joysafeter_shared/skill/`) — SKILL.md YAML frontmatter + Agent-Skills
   spec constraints (name/description/allowed-tools), binary/size guards.
2. **Permission gate** (`joysafeter_shared/common/skill_permissions.py`) — 4-tier visibility
   (private/project/organization/public) with strict active-org isolation.
3. **Security scan** (`joysafeter_domain/.../joysafeter_skill_security.py` → **skillspector**
   service) — records advisory verdicts and canonical hashes. When
   `SKILL_SECURITY_SCAN_ENFORCEMENT_ENABLED=true`, publishing runs a fresh fail-closed scan
   over the exact snapshot; the default is `false`.
4. **Pack & deliver** — the Rust orchestrator's `HarnessInputBuilder` resolves a published version
   when the task starts, builds the `tar.gz` `SkillArchive` from immutable version files, and
   records usage. The runner unpacks the injected archive in the sandbox; missing versions stop
   input construction instead of silently degrading.

Version exposure is tier-aware at every boundary. Same-project Agents may use any published
version and resolve `latest` to the highest SemVer. Cross-project callers in the same organization
may use only the versions referenced by the organization/public pointers; cross-organization
callers may use only the public pointer. Skill list/detail/version APIs, Agent save validation, and
the Rust runtime apply the same rule. Cross-project reads are projected from the exposed immutable
version rather than the mutable parent Skill draft.

### 9.3 Observability — full-chain tracing

`joysafeter_shared/telemetry/` owns the application-level OTel provider:

- A global `TracerProvider` initializes request tracing and optionally exports spans through OTLP.
- `TracingMiddleware` extracts W3C `traceparent` on ingress and echoes `x-trace-id`; loguru
  injects the live `trace_id` into every log line for correlation.
- Product analytics are computed from durable sessions, tasks, and session events. The removed
  `Trace` / `Observation` persistence prototype is not a runtime or database contract.

### 9.4 Security posture

- **Auth:** JWT (HS256) with org/project/role claims + real-time DB re-verification; HttpOnly
  cookies; CSRF token on mutating requests; passwords SHA-256 pre-hashed client-side.
- **Credential encryption:** AES-256-GCM for unified credential values, task identity material, and repository
  tokens. Legacy `enc:`/`enc:v1:` ciphertext reads through `JOYSAFETER_VAULT_ENCRYPTION_KEY`; configured
  keyrings write `enc:v2:<key_id>:` through `JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING` and
  `JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID`. The exact v2 prefix is authenticated as AES-GCM
  associated data. Canary creation uses insert-if-absent semantics, never overwrites a concurrent winner,
  validates the committed winner, and rolls back its own partial batch on failure. Startup validates key
  syntax, database canaries, JSON object shape, and read-key coverage for every persisted envelope; a
  bounded worker rewraps old ciphertext before legacy keys are removed and rejects plaintext or malformed
  storage values. Startup intentionally does not decrypt every business ciphertext; authenticated payload
  corruption is detected when that material is used or selected for rewrap. The separate offline
  `credential_encryption_rotation.py --verify-integrity` mode runs in a PostgreSQL repeatable-read, read-only
  transaction, cursor-pages through every non-empty value on all four storage surfaces, decrypt-verifies current
  and historical envelopes, and emits only record coordinates plus stable failure categories.
- **Credential material flow:** API consumers reveal through the Application credential access service;
  Rust runtime consumers reveal through `CredentialMaterialAccessService`, which validates purpose,
  decrypts only authorized fields, and writes append-only access audit records. Snapshot and Harness MCP
  URL resolution are metadata-only. Sandbox creation owns model/environment material injection, while the
  Harness builder may read only an optional encrypted model-name field when no explicit model is configured.
  The removed `SetupSandbox.secrets` and `StartTask.secrets` field numbers and names are reserved, so the
  generic secret transport cannot be accidentally reintroduced or reused by a future wire schema.
- **SSRF guard:** blocks cloud-metadata IPs, resolves DNS to defeat rebinding; private RFC-1918
  allowed by default (internal LLM/MCP endpoints), opt-in hardening flags.
- **Sandbox isolation:** dropped capabilities, non-root, no-new-privileges, PID limits, and
  Envoy deny-all egress.
- **Skill scanning:** advisory by default. Optional enforcement runs only at version publication;
  later scans never invalidate or demote an already-published version.

---

## 10. Source layout

```
backend/app/
├── joysafeter_api/            # API service: REST routers, SSE, WS notifications, auth deps
│   ├── api/v1/                #   routers (auth, agents, sessions, tasks, skills, credentials, credential groups, ...)
│   ├── websocket/             #   notification manager + WS auth
│   ├── app.py / main.py       #   app assembly + entrypoint
│   └── startup.py             #   wires SessionBroadcaster
├── joysafeter_orchestrator_rs/ # Rust orchestrator service
│   ├── src/grpc/              #   AgentBridge server (+ generated proto)
│   ├── src/kernel/            #   scheduler, controllers, sandbox resolver/bridge, coordinator, queue
│   ├── src/runtime/           #   HarnessAdapter SPI + adapters
│   ├── src/sandbox/           #   Docker/E2B/Daytona providers, Envoy manager, image builder
│   ├── src/events/            #   event bus + stream/realtime subscribers
│   ├── src/main.rs            #   boot/shutdown wiring
│   └── Cargo.toml             #   Rust crate manifest
├── joysafeter_worker/         # Worker service
│   └── events/                #   EventStreamWorker (Redis Stream consumer) + EventBatchSender
├── joysafeter_application/    # Use-case orchestration; owns transaction boundaries and application ports
│   ├── api_keys/              #   project API-key lifecycle orchestration
│   ├── credentials/           #   credential/group lifecycle, binding, snapshots, resource resolution
│   └── sessions/              #   credential-aware session creation, resources, repository-token protection
├── joysafeter_domain/         # Data model + business logic
│   ├── models/                #   SQLAlchemy tables
│   ├── repositories/          #   thin base repo (auth/skills)
│   ├── schemas/               #   Pydantic DTOs
│   └── services/              #   agent/task/session/skill/memory/... domain services, policies, and FSMs
├── joysafeter_infrastructure/ # Adapters implementing application ports
│   ├── credentials/           #   SQLAlchemy, material, audit, dependency, and network-policy adapters
│   ├── repository_access/     #   repository credential material adapter
│   └── runtime_configuration/ #   runtime configuration status adapters
└── joysafeter_shared/         # Cross-service foundation
    ├── llm/                   #   OpenAI-compatible SSE helper
    ├── skill/                 #   SKILL.md parse + validate
    ├── telemetry/             #   OTel tracer-provider lifecycle
    ├── security/ security.py  #   JWT, passwords, SSRF guard, credential-key setting
    ├── storage/               #   pluggable file backend (local / s3 / oss)
    ├── cache/                 #   pooled Redis client + distributed lock
    ├── oauth/                 #   pluggable SSO (oauth2, jd_sso)
    ├── runtime/               #   app_factory, lifecycle, docker_check (shared by all 3 services)
    ├── config/                #   settings + service_role (the 3-service split switch)
    └── database.py            #   async SQLAlchemy engine/session

proto/joysafeter.proto         # AgentBridge gRPC contract
sandbox-runner/                # Rust workspace: types / runtime / runner / ctl
skills/                        # 4 skill packs (pptx, xlsx, skill-creator, skill-security-auditor)
deploy/docker-compose.yml      # 3-service + infra topology (Rust orchestrator profile)
frontend/                      # Next.js App Router UI
```
