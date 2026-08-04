# Egress Controller `apply_status` Concurrency Correctness (B1)

> **Historical / superseded (2026-08-04):** This design applies to the deleted
> Go publisher. Rust now owns canonical connection, ACK/NACK, generation, and
> aggregate apply-state transitions.

- **Date:** 2026-08-03
- **Scope:** `egress-controller` (Go) apply-status aggregation only. No schema change, no orchestrator (Rust) change.
- **Status:** Design approved, pending spec review.
- **Supersedes / relates to:** builds on `2026-08-01-unified-egress-provider-parity-and-e2e-verification.md`. Fixes a correctness gap introduced with the multi-replica durable apply-status writeback (`e5f56d55` added monotonic guards but not concurrency safety).

## Problem

The unified Envoy egress control plane runs the Go `egress-controller` at N replicas (k8s Deployment `27-egress-envoy.yaml` / `25-egress-controller.yaml`, replicas 3, HPA up to 12). Each Envoy node connects to exactly **one** controller replica; that replica records the node's connection and per-resource ACK/NACK, and recomputes the shared aggregate row in `joysafeter_egress_apply_status`.

The Rust orchestrator's `PostgresEgressPolicyAuthority::wait_applied` (`backend/app/joysafeter_orchestrator_rs/src/egress/authority.rs:531`) blocks on that aggregate reaching `state = 'applied'` before a sandbox's egress policy is considered live. If the aggregate is wrong or stuck, `wait_applied` times out (`EGRESS_POLICY_APPLY_TIMEOUT`) and sandbox egress setup fails. **This directly blocks the production egress cutover** (`JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED`).

### Root cause 1 — lost update under concurrent ACKs

`writeACK` (`egress-controller/internal/status/postgres.go:290-383`) runs, in one transaction:

1. `INSERT` the node's ACK into `joysafeter_egress_node_apply_status`.
2. `UPDATE joysafeter_egress_apply_status ... FROM (counts CTE)` where the CTE counts active nodes and their ACKed rows **globally** (across all controllers).

Two ACKs for different nodes of the same `(group_key, generation)`, processed concurrently by two replicas, race:

- Under `READ COMMITTED`, each transaction's `counts` CTE cannot see the *other* transaction's uncommitted `node_apply_status` INSERT.
- Both compute an aggregate that omits the peer's ACK. The last transaction to commit overwrites `acked_acks` with its own partial view — the peer's ACK is dropped from the aggregate.
- If those were the last two required ACKs, the aggregate stays `acked_acks < required_acks` → **`state` stuck at `published` forever** (nothing recomputes it later; see root cause 2). `wait_applied` times out.

The monotonic guards from `e5f56d55` prevent `applied → published` regression but do **not** prevent the stuck-at-`published` liveness failure.

### Root cause 2 — recompute triggers are insufficient

The aggregate is recomputed **only on ACK**. Specifically:

- `writeConnected` (`postgres.go:262-279`) upserts `node_connections` but does not recompute — a newly required node is not reflected until it happens to ACK.
- `writeDisconnected` (`postgres.go:281-288`) marks the connection gone but does not recompute — a `published` generation whose last blocking node just disconnected is never re-evaluated to `applied`.
- Lease expiry (`lease_expires_at`) silently changes the active-node set with no recompute.
- There is no periodic safety net.

## Goals & invariants

For any N concurrently-running controller replicas:

1. **Accuracy** — `connected_nodes / required_acks / acked_acks` eventually reflect the true global active-node ACK state, with no lost updates.
2. **Liveness** — once the global active-node set has ACKed all required type-URLs for a generation, `state` becomes `applied` within a bounded time.
3. **Monotonicity / fail-closed** — `applied` does not regress under concurrent recompute; NACK drives `failed` (preserved from current behavior).
4. **No new HA failure mode** — all replicas stay active; no leader election, no failover, no split-brain.

## Design

### (a) Canonical, self-contained, idempotent recompute

Extract the inline aggregate SQL from `writeACK` into `recomputeApplyStatus(ctx, tx, groupKey string, generation uint64) error` with two changes vs. today:

- **Self-contained `xds_version`** — count ACKs with `node_status.xds_version = apply_status.xds_version` (read from the target row) instead of a caller-supplied version. This lets *any* trigger call it knowing only `(group_key, generation)`, and it naturally ignores stale-version ACKs.
- **Recompute range** — `WHERE apply_status.state IN ('pending','published')`. Terminal states (`applied`, `failed`, `superseded`) are never rewritten, preserving monotonicity by construction.

Semantics otherwise identical to the current CTE: `connected_nodes` = active nodes for the group (`disconnected_at IS NULL AND lease_expires_at > now()`); `required_acks = connected_nodes * jsonb_array_length(required_type_urls)`; `acked_acks` = ACKed `(node, type_url)` rows among active nodes matching the row's version; transition to `applied` when `connected_nodes > 0 AND acked_acks >= required_acks`.

