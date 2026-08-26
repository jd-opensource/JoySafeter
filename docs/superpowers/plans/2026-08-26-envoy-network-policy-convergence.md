# Envoy Network Policy Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace competing sandbox-networking writers with one durable, generation-fenced convergence path that cannot destroy an Envoy-ready sandbox after a concurrent successful apply.

**Architecture:** PostgreSQL stores separate desired and applied policy generations. One canonical semantic compiler produces a sandbox-independent revision, while the xDS authority alone renders and publishes sandbox-specific Envoy resources. Resolver, recovery, refresh, and degraded reconciliation submit or wait for generations instead of independently mutating Envoy.

**Tech Stack:** Rust, Tokio, SQLx, PostgreSQL, Redis wakeups, Kubernetes Lease authority, Envoy Delta gRPC xDS, Docker, Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-envoy-network-policy-convergence-design.md`

## Global Constraints

- Preserve unrelated uncommitted typed-ID, credential, frontend, and documentation changes.
- PostgreSQL remains authoritative; Redis remains wakeup and coordination infrastructure only.
- Envoy and the orchestrator remain fail-closed for pending, NACKed, stale, or unverified policy state.
- Plaintext credentials may reach only the credential material boundary and Envoy rendering path; logs and persisted summaries contain digests only.
- No stale operation may remove or overwrite a ready or newer policy generation.
- Run backend pytest commands from `backend/`.
- Do not commit changes unless explicitly requested.
- Establish a compilable Rust baseline before interpreting test failures in the target subsystem.

---

### Task 1: Add Incident Characterization Tests

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/network_policy_generation.rs`

**Interfaces:**
- Consumes the current `egress_policy_hash`, rendered `egress_policy_summary`, lifecycle transitions, and generation repository functions.
- Produces failing tests that reproduce semantic-hash divergence, premature `creating → idle`, duplicate completion failure, and stale cleanup risk.

- [ ] **Step 1: Restore a compilable target-test baseline**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline --lib --no-run
```

Expected: compilation succeeds. If unrelated current-worktree errors remain, record them and coordinate their resolution without changing network-policy behavior in this task.

- [ ] **Step 2: Add a failing semantic identity test**

Add a unit test beside the resolver policy-hash tests that builds equivalent credential routes for two `SandboxId` values, renders each policy, and proves the desired behavior:

```rust
let create_hash = egress_policy_hash(networking.as_ref(), &credentials);
let first_policy = credentials
    .clone()
    .to_policy(&first_sandbox, allowed_hosts.clone());
let first_reconcile_hash = network_policy_hash(
    networking.as_ref(),
    &crate::sandbox::lds_backend::egress_policy_summary(
        &first_sandbox,
        &first_policy,
    ),
);
let second_policy = credentials
    .clone()
    .to_policy(&second_sandbox, allowed_hosts);
let second_reconcile_hash = network_policy_hash(
    networking.as_ref(),
    &crate::sandbox::lds_backend::egress_policy_summary(
        &second_sandbox,
        &second_policy,
    ),
);

assert_eq!(
    create_hash,
    first_reconcile_hash,
);
assert_eq!(first_reconcile_hash, second_reconcile_hash);
```

Before Task 2, both equality assertions must fail because reconcile hashes rendered, sandbox-scoped data.

- [ ] **Step 3: Add a failing duplicate-completion integration test**

Extend `network_policy_generation.rs` with a test that prepares one generation, ACKs it once, then ACKs the same generation again and expects an idempotent success outcome rather than `false`:

```rust
assert_eq!(first_ack, NetworkPolicyAckOutcome::Applied);
assert_eq!(second_ack, NetworkPolicyAckOutcome::AlreadyReady);
```

- [ ] **Step 4: Add a failing runner lifecycle ownership test**

Extract or exercise the runner-ready lifecycle decision and assert:

```rust
assert_eq!(runner_attach_transition("creating"), None);
assert_eq!(runner_attach_transition("provisioning"), None);
assert_eq!(runner_attach_transition("running"), None);
```

The runner may update bridge metadata, but it must not own lifecycle promotion.

- [ ] **Step 5: Run the characterization tests**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline semantic_network_policy -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline --test network_policy_generation -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline runner_attach_transition -- --test-threads=1
```

