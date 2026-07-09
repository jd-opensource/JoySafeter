# JoySafeter Production Readiness Audit - 2026-07-09

Status: complete for this pass. This audit records evidence from the current
worktree and does not treat design documents as implementation proof.

## Module Boundary

The production runtime is measured as three cooperating backend modules:

| Module | Production owner | Evidence anchors |
|---|---|---|
| API | REST/auth/RBAC, task creation, SSE replay/live bridge, skill scan calls | `backend/app/joysafeter_api/`, `docs/ARCHITECTURE.md` |
| Rust Orchestrator | DB-backed scheduling, sandbox lifecycle, runner gRPC, event emission, task ownership | `backend/app/joysafeter_orchestrator_rs/`, `deploy/docker-compose.yml` |
| Worker | Redis Stream recovery, durable event persistence, DB replay support | `backend/app/joysafeter_worker/`, `backend/tests/test_foundation2_*` |

Frontend and deploy remain production surfaces, but the critical collaboration
contract is API -> DB/Redis -> Rust Orchestrator -> Redis Stream/PubSub -> Worker/API SSE.

## Evidence Matrix

| Area | Current evidence | Judgment |
|---|---|---|
| Link completeness | API creates DB tasks and Redis wakeups; Rust scheduler claims DB rows; API control commands route to the owning Rust instance with ACK; API readiness exposes live/stale Rust orchestrator membership from Postgres; Rust runner-idle status changes update the session row and replayable event row in one transaction; runner events flow through Redis Stream/PubSub; Worker persists Redis Stream events; SSE supports replay/live. | Proven for a live Docker mock task from API-created session/task through Rust, sandbox runner, custom tool result relay, persisted events, terminal DB state, paginated HTTP replay, and SSE DB replay. |
| Self-consistency | Python task state machine had lease/fencing support, but production Rust path did not stamp or renew running-task ownership. Rust now stamps/fences/renews leases and only renews tasks that this process has actively claimed or adopted through a live bridge. | Gap found and fixed in this audit. |
| Bug risk | Stale runner results could previously pass `WHERE status = 'running'` after a lease reclaim and overwrite a newer run. Lease-expired reclaim also needed a CAS to avoid double retry increments across orchestrator instances. | Fixed in Rust production path; covered by new contract test and `cargo check`. |
| System resilience | Redis Stream worker has `xautoclaim` recovery and dead-letter handling. Rust orchestrator now stamps `owner_epoch`, renews only process-active leases, mirrors instance heartbeat into Postgres, reclaims expired running tasks, avoids orphan cleanup racing new sandbox DB inserts, and fails fast when the configured provider is weaker than the required isolation class. | Improved, not complete. Outbox and full provider-chain failover remain open. |
| Feature completeness | Task idempotency, project/user admission counters, skill scan gates, event stream health, resource lifecycle guards, Rust resource envelope propagation, provider minimum-isolation enforcement, mock runner execution, and session replay have test or live evidence. | Mixed. Dynamic provider chain/failover and full end-to-end quota enforcement still need production smoke verification. |

## Changes Landed In This Pass

- Rust orchestrator reads `JOYSAFETER_TASK_LEASE_TTL_SEC` and
  `JOYSAFETER_TASK_LEASE_RENEW_INTERVAL_SEC`, matching Python settings.
- `claim_next_sandbox_task` now stamps `owner_instance_id`, `owner_epoch`, and
  `lease_expires_at` when a task becomes `running`.
- Runner-result, cancel, and timeout writes now pass the claimed `owner_epoch`
  into `transition_task_cas`, preventing stale owners from writing terminal state.
- Cancel/timeout status broadcasts now happen only after the epoch-fenced CAS
  succeeds, keeping live SSE state aligned with DB authority.
- Terminal task transitions clear ownership/lease fields and stamp completion
  metadata consistently.
