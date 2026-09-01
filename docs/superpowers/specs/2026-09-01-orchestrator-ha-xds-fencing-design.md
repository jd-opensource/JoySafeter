# Orchestrator HA and xDS Authority Fencing

Date: 2026-09-01

## Scope

This design hardens the Kubernetes runtime for three active orchestrator replicas
with PostgreSQL-authoritative scheduling, Redis coordination, and one
Lease-elected xDS authority. It covers four failure boundaries:

1. xDS transport convergence after authority transfer.
2. Redis orchestrator instance-registry self-healing.
3. Exact runner-connection fencing before bridge-health destruction.
4. Separation of runtime deletion from residual socket cleanup.

PostgreSQL remains authoritative for durable sandbox and task state. Redis is
coordination state only. Kubernetes Lease state grants the sole xDS write
authority.

## Invariants

### xDS authority transport

- Every accepted xDS TCP connection is bound to one serving authority epoch.
- A connection is accepted only while the local authority is
  `RecoveryServing(epoch)` or `Ready(epoch)`.
- Revocation or any epoch change force-closes connections admitted under the old
  epoch, including their underlying HTTP/2 transport.
- Closing ADS response streams alone is insufficient because Envoy can create a
  new RPC on an existing HTTP/2 connection.
- Envoy limits xDS connection lifetime as defense in depth; the server-side
  epoch fence is the correctness mechanism.

### Redis instance registry

- One component owns the `joysafeter:instances:<instance_id>` record.
- Each heartbeat atomically writes the complete registration metadata and TTL.
- A deleted key or Redis restart is repaired by the next successful heartbeat.
- Initial registration failure in multi mode is fatal.
- The heartbeat loop is supervised as a critical runtime service.
- Graceful shutdown removes the instance key.

### Bridge generation fencing

- A local bridge is not sufficient proof of destructive ownership in multi
  mode.
- Destructive bridge-health recovery requires Redis to contain the exact
  `instance_id + connection_id` token for the observed bridge generation.
- Ownership is checked before durable recovery and again immediately before the
  provider side effect.
- Missing ownership, replacement ownership, or Redis failure fails closed.
- Local deployment modes retain process-local exact-generation checks.

### Runtime deletion and residual cleanup

- Provider destruction reports whether the runtime was deleted independently
  from residual cleanup status.
- Once Kubernetes confirms the Pod is absent, callers must never restore the DB
  row to a running or idle state because socket cleanup failed.
- Kubernetes records the Pod node before deletion, waits for disappearance, and
  targets the Envoy Pod on that node for socket cleanup.
- Residual cleanup failures are retryable and observable, but do not turn a
  completed runtime deletion into a runtime-destroy failure.
- A failure to delete the runtime remains an error and preserves the existing DB
  restore behavior.

## Ownership

| Boundary | Owner | Non-responsibilities |
|---|---|---|
| Authority epoch and connection admission | `src/xds/authority.rs`, `src/xds/transport.rs` | Lease acquisition and business policy material |
| Instance registration | `src/kernel/instance_registry.rs` | Task scheduling truth and bridge ownership |
| Exact bridge ownership | `src/kernel/ha/*` | Sandbox lifecycle transitions |
| Destruction outcome | `src/sandbox/provider.rs`, provider adapters | DB transitions |
| DB transition after destruction | sandbox lifecycle/controller application services | Provider-specific cleanup mechanics |

## Failure Semantics

### Authority transfer

1. Lease owner revokes authority.
2. Authority watch changes phase.
3. Transport closes every connection bound to the revoked epoch.
4. Envoy reconnects through the leader-selected Service.
5. The new authority admits a new connection after recovery serving begins.

If the new authority is not ready, connections are closed and retried; a
non-authority replica never serves ADS.

### Redis outage

The instance heartbeat logs and retries Redis connection failures. Because the
supervised task stays alive, it rewrites the complete key after Redis recovers.
Destructive bridge-health maintenance does not proceed while exact ownership
cannot be proven.

### Partial Kubernetes destruction

The provider returns a structured destruction outcome. `runtime_deleted=true`
allows the application layer to commit the sandbox's destroyed transition even
when residual cleanup is pending. `runtime_deleted=false` remains a destroy
failure and may restore the claimed DB state.

## Deployment Contract

- Multi mode defaults to three orchestrator replicas.
- Orchestrator Pods use required hostname anti-affinity when three or more
  schedulable nodes are available, plus topology spread with
  `ScheduleAnyway` to keep small development clusters deployable.
- The PodDisruptionBudget requires two available orchestrators in multi mode and
  one in single-instance modes.
- Envoy's xDS cluster sets a bounded maximum connection duration.

## Verification

### Automated tests

- Transport test: an authenticated channel admitted in epoch N becomes unusable
  after revoke, then a fresh channel succeeds in epoch N+1.
- Registry test: deleting the instance key is repaired with complete metadata
  and TTL by the next heartbeat.
- Bridge-store tests: old and foreign connection generations fail ownership
  checks; the exact current generation succeeds; Redis errors fail closed.
- Controller regression test: ownership replacement between the two fences
  prevents provider destruction.
- Provider/application tests: residual cleanup failure after confirmed deletion
  does not restore DB state; runtime deletion failure still does.
- Helm and deploy-script contract tests cover anti-affinity, PDB, xDS connection
  lifetime, and the failover verification command.

### Kubernetes fault injection

An explicit destructive verification mode must:

1. Identify and delete the current xDS authority Pod.
2. Wait for a different Lease holder, leader label, and Service endpoint.
3. Require one Ready authority and `active_envoy_nodes == ready Envoy Pods`.
4. Confirm authenticated streams reach the new authority.
5. Confirm the old authority-unavailable rejection counter no longer grows.
6. Delete an orchestrator instance key and require heartbeat self-healing.
7. Report all observed identities and counters for auditability.

The destructive mode is opt-in and must never run as part of ordinary
`k8s verify`.