Expected: the new assertions fail for the documented reasons before implementation.

- [ ] **Step 6: Review checkpoint**

Run `git diff --check` and inspect only the new tests. Do not commit unless explicitly requested.

---

### Task 2: Introduce Canonical Semantic Policy Identity

**Files:**
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/network_policy.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/mod.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`

**Interfaces:**
- Produces `NetworkPolicyRevision(String)`.
- Produces `DesiredNetworkPolicy::from_inputs(networking, credentials)`.
- Produces `DesiredNetworkPolicy::revision()` and `DesiredNetworkPolicy::render_for(sandbox_id)`.
- Retains `sandbox::lds_backend::egress_policy_summary` only as a redacted rendered diagnostic.

- [ ] **Step 1: Define the semantic model**

Create these application-level types:

```rust
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NetworkPolicyRevision(String);

#[derive(Clone)]
pub struct DesiredNetworkPolicy {
    networking: Option<serde_json::Value>,
    allowlist_hosts: Vec<String>,
    credential_routes: Vec<EgressCredentialRoute>,
}

impl DesiredNetworkPolicy {
    pub fn from_inputs(
        networking: Option<&serde_json::Value>,
        credentials: &SandboxCredentials,
    ) -> anyhow::Result<Self>;

    pub fn revision(&self) -> NetworkPolicyRevision;

    pub fn redacted_summary(&self) -> serde_json::Value;

    pub fn render_for(&self, sandbox_id: SandboxId) -> SandboxEgressPolicy;
}
```

Canonicalize host names and header names, sort allowlists/routes/headers/addresses, hash secret values, and exclude sandbox-scoped resource names.

- [ ] **Step 2: Replace create-path hashing**

Build `DesiredNetworkPolicy` once while resolving the runtime context. Store its revision in `ExpectedFingerprint.egress_policy_hash`, and retain enough logical policy input for the eventual authority request.

Replace the private duplicate functions:

```rust
fn egress_policy_hash(...)
fn egress_policy_summary(...)
```

with calls to `DesiredNetworkPolicy::revision()` and `redacted_summary()`.

- [ ] **Step 3: Replace reconcile and recovery hashing**

In every path currently combining `network_policy_hash` with rendered
`lds_backend::egress_policy_summary`, rebuild the same `DesiredNetworkPolicy` and use:

```rust
let desired = DesiredNetworkPolicy::from_inputs(networking, &credentials)?;
let policy_hash = desired.revision().to_string();
let rendered = desired.render_for(sandbox_id);
```

Do not derive generation identity from `rendered`.

- [ ] **Step 4: Keep rendered summaries diagnostic-only**

Rename the Envoy helper to make the boundary explicit:

```rust
pub fn rendered_egress_policy_summary(
    sandbox_id: &SandboxId,
    policy: &SandboxEgressPolicy,
) -> serde_json::Value;
```

Use it only for redacted audit records and troubleshooting.

- [ ] **Step 5: Run canonical identity tests**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline semantic_network_policy -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline egress_policy -- --test-threads=1
```

Expected: equal logical policy produces one revision across create/reconcile and across sandbox IDs; every enforcement-relevant mutation changes it.

- [ ] **Step 6: Review checkpoint**

Run `cargo fmt --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --check` and `git diff --check`. Do not commit unless explicitly requested.

---

### Task 3: Separate Desired and Applied Generations