- TaskController renews live leases and uses lease-specific CAS reclaim/fail
  queries for expired running tasks, avoiding double retry increments when
  multiple orchestrators race on the same expired lease.
- TaskController lease renewal is now bounded to process-active tasks discovered
  from connected sandbox bridges. A restarted orchestrator with the same stable
  `JOYSAFETER_INSTANCE_ID` no longer extends leases for running tasks it has
  not actually adopted, which closes the hard-kill recovery hole found during
  game-day testing.
- Cancel now wins over a late runner `aborted` result in the Rust task loop.
  This prevents a cancelled task from later emitting a contradictory
  `session.status_idle` error event when the runner acknowledges cancellation
  as an aborted result.
- Rust `SandboxResolver` now labels provider sandboxes with owner instance,
  creation timestamp, and project id, while preserving CPU/memory resource
  envelope propagation into `SandboxCreateConfig`.
- Orphan cleanup now skips recently-created provider sandboxes without DB rows,
  preventing the cleanup loop from destroying a sandbox in the window between
  `provider.create()` and `joysafeter_sandboxes` insert.
- Rust command relay now ACKs `input` commands only when the sandbox bridge
  actually accepts the control input into its queue. A closed/full bridge queue
  no longer produces a false-success ACK to the API.
- Rust active task execution now forwards queued live input to the runner even
  when the task is not paused on a HITL control request. The live mock smoke
  exposed that ACK-to-queue alone was insufficient: non-HITL
  `user.custom_tool_result` events were acknowledged but never consumed by the
  runner until this loop was fixed.
- `joysafeter-runner` now preserves the live input control sender in
  `SurvivingTask` and forwards `Payload::Input` to a surviving task after
  runner reconnect. The hard-kill reconnect drill exposed that event replay and
  cancel still worked, but custom tool continuation did not reach the original
  mock harness without this channel.
- Added `joysafeter_cluster_members` migration and Rust orchestrator PG
  registration/heartbeat mirroring. Redis TTL remains the live coordination
  mechanism; Postgres now carries durable `heartbeat_at`/`expires_at` evidence
  for production audits and recovery checks.
- API readiness now queries the durable cluster membership mirror and reports
  live/stale orchestrator counts plus newest heartbeat/expiry timestamps. Zero
  live orchestrators degrades readiness visibility without turning a reachable
  API/Postgres pair into an HTTP 503.
- Fixed local deploy migration ordering: `deploy/deploy.sh local` now builds
  the `db-init` backend image before running Alembic, so new migration files are
  present when the migration step executes.
- Local deploy no longer relies on Compose build for project-owned images.
  Disabling `COMPOSE_BAKE` did not prevent the observed post-export hang, so
  `deploy/deploy.sh local` now builds backend, frontend, Rust orchestrator, and
  SkillSpector through the script-controlled `build_all_images` path, syncs the
  resulting image names into `deploy/.env`, and uses Compose only for
  `up --no-build` and `run --rm db-init`.
- Local deploy preflight now warns when the configured sandbox runtime image is
  absent. The live stack defaulted to `joysafeter-claudecode:latest`, but no
  `joysafeter-claudecode`, `joysafeter-codex`, or `joysafeter-native` image was
  present; a healthy control plane would still fail real agent execution.
- The Claude runtime Dockerfiles now install Node 22 via NodeSource
  `setup_22.x` across `claudecode`, `codex`, and `native` runtime images. The
  previous Node 20 base emitted an engine warning for current
  `@anthropic-ai/claude-code@latest`.
- Added `JOYSAFETER_SANDBOX_MIN_ISOLATION_CLASS` and Rust startup validation.
  `docker` satisfies `shared_container`, `daytona` satisfies
  `remote_workspace`, and `e2b` satisfies `isolated_vm`; weaker configured
  providers now fail fast instead of silently downgrading isolation.