### (b) advisory-lock serialization

Add `withGenerationLock(ctx, tx, groupKey, generation, fn)` that executes, **before** the recompute UPDATE:

```sql
SELECT pg_advisory_xact_lock(hashtextextended($1, 0))  -- $1 = group_key || ':' || generation
```

This mirrors the orchestrator's existing `lock_group` (`authority.rs:852-861`). Because the lock is acquired *before* the `counts` snapshot is taken, a blocked transaction waits until the prior holder commits (making its `node_apply_status` INSERT visible) and only then takes a fresh statement snapshot.

**Correctness argument (induction over serialized recomputes):** advisory-xact locks serialize all recomputes for a given `(group, generation)` across every replica and connection. To run a recompute you must hold the lock; to hold it the previous holder must have committed (releasing the lock also commits its same-transaction `node_apply_status` INSERT). Therefore every recompute sees all previously-committed ACKs plus its own — and the globally-last recompute sees the entire committed ACK set. The lock is transaction-scoped, released on commit.

Note: the `node_apply_status` INSERT itself is **not** under the lock (different-node INSERTs never conflict); only the aggregate UPDATE is serialized, which is exactly the contended resource.

### (c) Trigger points

| Trigger | Action |
|---|---|
| ACK | Existing tx: INSERT `node_apply_status` → `withGenerationLock` → `recomputeApplyStatus` |
| NACK | Also inside the lock (serialize `failed`/`applied` so state never tears); NACK→`failed` semantics unchanged |
| connect / disconnect | After the `node_connections` write, recompute every non-terminal generation of that group, each in its own short locked tx (`recomputeGroupNonTerminal`) |
| **periodic ticker** | Background loop every `RecomputeInterval`: recompute all rows in `state IN ('pending','published')`, each under its lock — the ultimate backstop for lease expiry / missed events |

Because each recompute is idempotent, locked, and monotonic, **all replicas may run the ticker concurrently without coordination** (they serialize per row). This fulfills the "periodic recompute" requirement with no leader.

### (d) Lease-expiry liveness

`connected_nodes` already filters on `lease_expires_at > now()`, but only re-evaluates when a recompute runs. The periodic ticker (c) is what makes lease expiry actually converge: a dead controller's nodes drop out of `active_nodes` and `required_acks` shrinks accordingly within `RecomputeInterval`. (Nodes also reconnect to a live replica, firing `connect` recomputes.)

## Code changes (small, focused units)

- `egress-controller/internal/status/recompute.go` (new): `recomputeApplyStatus`, `withGenerationLock`, `recomputeGroupNonTerminal`.
- `egress-controller/internal/status/postgres.go`: `writeACK` calls the helper instead of inline SQL; `writeConnected` / `writeDisconnected` append a group recompute; `run()` ticker loop (`:141-161`) gains a recompute tick (reuse or parallel to the heartbeat ticker).
- `egress-controller/internal/config/config.go`: add `RecomputeInterval` (default 15s), env `JOYSAFETER_EGRESS_CONTROLLER_RECOMPUTE_INTERVAL`.
- `egress-controller/internal/telemetry/metrics.go`: recompute count by trigger label, advisory-lock wait duration, `published`-dwell gauge.

**No Alembic migration; no orchestrator change.** Pure controller-side correctness fix, default-on (the overall egress feature remains gated upstream by `JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED`).

## Testing

- `egress-controller/internal/status/postgres_concurrency_integration_test.go` (new, real Postgres, following the existing `*_integration_test.go` pattern): K nodes, M concurrent goroutines recording ACKs via independent transactions, repeated over several rounds; assert final `acked_acks == required_acks && state == 'applied'` with zero lost updates.
- **Adversarial control:** a test-only path that disables the advisory lock and asserts it can reproduce the undercount — proving the lock is the load-bearing fix.
- Unit / integration: disconnect unblocks a `published`→`applied` transition; an expired lease is reconciled by the ticker; a NACK after a partial ACK set does not spuriously leave `applied`; ticker convergence for a generation that received no ACK-triggered recompute.

## Non-goals (explicitly excluded)

- Leader election / sharded ownership of writes.
- B2 transactional outbox consumer (`joysafeter_egress_outbox_events` unbounded growth + delivery accounting) — separate future spec.
- Native Kubernetes client replacing `kubectl` shell-out.
- Production PKI (cert-manager / SPIRE).

## Open decision (recommendation baked in)

The periodic ticker runs on **all replicas** (recommended: idempotent + locked ⇒ safe; add random jitter to spread DB load), rather than electing a single ticker owner. Electing an owner would reintroduce the leader/failover complexity this design deliberately avoids. Revisit only if DB load from redundant ticks proves material.