**Files:**
- Create: `backend/alembic/versions/20260824_000002_network_policy_convergence.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_sandbox.py`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/models.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/queries/sandbox.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/network_policy_generation.rs`
- Create: `backend/tests/test_network_policy_convergence_migration.py`

**Interfaces:**
- Produces explicit desired and applied hash/version fields.
- Produces `NetworkPolicyPrepareOutcome::{Pending, AlreadyReady}`.
- Produces `NetworkPolicyAckOutcome::{Applied, AlreadyReady, Stale, Missing}`.
- Produces `NetworkPolicyFailureOutcome::{Recorded, AlreadyReady, Stale, Missing}`.

- [ ] **Step 1: Add migration tests**

Create fixtures for ready, pending, nacked, disabled, and destroyed rows. Assert the upgrade mapping:

```text
ready     -> applied hash/version equals desired hash/version
pending   -> applied hash/version is NULL
nacked    -> applied hash/version is NULL
disabled  -> desired/applied remain NULL/0 as defined by the model
destroyed -> historical values are preserved without becoming live
```

Assert downgrade restores the existing columns without losing the desired generation.

- [ ] **Step 2: Add the schema migration**

Add nullable `networking_applied_hash` and `networking_applied_version` columns.
Keep existing `networking_policy_hash/version` as the canonical desired generation.
Backfill only rows with `networking_status = 'ready'`:

```sql
UPDATE joysafeter_sandboxes
SET networking_applied_hash = networking_policy_hash,
    networking_applied_version = networking_policy_version
WHERE networking_status = 'ready';
```

Add a check constraint requiring ready rows to have desired/applied equality.

- [ ] **Step 3: Add typed repository outcomes**

Replace boolean ACK/failure results with enums. Implement ACK as an update followed by an exact-state read when no row was updated:

```rust
match current_state {
    None => NetworkPolicyAckOutcome::Missing,
    Some(state) if state.is_ready_for(generation) => {
        NetworkPolicyAckOutcome::AlreadyReady
    }
    Some(state) if state.desired_matches(generation) => {
        NetworkPolicyAckOutcome::Applied
    }
    Some(_) => NetworkPolicyAckOutcome::Stale,
}
```

The `Applied` branch must come from the successful guarded update, not from an unchecked read.

- [ ] **Step 4: Split ordinary prepare from recovery reopen**

Implement:

```rust
pub async fn prepare_desired_network_policy(...)
    -> Result<NetworkPolicyPrepareOutcome, sqlx::Error>;

pub async fn reopen_network_policy_for_authority_recovery(...)
    -> Result<NetworkPolicyGeneration, sqlx::Error>;
```

Ordinary same-revision prepare returns `AlreadyReady` without demoting the row.
Only authority recovery may reopen the same ready generation after in-memory xDS loss.

- [ ] **Step 5: Run database tests**

From the repository root, with a migrated test database configured:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline --test network_policy_generation -- --test-threads=1
cd backend && uv run pytest tests/test_network_policy_convergence_migration.py -q
```

Expected: migration and state-transition matrices pass, including duplicate ACK and same-generation prepare.

- [ ] **Step 6: Review checkpoint**

Run `cd backend && uv run alembic upgrade head`, inspect the resulting schema, and run `git diff --check`. Do not commit unless explicitly requested.

---