- Added a Rust DB helper that updates session status and inserts the matching
  `joysafeter_session_events` row under one transaction/advisory lock, then
  routed runner-idle status writes through it. This narrows the outbox risk by
  removing the highest-frequency Rust status/event split-commit window.
- Rust idle status publishing now only broadcasts a status event after
  `update_session_status_and_insert_event` actually inserts the replayable DB
  event. This prevents fallback or race paths from publishing a fresh
  `session.status_idle` envelope after the session row/event have already
  converged.
- Cancel and server-timeout branches now also use the same atomic
  session-status/event helper before publishing `session.status_idle`. The
  review found that these direct branches could otherwise emit a live idle
  status without a replayable DB event, and the timeout path returned
  immediately after the live publish.
- Added `backend/tests/test_rust_orchestrator_task_lease_contract.py` to pin the
  Rust production-path contract.
- Added `backend/tests/test_rust_sandbox_provisioning_contract.py` to pin the
  Rust sandbox provisioning contract.
- Added `backend/tests/test_rust_command_relay_contract.py` and a Rust unit test
  to pin the API-to-Rust input ACK contract, including non-HITL live input
  forwarding from the bridge queue into `SendInput`, surviving-runner input
  forwarding after reconnect, and the cancel-over-error result precedence.
- Added `backend/tests/test_rust_cluster_membership_contract.py` to pin the
  durable cluster membership contract.
- Added `backend/tests/test_cluster_membership_health_contract.py` to pin the
  API readiness visibility contract for orchestrator membership.
- Added `backend/tests/test_cluster_membership_health_integration.py` to prove
  the readiness query against the real migrated Postgres registry.
- Added `backend/tests/test_deploy_local_migration_order_contract.py` to pin
  the local deploy order and sandbox runtime image preflight that the live
  smoke exposed.
- Added `backend/tests/test_rust_provider_isolation_contract.py` and Rust unit
  tests to pin provider isolation ranking and startup validation.
- Added `backend/tests/test_rust_session_status_atomic_event_contract.py` to
  pin the Rust session status/event atomicity contract.

## Verification Run

