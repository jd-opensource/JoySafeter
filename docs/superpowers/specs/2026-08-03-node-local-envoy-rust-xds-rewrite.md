# Node-local Envoy + Rust xDS Control Plane Rewrite

- **Date:** 2026-08-03
- **Status:** Implemented; Rust is the deployment default, live production cutover verification required
- **Scope:** Sandbox egress data plane, Rust xDS control plane, Docker/Kubernetes deployment topology

## Decision

Every sandbox execution host has a local Envoy egress data plane. Kubernetes
uses one Envoy Pod per eligible node; Docker uses one Envoy container per host.
The Envoy instance makes allow/deny decisions locally from versioned xDS policy.
Normal sandbox traffic never traverses the orchestrator or xDS server.

The Rust orchestrator and xDS server run in the same process. Production runs
multiple identical replicas but exactly one replica is active at a time; all
other replicas are cold standbys. A PostgreSQL session advisory lock is the
single-active authority. A standby does not schedule tasks or serve ADS until it
acquires leadership. Envoy now targets the embedded Rust ADS server by default;
the temporary Go controller is absent from the base deployment and retained only
as an explicit emergency rollback asset during the first production cutover.

## Required topology

```text
Sandbox Pod/container
        |
        | only permitted egress target
        v
Node-local Envoy  --------------------> approved upstream
        ^
        | mTLS Delta ADS
        |
Active Rust orchestrator+xDS process <----> PostgreSQL durable authority
        ^
        |
Cold standby Rust replicas
```

Kubernetes sandbox egress remains default-deny at L3/L4. Network policy or CNI
enforcement must permit only the node-local Envoy path and explicitly required
platform services. Proxy environment variables alone are not a security
boundary because a sandbox process could open a direct socket.

## Local Envoy responsibilities

Each Envoy independently enforces:

- destination hostname, CIDR, port, and protocol allowlists;
- HTTP host, path-prefix, and method restrictions where applicable;
- default-deny fallback routes;
- sandbox identity and policy-generation binding;
- request-header removal and approved route rewrites;
- connection, timeout, circuit-breaker, and overload limits;
- local access logs, response flags, and deny reason metrics.

The request path must not synchronously call the orchestrator for ordinary
allowlist decisions. Dynamic credential resolution may remain a separate,
minimal capability until short-lived locally verifiable credentials replace it.
Real provider secrets must not be embedded in xDS snapshots.

## Node identity and policy isolation

Every Envoy ADS stream supplies a non-empty `node.id` and the following
normalized metadata:

- `deployment_id`
- `environment`
- `region`
- `provider`
- `shard_id`
- `envoy_version`
- `config_schema_version`
- `host_id` for Docker and node-local deployments

The compatibility shared-data-plane mode derives a deterministic
`v1:<sha256>` group key without `host_id`. Node-local mode requires `host_id`
and derives a deterministic `v2:<sha256>` group key. A stream is permanently
bound to one node identity and group. A stream that changes identity or has
incomplete metadata is rejected. Resources from one group must never be
delivered to another group.

For node-local Envoy, `host_id` is the Kubernetes node UID/name or Docker host
identity. The policy compiler publishes only policies assigned to that host.

## HA and durable-state contract

- PostgreSQL desired generations are authoritative.
- All Rust xDS replicas reconstruct deterministic snapshots from durable state.
- Snapshot versions are content-derived or generation-derived, never local
  process counters in production mode.
- ACK/NACK records include group, node, type URL, version, nonce, and sanitized
  reason.
- A generation becomes applied only after every required resource type is ACKed
  by the ready connected nodes in its group.
- NACK restores the durable last-known-good generation and marks the candidate
  failed.
- Existing Envoy traffic continues with last-known-good configuration during
  control-plane loss. New or changed sandbox policy remains blocked until its
  generation is applied.
- Startup and periodic reconciliation repair missed notifications, stale node
  leases, and orphaned snapshots.

## Single-active process model

Every replica runs the same `joysafeter-orchestrator` binary. Before starting
the task scheduler, sandbox controllers, runner gRPC service, credential
service, or ADS service, it attempts to acquire a dedicated PostgreSQL advisory
lock on a dedicated database connection.

- The lock holder starts the complete orchestrator+xDS control plane.
- Non-holders remain cold, expose process readiness/liveness, and retry
  leadership acquisition so Deployment and PDB accounting remain healthy.
- Only the lock holder patches `joysafeter.io/control-plane-active=true`; the
  runner/ADS Service selects that label and excludes cold standbys.
- The active replica continuously probes the lock connection. A connection
  failure or probe timeout clears the active label and cancels the active runtime.
- Active shutdown drops the dedicated connection, releasing leadership.
- A cold standby acquires the lock, reconstructs state from PostgreSQL, starts
  gRPC/ADS, and becomes ready.

Envoy retains its last-known-good configuration while the active process fails
over. Existing allowed traffic therefore continues locally; new policy changes
remain blocked until the replacement active process reconciles and receives
ACKs.

## Migration phases