### Task 4: Route Every Apply Through One Authority

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/xds_authority.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_controller.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/main.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/provider.rs`

**Interfaces:**
- Produces `ensure_network_policy_ready(pool, queue, authority, sandbox_id, generation, timeout)`.
- The function succeeds for `Applied` and `AlreadyReady`, returns a freshness error for `Stale`, and returns a lifecycle error for `Missing`.
- Only `apply_sandbox_networking_generation_as_authority` invokes `provider.refresh_networking`.

- [ ] **Step 1: Add a barrier-controlled authority test double**

Implement a test provider that records refresh and teardown calls and uses Tokio barriers to control completion:

```rust
struct BlockingNetworkProvider {
    refresh_entered: Arc<Barrier>,
    refresh_release: Arc<Barrier>,
    refresh_count: AtomicUsize,
    teardown_count: AtomicUsize,
}
```

The test must launch resolver waiting and reconcile concurrently and assert one durable successful outcome with zero teardown calls.

- [ ] **Step 2: Introduce one ensure operation**

Move the local/multi branching behind:

```rust
pub async fn ensure_network_policy_ready(
    pool: &PgPool,
    queue: Option<&dyn NetworkPolicyRequestQueue>,
    authority: &XdsAuthorityState,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
    timeout: Duration,
) -> anyhow::Result<NetworkPolicyAckOutcome>;
```

Local mode applies under the same authority application lock and epoch guard used by recovery. Multi mode publishes the exact generation and waits in PostgreSQL.

- [ ] **Step 3: Remove direct resolver provider mutation**

Replace `apply_prepared_network_policy` calls to `provider.refresh_networking` with `ensure_network_policy_ready`. Keep provider rendering and publication inside the authority application function.

- [ ] **Step 4: Make reconcile consume desired state**

The degraded loop reads the current desired generation. It rebuilds the semantic policy only to validate that durable desired state is current. It does not prepare a new generation from a rendered summary.

- [ ] **Step 5: Cover authority loss and duplicate wakeups**

Add tests where:

```text
duplicate Redis/in-process wakeup -> one generation, idempotent success
authority epoch changes before ACK -> no applied-state mutation
new authority reopens same generation -> apply and ready
stale request arrives after newer desired generation -> Stale, no provider write
```

- [ ] **Step 6: Run focused authority tests**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline xds_authority -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline networking_reconcile -- --test-threads=1
```

Expected: all mutation paths use one authority function and concurrent duplicate requests converge.

- [ ] **Step 7: Review checkpoint**

Use `rg "provider\.refresh_networking" backend/app/joysafeter_orchestrator_rs/src` and verify the only production call is inside the authority application boundary. Do not commit unless explicitly requested.

---

### Task 5: Correct Lifecycle and Fence Cleanup

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_lifecycle.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/queries/sandbox.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs`

**Interfaces:**
- Produces `begin_owned_sandbox_cleanup(sandbox_id, external_id, generation)`.
- Produces a resolver wait path that adopts `AlreadyReady` and current ready state.
- Removes lifecycle mutation from runner attachment.

- [ ] **Step 1: Remove runner-owned lifecycle promotion**

Delete the generic transition:

```rust
transition_sandbox_cas(&pool, sandbox_db_id, status, "idle")
```

Runner attach continues to authenticate, register the bridge, touch liveness, and clear disconnect metadata.

- [ ] **Step 2: Enforce executable readiness**

Before task attachment/start, require:

```rust
sandbox.runner_bridge_is_ready()
    && sandbox.runtime_config_is_current(required_generation)
    && sandbox.network_policy_is_ready_for(required_policy_generation)
```

Keep the sandbox in `creating` until the desired network generation is ready, then let the resolver perform `creating → provisioning`.

- [ ] **Step 3: Add fenced cleanup repository operation**

Implement one guarded transition equivalent to:

```sql
UPDATE joysafeter_sandboxes
SET status = 'stopping', updated_at = NOW()
WHERE id = $1
  AND external_id = $2
  AND status IN ('creating', 'provisioning')
  AND networking_policy_hash = $3
  AND networking_policy_version = $4
  AND NOT (
      networking_status = 'ready'
      AND networking_applied_hash = networking_policy_hash
      AND networking_applied_version = networking_policy_version
  )