- `cargo fmt` in `backend/app/joysafeter_orchestrator_rs`
- `cargo check` in `backend/app/joysafeter_orchestrator_rs`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_rust_session_status_atomic_event_contract.py -q`
- `cargo test recent_uncommitted_provider_sandbox_is_protected_from_orphan_cleanup` in `backend/app/joysafeter_orchestrator_rs`
- `cargo test send_control_input_reports_closed_queue` in `backend/app/joysafeter_orchestrator_rs`
- `cargo test provider_isolation_rank_is_ordered_from_docker_to_e2b` in `backend/app/joysafeter_orchestrator_rs`
- `cargo test validate_provider_isolation_fails_when_provider_is_weaker_than_minimum` in `backend/app/joysafeter_orchestrator_rs`
- `python -m py_compile backend/alembic/versions/20260703_000009_add_cluster_members.py`
- `python -m py_compile backend/app/joysafeter_api/api/v1/health.py backend/tests/test_cluster_membership_health_contract.py backend/tests/test_cluster_membership_health_integration.py`
- `python -m py_compile backend/tests/test_deploy_local_migration_order_contract.py`
- `bash -n deploy/deploy.sh`
- `deploy/deploy.sh doctor`
- `SECRET_KEY=test-secret uv run --project backend --dev alembic heads`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_deploy_local_migration_order_contract.py -q`
- Post-local-deploy patch: `bash -n deploy/deploy.sh`
- Post-local-deploy patch: `deploy/deploy.sh doctor`
- Post-local-deploy patch: `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_deploy_local_migration_order_contract.py -q`
- Post-local-deploy patch: `deploy/deploy.sh local --arch arm64`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_rust_command_relay_contract.py backend/tests/test_deploy_local_migration_order_contract.py -q`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_cluster_membership_health_contract.py -q`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_cluster_membership_health_integration.py -q`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_deploy_local_migration_order_contract.py backend/tests/test_cluster_membership_health_contract.py backend/tests/test_cluster_membership_health_integration.py backend/tests/test_rust_cluster_membership_contract.py -q`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_deploy_local_migration_order_contract.py backend/tests/test_cluster_membership_health_contract.py backend/tests/test_cluster_membership_health_integration.py backend/tests/test_rust_session_status_atomic_event_contract.py backend/tests/test_rust_provider_isolation_contract.py backend/tests/test_rust_cluster_membership_contract.py backend/tests/test_rust_orchestrator_task_lease_contract.py backend/tests/test_rust_sandbox_provisioning_contract.py backend/tests/test_rust_command_relay_contract.py -q`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_rust_orchestrator_task_lease_contract.py backend/tests/test_rust_command_relay_contract.py -q`
- `SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_rust_command_relay_contract.py -q`
- `cargo fmt` in `sandbox-runner/crates/joysafeter-runner`
- `cargo check` in `sandbox-runner/crates/joysafeter-runner`
- `cargo test` in `sandbox-runner/crates/joysafeter-runner`
- `deploy/deploy.sh build --claudecode-only --arch arm64`
- `docker run --rm --entrypoint sh joysafeter-claudecode:latest -lc 'node --version && claude --version && test -x /usr/local/bin/joysafeter-runner && echo runner=present'`
- `DOCKER_DEFAULT_PLATFORM=linux/arm64 docker-compose -f deploy/docker-compose.yml --profile rust-orchestrator build orchestrator-rs`
- `docker-compose -f deploy/docker-compose.yml --profile local-redis --profile rust-orchestrator up -d --no-build orchestrator-rs`
- `docker-compose -f deploy/docker-compose.yml --profile local-redis --profile rust-orchestrator kill -s SIGKILL orchestrator-rs`
- `docker-compose -f deploy/docker-compose.yml --profile local-redis --profile rust-orchestrator up -d --no-build --force-recreate orchestrator-rs`

Static checks, unit tests, focused contract tests, and completed smoke checks
passed on 2026-07-09. Interrupted deploy-wrapper and Compose-build hang
observations are documented explicitly in the runtime smoke notes below.

## Remaining Production Risks

| Risk | Why it still matters | Next evidence needed |
|---|---|---|
| Full outbox absent | Rust runner-idle status/event writes are now atomic, but API session writes, Redis publication, and all event producers are still not covered by a unified DB outbox. | Implement or explicitly reject full outbox; run worker-down/restart zero-loss test. |
| Dynamic provider chain incomplete | Minimum isolation is enforced for the configured provider, but there is still no health-ranked provider chain that can choose among Docker/Daytona/E2B at runtime. | Implement provider chain or explicitly document single-provider production mode; add provider outage/fail-fast tests. |
| Tenant/resource admission needs runtime smoke | API counters exist and Rust provisioning carries project/resource metadata, and a single mock task now proves basic sandbox execution. This has still not been proven under real concurrent project/user quota pressure. | Run Docker inspect/resource tests and a concurrent project-admission smoke against the built runtime image. |
| Runtime CLI supply chain is still loose | `joysafeter-claudecode:latest` now runs on Node 22 locally, but the runtime image still installs `@anthropic-ai/claude-code@latest`, which is slow and mutable. Codex/native runtime images were source-fixed to Node 22 but not rebuilt in this pass. | Pin CLI versions or record an approved update cadence; rebuild/smoke codex/native images before enabling them in production. |

## Runtime Smoke Evidence Collected

- `deploy/deploy.sh doctor` passed on 2026-07-09. It confirmed Docker,
  SkillSpector source, Docker socket mapping, and Compose configuration; it
  warned that the normal local stack ports were already in use.
- Before redeploy, `docker ps` showed an existing JoySafeter stack:
  `joysafeter-api`, `joysafeter-worker`, `joysafeter-orchestrator`,
  `joysafeter-db`, `joysafeter-redis`, `joysafeter-skillspector`, and
  `joysafeter-frontend`.
