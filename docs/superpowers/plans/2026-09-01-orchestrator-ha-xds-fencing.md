# Orchestrator HA and xDS Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure one Lease-elected xDS writer can serve concurrent sandbox policy delivery without global head-of-line blocking, false NACK state, retry storms, or lifecycle state tearing.

**Architecture:** Keep PostgreSQL authoritative and serialize only xDS resource-world publication. Return typed delivery tickets from publication, settle them outside the global authority lock, persist typed exact-generation outcomes, and make task/session retry plus residual cleanup durable transactions.

**Tech Stack:** Rust, Tokio, SQLx/PostgreSQL, Redis Streams, Envoy Delta xDS, Kubernetes, Pytest deployment contracts.

**Spec:** `docs/superpowers/specs/2026-09-01-orchestrator-ha-xds-fencing-design.md`

## Global Constraints

- Three orchestrators remain active schedulers; exactly one Lease holder publishes xDS.
- PostgreSQL remains authoritative; Redis remains wakeup and coordination infrastructure.
- No network wait may hold the global authority publication lock.
- Every durable result is fenced by exact generation and, where applicable, authority epoch.
- Existing unrelated worktree changes must be preserved.

---

### Task 1: Split Publication From Settlement

**Files:** `kernel/network_policy/ports.rs`, `kernel/network_policy/application.rs`, `kernel/network_policy/authority.rs`, `sandbox/envoy/policy_runtime.rs`, `xds/authority_worker.rs`

**Interface:** Runtime publication returns a typed ticket; settlement consumes the ticket outside the authority lock.

- [ ] Add a failing concurrency test where sandbox A never ACKs and sandbox B still publishes.
- [ ] Run the focused test and confirm B is blocked by the current implementation.
- [ ] Introduce publication-ticket and settlement methods on the runtime port.
- [ ] Move delivery and socket waits outside the authority lock.
- [ ] Re-run focused concurrency and existing xDS tests.

### Task 2: Add Typed Policy Failures

**Files:** create `kernel/network_policy/error.rs`; modify `kernel/network_policy.rs`, `kernel/network_policy/application.rs`, `db/queries/network_policy.rs`; test `tests/network_policy_generation.rs`.

**Interface:** `NetworkPolicyApplyError` exposes a stable code, retry class, and persistence disposition.

- [ ] Add failing tests for NACK, timeout, authority loss, socket failure, and supersession mapping.
- [ ] Run the tests and verify current false-NACK behavior.
- [ ] Implement typed errors and exact-generation persistence mapping.
- [ ] Surface failure-persistence errors instead of ignoring them.
- [ ] Re-run network-policy generation and service tests.

### Task 3: Bound Reconciliation Retries

**Files:** `kernel/network_policy/reconciler.rs`, `db/queries/sandbox.rs`, `joysafeter_domain/models/joysafeter_sandbox.py`, new Alembic migration.

**Interface:** Durable attempt count, next retry time, and stable failure code determine eligibility.

- [ ] Add failing repository tests for retry eligibility and successful-repair counting.
- [ ] Run tests and verify current two-second hot-loop behavior.
- [ ] Add retry metadata migration and model fields.
- [ ] Implement typed retry scheduling and reconciler accounting.
- [ ] Re-run migration, repository, and reconciler tests.

### Task 4: Make Retry State Atomic

**Files:** `db/queries/task.rs`, `kernel/scheduler.rs`, `kernel/task_controller.rs`, `kernel/runner/task_lifecycle.rs`, `kernel/runner/cleanup.rs`.

**Interface:** One repository transaction updates task retry state, session state, and replayable event.

- [ ] Add failing PostgreSQL tests with injected rollback between transition stages.
- [ ] Run tests and confirm partial state is observable today.
- [ ] Implement one expected-state-fenced repository transaction.
- [ ] Replace duplicated retry/session/event sequences with the transaction.
- [ ] Re-run scheduler, controller, and runner lifecycle tests.

### Task 5: Persist Residual Cleanup

**Files:** `sandbox/provider.rs`, `kernel/sandbox_lifecycle.rs`, `sandbox/k8s.rs`, new cleanup-work migration, Envoy DaemonSet.

**Interface:** Provider absence and pending deletion remain typed; residual cleanup is durable node-scoped work.

- [ ] Add failing lifecycle tests for pending deletion, typed absence, and residual work persistence.
- [ ] Run tests and confirm string matching and dropped residual work.
- [ ] Implement cleanup-work persistence and bounded retry worker.
- [ ] Add safe legacy ownership detection/repair deployment behavior.
- [ ] Re-run lifecycle, migration, Helm, and deployment contract tests.

### Task 6: Bound Authority Work And Recovery

**Files:** `xds/authority_worker.rs`, `sandbox/envoy/policy_runtime.rs`, `xds/delivery.rs`, `xds/delta.rs`.

**Interface:** Foreground work is bounded/coalesced; maintenance tasks are structurally owned; recovery uses one deadline.

- [ ] Add failing tests for coalescing, child cancellation, shared recovery deadline, and prune NACK telemetry.
- [ ] Run tests and confirm current unbounded, detached, and sequential behavior.
- [ ] Implement bounded authority work and structured child ownership.
- [ ] Settle recovery deliveries concurrently under one deadline.
- [ ] Re-run all xDS unit and integration tests.

### Task 7: Verify The Complete Contract

**Files:** `docs/ARCHITECTURE.md`, architecture/deployment contract tests.

- [ ] Run Rust unit and focused integration tests.
- [ ] Run DB-backed tests with `JOYSAFETER_TEST_DATABASE_URL` when available.
- [ ] Run Python architecture and migration tests from `backend/`.
- [ ] Run `cargo fmt --check`, `cargo check --all-targets`, Helm lint, and `git diff --check`.
- [ ] Run Kubernetes failover and legacy socket-permission fault injection when a cluster is available.