RETURNING id;
```

Only a successful return authorizes teardown and provider destruction.

- [ ] **Step 4: Adopt concurrent success before cleanup**

When ensure/apply returns stale or persistence conflict, reload the sandbox:

```rust
if sandbox.network_policy_is_ready_for_current_desired()
    && runtime_generation_is_current
{
    return Ok(());
}
```

A newer generation returns a runtime freshness conflict and leaves cleanup to its owner.

- [ ] **Step 5: Add lifecycle concurrency tests**

Cover:

```text
runner connects during creating -> status remains creating
network becomes ready -> resolver transitions to provisioning
concurrent ready before cleanup -> cleanup CAS fails, provider survives
newer generation before cleanup -> stale caller does not teardown
provider failure before any ready generation -> cleanup owns stopping and destroys
```

- [ ] **Step 6: Run focused lifecycle tests**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline sandbox_resolver -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline grpc::server -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline scheduler -- --test-threads=1
```

Expected: no test permits a stale network completion to destroy a ready/newer sandbox.

- [ ] **Step 7: Review checkpoint**

Search all `creating → idle` transitions and document the owner of each remaining test or production call. Run `git diff --check`. Do not commit unless explicitly requested.

---

### Task 6: Make gRPC xDS the Supported Default

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/config.rs`
- Modify: `backend/env.example`
- Modify: `deploy/.env.example`
- Modify: `deploy/local-test.sh`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/mcp_live_envoy.rs`
- Modify: `deploy/k8s/env-reference.md`

**Interfaces:**
- Makes `grpc` the default dynamic xDS transport.
- Keeps filesystem mode explicit and fail-closed for cross-resource dependencies.
- Produces real acceptance evidence for both transports.

- [ ] **Step 1: Add configuration tests**

Assert that an absent `JOYSAFETER_ENVOY_XDS_MODE` resolves to `grpc`, invalid values fail validation, and explicit `filesystem` remains selectable.

- [ ] **Step 2: Switch defaults and examples**

Change the Rust default and all local/deployment examples to `grpc`. Keep Helm values unchanged where already set to `grpc`.

- [ ] **Step 3: Harden filesystem publication**

Replace resource-count `version_info` with a SHA-256 content version. Add an Envoy admin probe contract and publish in this order:

```rust
self.cds.replace_by_prefix(&cluster_prefix, clusters).await?;
self.wait_for_clusters_active(&required_cluster_names).await?;
self.lds.upsert(vec![listener]).await?;
self.wait_for_listener_active(sandbox_id).await?;
self.wait_for_socket_ready(sandbox_id).await?;
```

If admin verification is unavailable, return a typed `xds_timeout`/configuration error before LDS publication.

- [ ] **Step 4: Preserve gRPC atomic batch behavior**

Retain `apply_sandbox_batch` as one version tick with CDS changes before LDS changes. Extend the test to assert that a listener referencing a new dedicated cluster cannot be emitted in an earlier version.

- [ ] **Step 5: Run xDS tests**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline sandbox::lds_backend::tests -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline sandbox::envoy::tests -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline --test mcp_live_envoy --no-run
```

Expected: gRPC batch ordering, ACK handling, filesystem activation barrier, and socket gating pass.

- [ ] **Step 6: Review checkpoint**

Run `rg "JOYSAFETER_ENVOY_XDS_MODE" backend deploy docs` and verify every supported default is `grpc`, with filesystem described only as compatibility/debug mode. Do not commit unless explicitly requested.

---

### Task 7: Add Error Taxonomy and Operational Evidence

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/xds_authority.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE_CN.md`

**Interfaces:**
- Produces stable scheduling error categories for policy compile, stale generation, NACK, timeout, socket readiness, persistence, lifecycle conflict, and provider failure.
- Produces structured logs containing IDs and versions but no secret material.

- [ ] **Step 1: Define typed network-policy errors**

Introduce an application error enum with variants:

```rust
PolicyCompile,
PolicyStale,
XdsNack,
XdsTimeout,
SocketTimeout,
AckPersistence,
LifecycleConflict,
ProviderFailure,
```

Attach the underlying error as a source and retain full causal formatting through Scheduler.

- [ ] **Step 2: Replace substring classification**

Change Scheduler from string matching to typed classification. Persist stable codes such as `xds_nack`, `policy_stale`, and `lifecycle_conflict` in `last_schedule_error_type`.