- Approved `deploy/deploy.sh local` rebuilt backend/frontend/orchestrator
  images. The Rust orchestrator release image built successfully. The wrapper
  then stayed stuck in `docker-buildx bake` after image export, so it was
  interrupted and `docker-compose --profile local-redis --profile
  rust-orchestrator up -d --no-build` was used to complete service recreation
  from the freshly built images.
- That live redeploy exposed a migration-order bug: `run_local_migrations`
  had run `db-init` before rebuilding the backend image, so the database
  remained at Alembic `20260703_000008`; the new API readiness degraded with
  `cluster_membership_unavailable`, and the new Rust orchestrator restarted
  because `joysafeter_cluster_members` did not exist.
- The deploy script was fixed to build `db-init` before running Alembic.
  Running `docker-compose --profile local-redis --profile rust-orchestrator
  --profile init run --rm db-init` then applied
  `20260703_000008 -> 20260703_000009`.
- A later targeted reproduction showed that setting `COMPOSE_BAKE=false` was
  not sufficient: `docker-compose ... build orchestrator-rs` still exported the
  image and then failed to return cleanly. The local deploy script was therefore
  changed to avoid Compose build for project images entirely. It now builds
  core images through `build_all_images`, syncs `BACKEND_FULL_IMAGE`,
  `FRONTEND_FULL_IMAGE`, `ORCHESTRATOR_RS_FULL_IMAGE`, and
  `SKILLSPECTOR_FULL_IMAGE` into `deploy/.env`, and starts services with
  Compose `up --no-build`.
- The patched `deploy/deploy.sh local --arch arm64` then ran end-to-end. It
  built backend, frontend, Rust orchestrator, and SkillSpector through the
  script-controlled Buildx path; all four images exported and imported into
  Docker without hanging. The script then ran Alembic through `db-init` and
  recreated the local stack with Compose `up --no-build`, returning exit code 0.
- Post-local health checks were clean: `docker ps` reported frontend, API,
  worker, orchestrator, DB, Redis, and SkillSpector healthy/running;
  `/api/v1/health/ready` returned `status:"ok"` with `live_orchestrators:1`;
  Redis Stream group `pending:0` and `lag:0`; `joysafeter:events:dead` length
  was `0`; and the database reported `active_tasks=0`.
- After `docker-compose --profile local-redis --profile rust-orchestrator up
  -d --no-build orchestrator-rs`, Rust logs showed `Postgres cluster member
  heartbeat registered`, `gRPC server started`, and `JoySafeter kernel fully
  started`.
- Live Postgres now reports Alembic `20260703_000009`, and
  `joysafeter_cluster_members` contains `orchestrator-rs-001` with
  `expires_at > now()`.
- From inside `joysafeter-api`, `/api/v1/health/ready` now returns
  `status:"ok"` with `checks.cluster_membership.status:"ok"`,
  `live_orchestrators:1`, and `stale_orchestrators:0`.
- Worker logs show repeated `/health` HTTP 200 responses. Redis
  `xinfo groups joysafeter:orchestrator:events` reports consumer group
  `joysafeter-orchestrator-event-workers` with `pending:0`, `entries-read:9`,
  and `lag:0`. `joysafeter:events:dead` length is `0`.
- `docker ps` reports API, worker, DB, Redis, SkillSpector, and frontend as
  healthy; Rust orchestrator has no Docker healthcheck but is `running`. Its
  earlier restart count came from the pre-migration crash loop observed and
  repaired during this smoke.
- Runtime execution preflight initially found no local `joysafeter-claudecode`,
  `joysafeter-codex`, or `joysafeter-native` image, while the orchestrator was
  configured with `JOYSAFETER_SANDBOX_IMAGE=joysafeter-claudecode:latest`.
  `deploy/deploy.sh doctor` now warns when that configured runtime image is
  absent.
