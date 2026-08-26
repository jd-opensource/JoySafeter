# Envoy Network Policy Convergence Design

**Date:** 2026-08-26

**Status:** Implemented; live stress verification pending

**Builds on:** `docs/superpowers/specs/2026-08-23-mcp-runtime-plan-architecture.md`

## Goal

Make sandbox network-policy activation a single-writer, generation-fenced,
observable convergence protocol across scheduling, sandbox lifecycle, PostgreSQL,
the xDS authority, Envoy, and the runner.

The design must ensure that a policy which has been accepted and made usable by
Envoy cannot subsequently cause task scheduling to fail merely because another
concurrent caller completed the same work or observed an older generation.

## Incident Being Addressed

Task `task_01a03bc2-43a0-79c3-9591-8f2ae3a06f83` exhausted its two scheduling
retries on 2026-08-26. Each attempt created a sandbox, produced an initial
filesystem LDS rejection for an unknown cluster, successfully repaired the
listener and socket, marked network policy version 2 ready, and then destroyed
the sandbox while reporting `failed to setup Envoy networking for new sandbox`.

The three sandbox rows ended with the same contradictory state shape:

```text
status = destroyed
networking_status = ready
networking_policy_version = 2
```

This was not an MCP authentication failure. The bearer-authenticated MCP service
was reachable directly; the sandbox was torn down before Claude Code could use it.

## Root Cause

The failure is one convergence defect expressed through four cooperating races.

### Two policy identity functions

The create path computes `ExpectedFingerprint.egress_policy_hash` from logical
networking and credential routes. The reconcile path computes a second hash from
the rendered Envoy policy summary. The rendered summary contains sandbox-scoped
resource identifiers, including cluster names.

Consequences:

- equivalent logical policy receives a different hash in create and reconcile;
- each sandbox receives a different reconcile hash;
- reconcile advances the durable generation while the create path is still
  applying the previous generation;
- a successful foreground apply later fails its PostgreSQL ACK compare-and-set.

### Multiple xDS writers for one sandbox

The new-sandbox resolver directly calls `provider.refresh_networking`. The
degraded-policy loop can call the same provider concurrently after the runner
changes the sandbox lifecycle status. A per-sandbox Envoy apply mutex serializes
individual writes, but it does not establish one durable owner for the complete
prepare, apply, ACK, and cleanup transaction.

### Lifecycle state is advanced by the wrong boundary

Runner attachment currently changes every non-pooled sandbox from its current
state to `idle`. A runner can therefore move a sandbox from `creating` to `idle`
before networking provisioning finishes. The degraded-policy query includes
`idle`, so the background reconciler treats an actively provisioned sandbox as
abandoned work.

### Filesystem CDS and LDS are not one transaction

The filesystem backend writes `cds.json` and then `lds.json`, but Envoy watches
the files independently. Envoy can process LDS before the referenced cluster is
active and reject the listener with `unknown cluster`. Filesystem LDS has no ACK
channel; its `wait_for_sandbox_ack` operation currently returns success after the
write, leaving Unix-socket polling as the only acceptance signal.

## Architectural Ownership

The Rust orchestrator owns the complete network-policy convergence protocol.

- PostgreSQL owns desired and applied generation state.
- The runtime policy compiler owns semantic policy identity.
- The elected or local xDS authority is the only component allowed to mutate
  provider-local Envoy resources.
- Envoy owns enforcement and reports ACK/NACK or materialized socket readiness.
- The sandbox resolver owns creation orchestration, but not direct xDS mutation.
- The runner gRPC server owns bridge authentication and connection state, not
  sandbox lifecycle promotion.
- The sandbox controller owns reconciliation and terminal lifecycle cleanup, but
  cleanup must be fenced by current PostgreSQL state.

## Required Invariants

### One semantic revision

Every caller derives a `NetworkPolicyRevision` from the same canonical logical
policy representation.

The revision includes:

- effective network mode;
- normalized ordinary allowlist hosts;
- credential-route kind and exposure;
- canonical host, port, TLS, path mapping, and retry mode;
- vetted destination addresses in canonical sorted form;
- injected header names and SHA-256 value digests;
- headers removed before injection.

The revision excludes:

- sandbox ID;
- Envoy listener, cluster, socket, and resource names;
- the sandbox-local runner-to-Envoy proxy authentication token, which is
  generated once for a sandbox instance, remains immutable for that instance,
  and is applied when the semantic policy is rendered;
- database row IDs that do not affect enforcement;
- map or vector insertion order;
- plaintext secret values;
- timestamps, authority epochs, and retry counters.

Changing an enforcement-relevant input changes the revision. Rendering the same
logical policy for a different sandbox does not.

### Desired and applied state are distinct

The sandbox row must distinguish what should be active from what Envoy has
confirmed active.

The target durable model is:

```text
networking_policy_hash              NULLABLE
networking_policy_version           NOT NULL
networking_applied_hash             NULLABLE
networking_applied_version          NULLABLE
networking_status                   pending | applying | ready | nacked | failed
networking_last_error                NULLABLE
networking_ready_at                 NULLABLE
```

The existing `networking_policy_hash/version` columns are the canonical desired
generation. The applied columns record only the generation accepted by Envoy;
there is no dual-read alias or second desired-state naming scheme.

`ready` means:

```text
networking_applied_hash = networking_policy_hash
AND networking_applied_version = networking_policy_version
AND the current authority observed Envoy acceptance
AND the required per-sandbox socket is usable
```

### ACK is idempotent

Acknowledging a generation returns a typed result:

```rust
enum NetworkPolicyAckOutcome {
    Applied,
    AlreadyReady,
    Stale,
    Missing,
}
```

- `Applied`: the current pending/applying generation became ready.
- `AlreadyReady`: the same generation was already ready; this is success.
- `Stale`: a newer or different desired generation exists; the caller must not
  overwrite it or interpret its own completed provider operation as authoritative.
- `Missing`: the sandbox was deleted; the caller stops without recreating state.

A late NACK cannot replace `ready` for the same generation. A stale ACK or NACK
cannot mutate a newer generation.

### One xDS writer

All policy mutations use one command path:

```text
submit desired generation
        ↓
wakeup authority
        ↓
authority validates current generation and lifecycle
        ↓
authority renders and publishes CDS/LDS
        ↓
Envoy acceptance + socket readiness
        ↓
authority persists applied generation
```

The resolver, command listener, recovery loop, and degraded-policy loop may submit
or wait for work. They may not call the provider networking adapter independently.

Single-process Docker mode uses an in-process authority implementation with the
same command and repository contracts. Multi-replica mode continues to use Redis
as a wakeup mechanism and Kubernetes Lease fencing. Redis never owns policy state.

### Lifecycle ownership is explicit

Lifecycle transitions are owned as follows:

| Transition | Owner | Required guard |
|---|---|---|
| create row in `creating` | Resolver | provider resource created |
| runner disconnected/connected metadata | gRPC server | authenticated runner token |
| `creating → provisioning` | Resolver | desired network generation ready |
| `provisioning/idle → running` | Scheduler | runner ready, runtime current, network ready |
| `running → idle` | Task completion path | no active task |
| live → `stopping` | Lifecycle controller | external ID and ownership CAS |
| `stopping → stopped/destroyed` | Lifecycle controller | provider operation completed |

Runner attachment must not transition `creating` to `idle`. Bridge readiness is a
separate fact recorded through the bridge registry and connection metadata.

### Cleanup is fenced and monotonic

A caller that encounters an error must re-read the sandbox before teardown.

- If the requested generation is now ready and runtime freshness still holds,
  adopt the successful result.
- If a newer desired generation exists, return a freshness conflict and leave its
  resources to the current owner.
- If the sandbox is already stopping, stopped, or destroyed, cleanup is a no-op.
- Destructive cleanup begins only after a CAS to `stopping` that includes the
  expected external ID and lifecycle owner/generation.
- Envoy teardown is executed only by the xDS authority after revalidating the
  current PostgreSQL lifecycle and network mode.

No stale Future may remove resources belonging to a ready or newer generation.

## Policy Compilation Boundary

Introduce one application-level policy model that is independent of Envoy names:

