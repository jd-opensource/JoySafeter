# Orchestrator HA and xDS Authority Fencing

Date: 2026-09-01

## Scope

This design hardens the Kubernetes runtime for three active orchestrator replicas
with PostgreSQL-authoritative scheduling, Redis coordination, and one
Lease-elected xDS authority. It covers seven failure boundaries:

1. xDS transport convergence after authority transfer.
2. Redis orchestrator instance-registry self-healing.
3. Exact runner-connection fencing before bridge-health destruction.
4. Separation of runtime deletion from residual socket cleanup.
5. Separation of serialized xDS publication from concurrent delivery settlement.
6. Typed network-policy failures and durable retry scheduling.
7. Atomic task, session, and replayable-event retry transitions.

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

### Inventory maintenance isolation

- Periodic stale-resource pruning shares the authority application lock with
  foreground mutations so an older PostgreSQL inventory snapshot cannot remove
  a policy published by a newer foreground request.
- The prune critical section performs only PostgreSQL inventory validation and
  local xDS resource-world publication; it never waits on Envoy network
  responses while holding the authority application lock.
- Pruning publishes removals and immediately retires their delivery tracking;
  removal ACK is not a correctness precondition because the authoritative
  snapshot no longer contains the resource.
- A disconnected Envoy converges when it reconnects and receives the current
  authoritative snapshot.
- A failed prune attempt is rate-limited by the normal reconciliation interval
  and cannot create a hot retry loop.
- Failure of one stale entry does not prevent attempts for the remaining stale
  inventory.
- Foreground policy failures retain their original cause even when asynchronous
  runtime cleanup is still pending.

### Foreground publication and delivery

- The authority application lock serializes only mutation of the authoritative
  xDS resource world. It is never held while waiting for an Envoy ACK, socket
  creation, or PostgreSQL persistence.
- Policy preparation may happen outside the authority lock. Immediately before
  publication, the authority revalidates both the Lease epoch and the exact
  PostgreSQL policy generation.
- Publication returns a delivery ticket. Delivery settlement is concurrent
  across sandboxes and remains fenced by authority epoch, policy generation, and
  delivery attempt identity.
- A later generation may supersede an older in-flight ticket. The older ticket
  is reported as superseded and cannot overwrite the newer PostgreSQL generation.
- Request fan-in is bounded and coalesced by sandbox and generation. A slow Envoy
  cannot create an unbounded set of Tokio tasks waiting on one global mutex.

### Network-policy failure semantics

- Network-policy application failures are typed at the runtime/application
  boundary. Error strings are diagnostic data, never control-flow inputs.
- Only an explicit Envoy rejection is persisted as `nacked` and may populate
  `last_nack_reason`.
- Invalid rendered policy is terminal for the current generation and is
  persisted as `failed`.
- Delivery timeout, authority loss, publication unavailability, and socket
  readiness failures are retryable delivery failures with a stable error code
  and durable next-attempt time.
- Generation supersession is not a policy failure and performs no failure write.
- Failure persistence is part of the operation result; a database write failure
  is surfaced and observed rather than discarded.
- Explicit NACK waits for a new generation or operator action. Retryable failures
  use bounded exponential backoff with jitter.

### Task/session retry transition

- Retrying a task is one PostgreSQL transaction containing the task CAS, retry
  metadata, session `rescheduling` transition, and replayable status event.
- The transition locks the session event sequence and validates the task's
  expected status, retry count, and owner epoch where applicable.
- Redis enqueue happens only after commit. A failed enqueue is repaired by the DB
  pending-task scanner and never rolls back durable scheduling truth.
- Rescheduling stop reasons carry stable, sanitized fields: `type`, `code`,
  `retryable`, `attempt`, `max_attempts`, and `source`.

### Durable residual cleanup

- Once the provider runtime is confirmed absent, the sandbox may be finalized as
  destroyed even if node-local socket cleanup fails.
- Every residual cleanup failure is persisted as cleanup work with sandbox, node,
  resource path, attempt count, next retry time, and sanitized last error.
- A node-scoped cleanup worker retries with bounded backoff. Successful cleanup
  completes the work idempotently.
- Kubernetes provider absence is represented by a typed provider outcome; callers
  do not infer absence by searching error text for `404` or provider messages.
- Deployment preflight verifies the socket root and detects incompatible legacy
  child ownership. Legacy repair changes ownership safely without deleting active
  sandbox sockets.

## Ownership

| Boundary | Owner | Non-responsibilities |
|---|---|---|
| Authority epoch and connection admission | `src/xds/authority.rs`, `src/xds/transport.rs` | Lease acquisition and business policy material |
| Instance registration | `src/kernel/instance_registry.rs` | Task scheduling truth and bridge ownership |
| Exact bridge ownership | `src/kernel/ha/*` | Sandbox lifecycle transitions |
| Destruction outcome | `src/sandbox/provider.rs`, provider adapters | DB transitions |
| DB transition after destruction | sandbox lifecycle/controller application services | Provider-specific cleanup mechanics |
| xDS resource-world publication | authority worker and network-policy application | Envoy ACK wait and socket readiness |
| Delivery settlement | network-policy runtime/application | Global authority serialization |
| Policy retry classification | network-policy application state machine | Scheduler string parsing |
| Task/session retry transaction | task repository application boundary | Redis wakeup delivery |
| Residual cleanup work | sandbox lifecycle and cleanup repository | Provider runtime deletion truth |

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

### Policy delivery failure

An explicit Envoy NACK terminates the current generation until policy material
changes. A transient delivery or socket failure remains retryable with durable
backoff. Authority transfer supersedes old-epoch delivery tickets without writing
a false NACK. PostgreSQL compare-and-set transitions prevent late results from
overwriting a newer generation.

### Retry transaction failure

Failure before commit leaves task, session, and event unchanged. Failure after
commit but before Redis enqueue leaves a durable pending task that the DB scanner
will enqueue. There is no supported state where a session is `rescheduling` while
its task remains permanently `scheduling` because of a partially completed retry.

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
- Concurrency test: a sandbox whose delivery never settles does not delay another
  sandbox's resource-world publication.
- Failure-mapping tests: only Envoy rejection becomes `nacked`; timeout, authority
  loss, socket failure, invalid material, and supersession retain distinct codes.
- Reconciler tests: persistent NACK is not retried every two seconds; transient
  failures honor durable backoff.
- Repository integration test: task retry, session status, and status event commit
  atomically, including injected failure rollback.
- Lifecycle test: residual socket cleanup creates durable retry work after runtime
  deletion and never restores the sandbox to a live state.
- Worker lifecycle test: cancelling the authority worker aborts all owned
  maintenance children.
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