- `deploy/deploy.sh build --claudecode-only --arch arm64` built
  `joysafeter-claudecode:latest`. The initial build showed that current
  `@anthropic-ai/claude-code@latest` requires Node `>=22`; the runtime
  Dockerfiles were updated from NodeSource `setup_20.x` to `setup_22.x`, and
  the rebuilt image reports `node v22.23.1`, `Claude Code 2.1.205`, and
  `joysafeter-runner` present.
- A first live mock-adapter task smoke created a real agent/session/task from
  the API container, queued the task to Redis, and proved Rust scheduling,
  Docker sandbox creation, runner connection, and persisted `agent.tool_use`.
  It then exposed a real command-chain bug: `user.custom_tool_result` was
  persisted and ACKed by the Rust command listener, but the active task never
  completed because Rust only drained bridge control input while
  `requires_action_pending` was true.
- After adding non-HITL bridge input forwarding in `grpc/server.rs`, rebuilding
  `joysafeter-orchestrator-rs:latest`, and restarting only `orchestrator-rs`,
  the second live mock smoke completed. Evidence:
  session `019f4581-3cf0-7ff2-ac8b-7d62f7574f9f`, task
  `019f4581-3d20-7a52-b749-ff0ef1f2a2f5`, sandbox
  `019f4581-3d3a-7703-a62d-9cd1e0018777`; final task status `completed`;
  session status `idle`; stop reason `{"type":"end_turn"}`; task output
  starts with `MOCK_COMPLETED`.
- Persisted event sequence for the successful smoke:
  `user.message`, `session.status_running`, `agent.tool_use`,
  `user.custom_tool_result`, `agent.tool_result`, `agent.message`,
  final result `agent.message`, and `session.status_idle`.
- Orchestrator logs for the successful smoke show `Relayed input command`,
  then `Task result received status="completed"`, then `Task completed
  successfully`. Sandbox runner logs show `Received StartTask`, then
  `Task completed status=completed`.
- A project-scoped replay smoke then created session
  `019f4585-0580-7210-a02d-304fbe66746f`, task
  `019f4585-05a2-7732-96f9-18fa80b90e3c`, and sandbox
  `019f4585-05c0-7882-8fe3-46e5edd4ab23`. The task completed and the DB
  converged to session status `idle`, stop reason `{"type":"end_turn"}`, and
  event sequence:
  `user.message`, `session.status_running`, `agent.tool_use`,
  `user.custom_tool_result`, `session.status_running`, `agent.message`,
  `agent.tool_result`, `session.status_idle`.
- A temporary project API key was created and revoked after use. With
  `X-Api-Key`, `GET /api/v1/sessions/{session_id}/events?after_seq=0`
  returned the same eight event types in order, and
  `GET /api/v1/sessions/{session_id}/events/stream?after_seq=0` replayed the
  same eight event types with `_sse_source:"db_replay"` on every SSE event.
- Orchestrator game-day testing first used graceful
  `docker-compose ... stop orchestrator-rs` while task
  `019f458a-0e62-7a43-ab30-8dfffe3d80b5` was waiting after `agent.tool_use`.
  Graceful shutdown was not a crash simulation: the runner returned `aborted`,
  the task became terminal, and the lease fields were cleared. API readiness
  degraded to zero live orchestrators once the PG membership heartbeat expired,
  proving the readiness mirror catches a stopped Rust runtime.
- A hard-kill pass with task `019f458b-6e70-7ee1-a7fd-2c3bb699c558` exposed a
  recovery bug: after `SIGKILL` and restart, the new process reused stable
  `JOYSAFETER_INSTANCE_ID=orchestrator-rs-001` and renewed the stale running
  task lease even though it had not adopted a live bridge. This kept the task
  `running` until its task timeout instead of allowing lease reclaim.