- [ ] **Step 3: Add structured context**

At prepare, apply, ACK, NACK, wait, and cleanup boundaries log:

```text
sandbox_id, task_id, desired_hash_prefix, desired_version,
applied_version, authority_epoch, xds_transport, operation_id, outcome
```

Use full-chain error formatting and never include plaintext headers or tokens.

- [ ] **Step 4: Update architecture documentation**

Document the desired/applied model, single authority writer, lifecycle ownership table, gRPC default, filesystem limitations, and cleanup fencing in both architecture documents.

- [ ] **Step 5: Run documentation and error tests**

Run:

```bash
python3 scripts/check_documentation_contracts.py
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline classify_scheduling_error -- --test-threads=1
```

Expected: documentation contracts and typed error mappings pass.

- [ ] **Step 6: Review checkpoint**

Run a repository search for the old generic error and verify detailed causes survive to persisted task errors and logs. Do not commit unless explicitly requested.

---

### Task 8: Run End-to-End Convergence Verification

**Files:**
- Modify: `tests/mcp_connection_matrix/test_l3_live.py`
- Modify: `tests/mcp_connection_matrix/conftest.py` if shared MCP fixtures require lifecycle support
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/mcp_live_envoy.rs`
- Create: `docs/superpowers/evidence/2026-08-26-envoy-network-policy-convergence-verification.md`

**Interfaces:**
- Proves real Claude Code access to no-auth, bearer, API-key-header, and custom-header MCP servers through limited networking.
- Proves repeated scheduling and authority recovery do not create generation churn or destructive cleanup.

- [ ] **Step 1: Add deterministic live fixtures**

Use the existing MCP fixture server to expose four endpoints on distinct ports. Store secrets only in temporary credential files or database records and never print them.

- [ ] **Step 2: Add a repeated bearer scheduling test**

Create one authenticated MCP agent/session flow and repeat sandbox allocation 20 times. For every attempt assert:

```text
task reaches running/completed
exactly one active sandbox is attached
desired version remains stable for duplicate application
applied version equals desired version
networking status is ready
Envoy listener remains present until normal lifecycle teardown
MCP ping returns pong
```

- [ ] **Step 3: Add fault-injection cases**

Cover delayed CDS delivery, duplicate reconcile wakeups, authority restart, stale ACK, socket delay, and teardown racing with a newer generation. Each case must assert final PostgreSQL and Envoy state, not only task output.

- [ ] **Step 4: Run focused real-Envoy tests**

Run:

```bash
JOYSAFETER_RUN_LIVE_ENVOY=1 \
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline --test mcp_live_envoy -- --ignored --nocapture --test-threads=1
```

Expected: all xDS acceptance, socket, routing, and authentication assertions pass.

- [ ] **Step 5: Run the L1/L2/L3 MCP matrix**

Run from the repository root:

```bash
cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l1_direct.py test_l2_contract.py -q
cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l3_live.py -q -k 'mcp and envoy'
```

Expected: anonymous SSE and Streamable HTTP, including all managed authentication
schemes, pass through their supported public flows.

- [ ] **Step 6: Run broader verification**

Run:

```bash
cargo fmt --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --check
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline -- --test-threads=1
cd backend && uv run pytest tests/test_network_policy_convergence_migration.py -q
git diff --check
```

Record unrelated failures separately; do not present partial or blocked checks as passing.

- [ ] **Step 7: Capture runtime evidence**

The verification document must include:

```text
exact commands and exit codes
test counts
task and sandbox IDs used for the live run
desired/applied generation state
Envoy ACK/NACK summary
absence of unknown-cluster events on gRPC xDS
absence of ready-to-destroy cleanup caused by generation conflict
remaining risks and deployment actions
```

- [ ] **Step 8: Final review checkpoint**

Compare every acceptance criterion in the design spec with direct test, database, or runtime-log evidence. Do not declare completion while any criterion lacks authoritative evidence.