```rust
pub struct DesiredNetworkPolicy {
    pub network_mode: EffectiveNetworkMode,
    pub allowlist_hosts: Vec<String>,
    pub credential_routes: Vec<DesiredCredentialRoute>,
}

impl DesiredNetworkPolicy {
    pub fn revision(&self) -> NetworkPolicyRevision;
    pub fn redacted_summary(&self) -> serde_json::Value;
    pub fn render_for(&self, sandbox_id: SandboxId) -> SandboxEgressPolicy;
}
```

`revision()` and `redacted_summary()` operate on canonical semantic data.
`render_for()` is the only step allowed to introduce sandbox-scoped listener,
cluster, and socket names.

The existing Envoy-facing `egress_policy_summary` remains useful for diagnostics,
but it must not define durable policy identity.

## Convergence State Machine

### Prepare desired policy

For a new semantic revision:

1. increment desired version;
2. store desired hash;
3. set status to `pending`;
4. preserve the last applied generation until a new ACK arrives;
5. publish a non-authoritative wakeup.

For the same semantic revision:

- if the same generation is ready in the current authority epoch, return
  `AlreadyReady` without changing status;
- if publication must be rebuilt after authority restart, keep the same desired
  generation and set it pending through an explicit recovery operation;
- ordinary duplicate callers do not demote `ready` to `pending`.

### Apply

The authority acquires its global application lock, then re-reads the sandbox.
It rejects stale generations before rendering. It publishes one complete policy,
waits for Envoy acceptance and socket readiness, verifies its authority epoch,
then persists the applied generation.

### Reconcile

The degraded-policy loop selects rows where desired and applied generations do not
match or status is `nacked/failed`. It does not invent a new desired revision from
rendered infrastructure state. If rebuilding logical inputs yields a different
semantic revision, it prepares that revision once and applies it through the same
authority path.

### Wait

The resolver waits on PostgreSQL for its exact desired generation. Completion is
successful when the exact generation is ready, including when another caller or
the authority completed it first. A newer generation produces a runtime freshness
decision, not an Envoy setup error.

## xDS Transport

### Supported path

Delta gRPC xDS is the normal dynamic configuration transport in every deployment,
including local Docker. It already provides:

- one versioned cluster/listener batch;
- clusters-before-listeners ordering;
- explicit ACK/NACK correlation;
- per-sandbox pending bookkeeping;
- reconnect recovery.

The default `JOYSAFETER_ENVOY_XDS_MODE` becomes `grpc`. Local deployment manifests
must set it explicitly during migration so behavior does not depend on an absent
environment variable.

### Filesystem compatibility mode

Filesystem mode remains an explicit compatibility/debug mode until removal. It
must not claim a real ACK. Its safe publication sequence is:

1. write CDS with a content-derived version;
2. query Envoy admin state until all referenced clusters are active;
3. write LDS with a content-derived version;
4. query Envoy admin state for listener acceptance;
5. verify the Unix socket;
6. return success only when all checks pass.

If Envoy admin verification is unavailable, credential routes requiring dedicated
clusters fail closed instead of relying on watcher ordering.

## Error Taxonomy and Observability

Errors must preserve the causal chain and be classified before reaching Scheduler:

- `policy_compile`: invalid or unsafe desired policy;
- `policy_stale`: desired generation changed;
- `xds_nack`: Envoy explicitly rejected a resource;
- `xds_timeout`: no ACK or admin acceptance before deadline;
- `socket_timeout`: accepted config did not create the socket;
- `ack_persistence`: Envoy succeeded but PostgreSQL persistence failed;
- `lifecycle_conflict`: cleanup or promotion lost its CAS;
- `provider_failure`: provider create/start/destroy failed.

Every application log includes sandbox ID, task ID when available, desired hash
prefix, desired version, authority epoch, transport, operation ID, and full error
chain. Secrets and complete credential-bearing policy JSON are never logged.

Metrics include:

- policy apply duration by result and xDS transport;
- NACK count by resource type and normalized reason;
- stale/duplicate ACK outcomes;
- desired-to-applied convergence lag;
- cleanup CAS conflicts;
- ready-to-destroy transitions, which should only occur through explicit lifecycle
  ownership and never as a side effect of stale policy completion.

## Failure Behavior