- After changing lease renewal to process-active bridge tasks, a patched
  hard-kill pass used session `019f4598-8477-7240-b6f0-f286c7fa726c`, task
  `019f4598-8480-76a0-a1f2-591893fbb390`, sandbox
  `019f4598-84af-7c32-b285-67c9115d7596`. Rust restarted, recovered Envoy LDS
  for one live sandbox, and the sandbox runner reconnected with
  `is_reconnect=true`; Rust logged `Resuming reconnected active task with full
  event loop`, so subsequent lease renewal was tied to an adopted active bridge.
- The same reconnect drill found that `user.custom_tool_result` after reconnect
  was ACKed by the command listener and marked `processed_at`, but the mock
  runner did not complete. Cleanup used Redis cancel relay; final DB state was
  task `cancelled`, session `idle`, stop reason `{"type":"cancelled"}`, cleared
  `owner_instance_id`/`owner_epoch`/`lease_expires_at`, no active tasks, Redis
  stream `pending:0`, `lag:0`, and dead-letter length `0`.
- After fixing the runner surviving-task control channel and rebuilding
  `joysafeter-claudecode:latest`, a new hard-kill reconnect drill used session
  `019f45ae-ebc0-7030-83a3-107dd777f126`, task
  `019f45ae-ec30-7b31-a6cf-592820d59038`, and sandbox
  `019f45ae-ec66-7561-ba22-437c65cc69a6`. The task was killed while waiting
  after `agent.tool_use`; after `docker-compose ... kill -s SIGKILL
  orchestrator-rs` and `docker-compose ... up -d --no-build --force-recreate
  orchestrator-rs`, Rust logged `Runner connected is_reconnect=true` and
  `Resuming reconnected active task with full event loop`.
- The reconnected drill then sent `user.custom_tool_result` for `mock_call_1`.
  Rust logged `Relayed input command`, `Task result received
  status="completed"`, and `Reconnected task completed`. Final DB state:
  task `completed` with `owner_instance_id`, `owner_epoch`, and
  `lease_expires_at` cleared; session `idle`; stop reason
  `{"type":"end_turn"}`. Persisted events include `agent.message`,
  `agent.tool_result`, and `session.status_idle`, proving custom tool
  continuation after runner reconnect.
- Final post-drill health checks were clean: `/api/v1/health/ready` returned
  `status:"ok"` with `live_orchestrators:1` and `stale_orchestrators:0`;
  Redis Stream group `joysafeter-orchestrator-event-workers` reported
  `pending:0` and `lag:0`; `joysafeter:events:dead` length was `0`.
- The successful reconnect drill also produced two `session.status_idle`
  events with stop reason `{"type":"end_turn"}`. This did not affect terminal
  DB state or stream health, but it remains a consumer-facing event hygiene
  issue to resolve or explicitly accept.
- After changing idle status publishing to require an inserted atomic status
  event, `joysafeter-orchestrator-rs:latest` was rebuilt and `orchestrator-rs`
  was force-recreated from the new image. The Compose build again exported the
  image successfully and then hung after `#19 DONE`; the wrapper was
  interrupted after `naming to docker.io/library/joysafeter-orchestrator-rs:latest`
  and `unpacking ... done`.
- A follow-up idle de-duplication smoke used session
  `019f45bc-3cbd-70f3-a4b6-21b7dcee9594`, task
  `019f45bc-3d21-79f2-80ab-ea71a9946963`, and sandbox
  `019f45bc-3d4c-75e3-98f9-812adc39c7e7`. The task completed, owner/lease
  fields were cleared, session status was `idle`, stop reason was
  `{"type":"end_turn"}`, and persisted event counts showed exactly one
  `session.status_idle`.
- The same smoke still produced two `session.status_running` events: the
  initial task start and the API-side mark-running after live control input was
  accepted. This is lower-risk event noise than duplicate terminal idle state,
  but it remains a candidate for future event hygiene cleanup.