1. Add PostgreSQL single-active leadership and cold-standby readiness behavior.
2. Introduce Rust node identity validation and group-isolated snapshot state.
3. Add deterministic policy compilation and local Envoy RBAC/route enforcement.
4. Add durable PostgreSQL reconciliation, ACK/NACK, apply status, and rollback.
5. Convert Kubernetes Envoy from a shared Deployment to a node-local DaemonSet
   and prove the non-bypass network path.
6. Compare the Go and Rust compilers against identical policy fixtures.
7. Switch the default Envoy ADS target directly to the active Rust process.
8. Keep Go only as an explicit emergency rollback until live leader-failover,
   NACK, database-outage, node-loss, and control-plane-restart drills pass.

## Implemented cutover gate

The embedded Rust Delta ADS implementation now provides:

- strict node/group binding;
- per-group resource isolation;
- subscription-aware Delta responses;
- durable deterministic versions;
- ACK quorum and NACK rollback;
- restart reconstruction;
- metrics and bounded diagnostics;
- real Envoy and multi-replica integration coverage.

## Go controller removal and Rust superiority gate

The embedded Rust control plane exceeds the temporary Go controller in deployment
simplicity, node isolation, durable failure recovery, security, and diagnostics.
The Go controller is no longer part of the default deployment.

### Current completed foundation

- Rust orchestrator and xDS share one process lifecycle.
- PostgreSQL session advisory locking permits exactly one active control-plane
  process; other replicas remain cold standbys.
- Active leadership loss revokes the Service-routing label and stops the full kernel.
- Delta ADS binds each stream to one immutable node identity and isolates state
  by deterministic group key.
- Kubernetes Envoy runs as a node-local DaemonSet and the sandbox-facing Service
  uses `internalTrafficPolicy: Local`.
- Every Kubernetes Envoy advertises both a unique Pod `node.id` and node-bound
  `host_id`; Rust v2 publication uses that identity for node-local groups.

### Implemented cutover capabilities

1. **Dedicated mTLS xDS listener in the orchestrator process.** ADS must not use
   the plaintext runner gRPC listener. The Rust process must expose a separate
   xDS port with client-CA verification, exact Envoy DNS SAN validation, TLS 1.3,
   keepalive, message limits, and bounded concurrent streams.
2. **Rust production policy compiler.** Decode the durable policy schema with
   strict unknown-field and secret-bearing-field rejection; produce deterministic
   LDS, RDS, and CDS resources equivalent to or stricter than the Go compiler.
3. **Durable deterministic snapshots.** Versions must derive from generation and
   deterministic protobuf bytes. Process-local counters are forbidden in
   production mode.
4. **PostgreSQL reconstruction and reconciliation.** Restore the newest applied
   last-known-good generation on startup, consume generation notifications, and
   retain periodic full reconciliation as the missed-notification fallback.
5. **Subscription-aware Delta ADS.** Respect subscribe/unsubscribe sets and
   initial resource versions; do not push unrelated full resource sets.
6. **Durable ACK/NACK state machine.** Correlate nonce, type URL, version, group,
   and node; persist sanitized NACK reasons; require ACKs only for changed types;
   compute quorum across leased connected nodes; reject replay of failed
   versions; and roll back immediately to durable last-known-good.
7. **Node-local v2 publication.** Compile and publish a separate `v2` group for
   each eligible execution node/host, with explicit policy assignment and no
   cross-host resource delivery.
8. **Leader-aware Kubernetes routing and rollout.** Cold standbys must remain
   healthy for Deployment/PDB accounting while only the PostgreSQL lock holder
   is selected by the runner/xDS Service. Active-only Pod readiness alone is not
   sufficient because it makes multi-replica rolling updates stall.
9. **Operational superiority.** Export bounded-cardinality metrics for streams,
   connected/leased nodes, publish/restore/rollback outcomes, ACK/NACKs,
   reconciliation lag, snapshot bytes, and active leadership. Add bounded
   diagnostic endpoints that never expose credentials or raw policy secrets.

### Mandatory removal tests

- Canonical Go/Rust compiler comparison produces identical or intentionally
  stricter resources for every policy fixture.
- Real Envoy accepts Rust LDS/RDS/CDS for Docker and Kubernetes node-local modes.
- Two or more Rust replicas prove single-active mutual exclusion and automatic
  takeover after process kill, database connection loss, and node drain.
- Restart reconstructs last-known-good before ADS readiness.
- Concurrent ACKs cannot lose updates; disconnected or expired nodes recompute
  quorum correctly.
- Every NACK persists a sanitized reason and restores last-known-good without
  interrupting existing Envoy traffic.
- PostgreSQL LISTEN loss, notification loss, database outage, and recovery
  converge through periodic reconciliation.
- Node A never receives Node B resources, including reconnect and stale-version
  cases.
- Production-sized policy, node, and reconnect load stays within explicit CPU,
  memory, snapshot-size, and convergence-time budgets.
- The direct cutover script requires connected Envoy nodes and healthy Rust xDS
  metrics before scaling any pre-existing Go controller Deployment to zero.

### Removal decision

The default deployment, build smoke, and architecture guards no longer depend on
Go. Delete the remaining rollback manifest, PKI identity, and Go source tree
after the first real production cutover passes policy, NACK rollback, restart,
and leadership-handoff drills and the emergency rollback procedure is verified.