- Invalid policy fails before provider publication.
- NACK and timeout leave the sandbox fail-closed and non-executable.
- Authority loss leaves desired state durable and resumable by the next authority.
- Duplicate requests converge without generation churn.
- A stale caller never mutates applied state or performs teardown.
- PostgreSQL persistence failure after Envoy acceptance leaves the sandbox
  non-executable and schedules reconciliation; it does not report ready from local
  memory alone.
- Reconcile failure never destroys a live sandbox. Lifecycle cleanup remains a
  separate, fenced decision.

## Migration Strategy

1. Add characterization tests around the current incident before changing behavior.
2. Introduce the canonical semantic policy compiler and use it in create, refresh,
   recovery, and reconcile paths.
3. Add applied columns and backfill them from the canonical policy fields for
   rows currently marked ready.
4. Introduce typed prepare/ACK outcomes and make duplicate completion idempotent.
5. Route local creation through the existing xDS authority application path.
6. remove runner-owned lifecycle promotion and add guarded resolver/scheduler
   transitions.
7. fence cleanup and authority teardown against current lifecycle and generation.
8. make gRPC xDS the local default and harden the filesystem compatibility path.

The migration must be deployable without stopping existing sandboxes. Existing
`ready` rows are backfilled with applied equal to desired. Existing non-ready rows
retain a null applied generation and are reconciled by the active authority.

## Verification Strategy

### Unit tests

- semantic revision is identical across sandbox IDs and route insertion order;
- semantic revision changes for host, path, TLS, vetted address, header value,
  removal policy, retry mode, and allowlist changes;
- rendered Envoy names do not affect semantic revision;
- ACK outcome classification is exhaustive and idempotent;
- runner connection does not promote `creating` lifecycle state.

### PostgreSQL integration tests

- duplicate same-generation prepare does not demote an already-ready row;
- recovery can explicitly reopen the same generation after authority restart;
- duplicate ACK returns `AlreadyReady`;
- stale ACK/NACK cannot mutate a newer generation;
- cleanup CAS fails after another actor makes the requested generation ready;
- desired/applied backfill preserves existing ready and degraded rows.

### Deterministic concurrency tests

Use a barrier-controlled fake provider:

1. foreground submits generation and waits;
2. reconcile observes the same desired generation;
3. one apply completes first;
4. the second completion observes `AlreadyReady`;
5. no provider destroy or xDS teardown occurs;
6. the resolver returns the sandbox successfully.

A second test changes the semantic policy while the first apply is blocked and
verifies that the stale caller returns a freshness conflict without removing the
new generation.

### Real Envoy tests

- Delta gRPC batch publishes dedicated clusters before listeners and receives an
  ACK for the exact sandbox.
- Filesystem compatibility mode delays LDS until the cluster appears in Envoy
  admin state.
- An injected initial LDS rejection converges without task retry or sandbox
  destruction.
- socket readiness is required in addition to config acceptance.

### End-to-end MCP tests

- run no-auth, bearer, API-key-header, and custom-header MCP servers;
- create limited-networking Claude Code sessions through the public API;
- invoke a real MCP `ping` tool;
- assert one sandbox allocation, one stable desired generation, ready applied
  generation, no listener teardown, and correct upstream authentication;
- repeat bearer creation at least 20 times to exercise scheduling timing;
- restart the orchestrator/xDS authority and verify recovery without changing the
  semantic revision.

## Non-Goals

- Changing MCP credential ownership or plaintext-secret boundaries.
- Making Redis authoritative for networking state.
- Allowing a sandbox to execute while networking is pending or failed.
- Retrying non-idempotent MCP requests inside Envoy.
- Preserving filesystem xDS as an equally capable long-term transport.
- Refactoring unrelated task, event, credential, or typed-ID code.

## Acceptance Criteria

- Create, refresh, recovery, and reconcile compute the same semantic revision for
  the same logical policy.
- Exactly one authority path writes Envoy resources.
- Duplicate successful completion cannot fail scheduling.
- A ready or newer generation cannot be torn down by a stale caller.
- Runner attachment cannot make a creating sandbox eligible for background
  reconciliation.
- Local and production defaults use gRPC xDS.
- The authenticated MCP end-to-end matrix passes, including 20 consecutive bearer
  sandbox creations.
- Runtime logs contain no `unknown cluster` event on the supported gRPC path and no
  `ready → destroyed` transition caused by policy-generation conflict.
