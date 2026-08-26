# Envoy Network Policy Convergence Analysis

**Date:** 2026-08-26

**Status:** Root cause verified; implementation landed, live stress verification pending

## Scope

This evidence record covers task
`task_01a03bc2-43a0-79c3-9591-8f2ae3a06f83` and the three sandboxes created by
its initial scheduling attempt plus two retries.

## Runtime Evidence

The task row reports:

```text
status                   = failed
retry_count              = 2
max_retries              = 2
schedule_attempts        = 2
last_schedule_error      = failed to setup Envoy networking for new sandbox
last_schedule_error_type = envoy_setup
```

The three sandbox attempts were:

```text
sbx_01a03bc2-43b6-7a43-90e3-4c940e860efd
sbx_01a03bc2-a204-7973-be08-b86ea5c68358
sbx_01a03bc3-3b29-73b3-8ed6-f180d4c43248
```

All three database rows ended as:

```text
status                    = destroyed
networking_status         = ready
networking_policy_version = 2
networking_last_error     = NULL
```

The final hashes were different for each sandbox even though the logical MCP and
network configuration was unchanged. That is consistent with hashing rendered,
sandbox-scoped cluster names.

## First Attempt Timeline

```text
09:49:42.386  Docker container created
09:49:42.429  sandbox started; initial policy hash a007fcf0...
09:49:42.431  foreground Envoy configuration begins
09:49:42.432  runner connects
09:49:42.438  SetupSandbox is sent
09:49:42.608  Envoy rejects LDS: referenced cluster is unknown
09:49:42.610  Envoy applies the missing CDS cluster
09:49:49.306  degraded-network reconcile starts a second application
09:49:49.501  Envoy accepts the listener
09:49:49.505  one caller confirms the Unix socket
09:49:49.507  listener and dedicated cluster are removed
09:49:49.521  the concurrent caller also observes the socket
09:49:49.522  reconcile records version 2 ready
09:49:59.371  cleanup finishes and Scheduler reports failure
```

Attempts two and three repeat the same shape: initial unknown-cluster rejection,
later listener acceptance, version 2 ready, immediate listener removal, and a
scheduler error after provider cleanup.

## Code Evidence

### Filesystem publication is not atomic

`backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs:751` attempts the
combined batch API. Filesystem LDS returns `false`, so the fallback writes CDS and
LDS separately at `backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs:761`.

The default `LdsBackend::wait_for_sandbox_ack` at
`backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs:781` returns
`Ok(())`; filesystem mode therefore has no real ACK/NACK observation.

### Policy identity has two definitions

Creation uses `egress_policy_hash` at
`backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs:3255`.
It hashes logical networking and route semantics without rendered cluster names.

Reconcile uses `network_policy_hash` over
`sandbox::lds_backend::egress_policy_summary` at
`backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs:2910`.
That summary includes route IDs, cluster names, vetted addresses, and rendered
cluster records at
`backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs:548`.

The initial hash was identical across all three attempts. Reconcile produced three
different hashes, proving that sandbox-scoped rendered data entered the durable
generation identity.

### Runner attachment exposes in-progress creation

The runner gRPC server transitions every non-pooled sandbox from its current state
to `idle` at `backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs:219`.

The degraded-network query selects `idle`, `running`, and `provisioning` rows with
`pending`, `nacked`, or `failed` networking at
`backend/app/joysafeter_orchestrator_rs/src/db/queries/sandbox.rs:213`.

The runner therefore makes a still-provisioning sandbox visible to reconcile.

### Stale completion triggers destructive cleanup

The foreground path ACKs only its exact generation at
`backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs:346`.
After reconcile advances the hash/version, that compare-and-set returns false and
the foreground path reports `generation changed before ACK persistence`.

The new-sandbox caller treats the result as an Envoy setup failure and invokes
`cleanup_rejected_new_sandbox` at
`backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs:1049`.
The cleanup removes xDS resources and destroys the provider resource without first
adopting a concurrently ready generation.

## Test Coverage Assessment

Existing tests prove important but incomplete properties:

- stale ACK cannot overwrite a newer generation;
- stale failure cannot NACK a newer generation;
- late failure cannot replace an acknowledged generation;
- gRPC xDS batches clusters before listeners under one version.

Missing coverage includes:

- create and reconcile produce the same semantic revision;
- duplicate completion of the same generation is successful;
- runner attachment does not expose an in-progress sandbox;
- reconcile and foreground provisioning converge without teardown;
- cleanup cannot remove a ready or newer generation;
- filesystem CDS activation is observed before LDS publication;
- a real authenticated MCP task survives the complete scheduling path.

## Verification Commands Run

Successful evidence collection:

```text
docker logs joysafeter-orchestrator
docker logs joysafeter-envoy
docker exec joysafeter-db ... psql ...
git blame ... sandbox_resolver.rs lds_backend.rs grpc/server.rs
git diff --check -- <investigated files>
```

The targeted Rust test commands were attempted:

```text
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline apply_sandbox_batch_is_atomic_and_ordered -- --exact --nocapture

cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --offline egress_policy_hash_tracks_header_secret_without_leaking_it \
  -- --exact --nocapture
```

They did not reach the selected test because the existing uncommitted typed-ID
work contains unrelated compilation failures, including mismatched typed IDs in
`tests/credential_runtime_contract.rs` and an unresolved
`joysafeter_entity_id` import in `crates/agent-identity-trait`.

No production code was modified while collecting this evidence.

## Verified Conclusion

The initial filesystem LDS rejection is the trigger, but it is not sufficient to
explain the terminal task failure. The deterministic terminal failure is caused by
the create and reconcile paths assigning different identities to the same logical
policy, advancing the generation concurrently, and allowing the stale foreground
caller to destroy a sandbox whose replacement generation was already usable.

## Implementation Follow-up

The convergence implementation subsequently landed in `aa5af383` and
`0aafcb6c`. PostgreSQL now stores distinct desired and applied generations;
the orchestrator uses one semantic policy revision, idempotent typed ACK/NACK
outcomes, authority fencing, guarded cleanup, and gRPC xDS as the supported
publication path.

Fresh verification on 2026-08-26:

```text
cargo fmt --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --check
  passed
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --lib -- --test-threads=1
  334 passed
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --test network_policy_revision -- --test-threads=1
  1 passed
cd backend && .venv/bin/pytest -q tests/test_network_policy_convergence_migration.py
  1 passed
python3 scripts/check_documentation_contracts.py
  passed
```

The Rust commands still emit pre-existing dead-code/private-interface warnings.
The 20-run authenticated live stress scenario and authority-restart deployment
exercise were not repeated in this documentation pass and remain the explicit
operational verification gap.
