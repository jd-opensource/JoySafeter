# Unified Egress — Provider Parity + CI-Grade E2E Verification

Status: **approved for implementation planning**
Date: 2026-08-01
Branch: `joysafeter-v2`
Scope: Docker single-host + Kubernetes/k3s egress data planes
Parent architecture: [`2026-07-31-production-unified-envoy-egress-architecture.md`](./2026-07-31-production-unified-envoy-egress-architecture.md)

This is a **delivery + verification sub-spec** of the parent unified-Envoy-egress
architecture. It does not re-decide architecture; it executes two of the parent
spec's phases and closes the verification vacuum. It covers:

1. A minimal **Phase 4** — bring the Docker Envoy onto the same Go control plane
   the K8s fleet already uses, so both providers run one control/credential
   plane.
2. **CI-grade end-to-end verification** for *both* Docker and K8s, producing
   tamper-evident, cross-correlated evidence rather than a self-asserting script.

## 1. Goal and Non-Goals

**North star (user):** good architecture, extensible security control,
production-grade — with **both Docker and K8s guaranteed end-to-end verified**.

**In scope:**

- **B. Provider parity:** wire Docker Envoy to the Go `egress-controller`
  (`SOURCE=postgres` + ADS to `egress-controller:18000` + per-sandbox socket
  listeners), behind a flag, with the legacy file-bootstrap path retained for
  rollback. Mark the Rust in-process xDS prototype (`sandbox/lds_backend.rs`)
  deprecated; do **not** delete it in this spec.
- **C. E2E verification:** real-Envoy, CI-runnable end-to-end tests for both
  providers, each emitting multi-source cross-correlated evidence.
- **C-4. Rust egress CI lane:** build + test the orchestrator egress code
  (`authority.rs`, `ext_authz.rs`, `enforcer.rs`) with a Postgres service.
- **D. deploy.sh convergence:** `deploy.sh k8s verify` points at the egress
  smoke; the manual `.tmp/envoy-xds-validation/` scaffold is promoted into a
  tracked, automated harness.

**Explicitly deferred to follow-on specs (documented here as known gaps, not
silently dropped):**

- Go controller **leader election / single-writer HA** (3 replicas currently
  publish and write apply-status independently; correctness rests on idempotent
  upserts + deterministic version hashes; concurrent state-machine races are
  untested). Single-replica e2e in this spec is unaffected.
- Parent **Phase 2** — independent `joysafeter-egress-authz`/broker deployment
  with resource isolation.
- Parent **Phase 5** — removal of the Rust HTTP forwarding proxy path
  (standalone binary, K8s manager adapter, enforcer branch, and proxy env).
- **Outbox real consumer** — `joysafeter_egress_outbox_events` currently only
  fires the `pg_notify` trigger; its `claimed_by/claimed_until/attempts/
  available_at` delivery protocol has no consumer.
- **Production PKI** — cert-manager/SPIRE issuance replacing the ephemeral
  `pki/bootstrap-egress-pki.sh`.
- **Multi-host Docker per-call identity** on the ext_authz Docker face (today it
  relies on per-sandbox Unix-socket isolation with `pool: None`).

## 2. Current State (code facts, verified 2026-08-01)

The reconciled architecture (contradicting an earlier stale note that said "drop
Go"): **Go won, Rust delegates.**

- Rust orchestrator writes provider-neutral desired policy generations to five
  `joysafeter_egress_*` Postgres tables (`egress/authority.rs:471,565`) and waits
  on the `joysafeter_egress_apply_status` NOTIFY (`authority.rs:505,785`).
- Go `egress-controller` reads those tables (`LISTEN joysafeter_egress_generation`
  + 30s full reconcile), compiles Envoy LDS/RDS/CDS, serves mTLS ADS, tracks
  ACK/NACK/last-known-good, and writes apply-status back. Near-complete, high
  quality, no TODO/FIXME.
- ext_authz is the orchestrator itself (K8s manifest `26-egress-authz.yaml`
  selects `app=joysafeter-orchestrator:18090`); the K8s face has mTLS DNS-SAN +
  runner-token constant-time check + generation-scoped last-known-good route
  lookup (`kernel/ext_authz.rs:107,203,247`).
- The whole feature is gated off by `JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED`
  (default `false`); legacy paths remain for rollback.

**What is done:** the K8s single path is wired and hardened; `k3s-egress-smoke.sh`
(806 lines) already asserts the full security matrix end-to-end.

**What blocks "production-grade, both providers e2e verified":**

- **Docker Envoy is not wired to the new control plane.** `deploy/docker-compose.yml:101-118`
  still runs the legacy file-bootstrap Envoy (empty `lds.json`/`cds.json`, waits
  for `bootstrap.json`); the compose `egress-controller` runs `SOURCE=file` on the
  example snapshot (`docker-compose.yml:80`) and is **not in the Docker data
  path**. Two xDS implementations coexist (Go for K8s, Rust prototype for Docker).
- **No real Envoy is ever fed the compiled config in CI.** The Go "e2e" test
  drives `manager.ACK/NACK` in-process (`xds/postgres_e2e_integration_test.go`);
  `.tmp/envoy-xds-validation/envoy.yaml` is a manual, unasserted, untracked,
  CI-excluded scaffold.
- **Neither Docker nor K8s egress e2e runs in CI.** `k3s-egress-smoke.sh` is
  local/manual only (needs real k3s + Postgres + real API key), and
  `deploy.sh k8s verify` invokes `k3s-task-smoke.sh`, not the egress smoke.
  `ci.yml:13-76` gates only the Go controller (build + unit + Postgres xDS
  integration).
- **The Rust orchestrator egress code has no CI lane.**

## 3. Design — B: Provider Parity (Docker onto the Go control plane)

The building blocks already exist; only wiring is missing.

- The Go docker compiler already emits per-sandbox Unix-socket listeners
  (`egress-controller/internal/compiler/render.go:188-190`,
  `compiler.go:158-162`).
- The Rust authority already supports the docker `host_id` node-selector key
  (`authority.rs`; migration requires `host_id` for `provider=docker`,
  `20260731_000001_egress_control_plane.py:57-65`).

The three wiring changes:

1. **Compose controller reads the real database.** Change the compose
   `joysafeter-egress-controller` from `SOURCE=file` (example snapshot) to
   `SOURCE=postgres` against the same Postgres the orchestrator uses.
2. **Docker Envoy consumes ADS from the controller.** Replace the
   file-bootstrap entrypoint (`docker-compose.yml:110-118`) with a bootstrap
   whose `dynamic_resources` point ADS at `joysafeter-egress-controller:18000`,
   carrying mandatory node metadata (`deployment_id`, `environment`, `region`,
   `provider=docker`, `shard_id`, `host_id`, `envoy_version`,
   `config_schema_version`). Local dev uses the plaintext bootstrap
   (`XDS_MTLS=false`), matching the existing K8s `local` overlay convention.
3. **Per-sandbox socket path alignment.** The mounted per-sandbox socket
   directory must match the listener path the controller emits
   (`<SocketRoot>/<sandboxID>/http.sock`).

**Flagging and rollback.** A Docker-side switch (reusing/extending
`JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED` semantics on the Docker preparer)
selects controller-driven xDS vs the legacy file path. The legacy path and
`lds_backend.rs` remain intact; `lds_backend.rs` gains a deprecation marker only.
Deletion is parent-spec Phase 5, out of scope here.

**Definition of done (B):** with the flag on, a Docker sandbox's egress traverses
the shared Envoy configured entirely by the Go controller over ADS; the Rust
in-process/file xDS path is not used; flag off restores the legacy path
byte-for-byte.

## 4. Design — C: E2E Verification (tamper-evident, cross-correlated)

**Principle:** a green script that exits 0 is not proof. Each link must produce
**independent, cross-correlated evidence from components that cannot all be
trivially forged by the test harness.** CI uses a **mock upstream**; no real API
key is placed in CI (the real-model round-trip stays in the operator's local
smoke).

### 4.1 The four evidence sources (asserted per link, both providers)

1. **Envoy side (self-report of applied config):** real Envoy `/config_dump`
   and `/stats` prove Envoy accepted and ACKed this generation — the credential
   listener, `host_rewrite_literal`/SNI, and the `ext_authz` filter are actually
   present; upstream cluster count matches policy.
2. **Postgres side (control-plane record, independent of Envoy's self-report):**
   `joysafeter_egress_apply_status.state = applied` with
   `acked_acks == required_acks` and zero NACKs, plus a matching
   `joysafeter_egress_node_apply_status` ACK row for the connected node
   (`nonce_sha256` only).
3. **Data-plane side (behavioral):**
   - Correct identity → request reaches the mock upstream with the
     platform-injected header (verified at the mock, not echoed by the client).
   - Wrong/missing token → ext_authz returns **403**.
   - Direct upstream IP from the sandbox → **denied** (NetworkPolicy on K8s;
     `network=none` + socket-only on Docker).
   - Real secret absent from pod/container env, process args, mounted files, and
     the `last-applied-configuration` annotation.
4. **Cross-correlation (anti-forgery):** tie an Envoy access-log `x-request-id`
   to the sandbox-side request and to the mock upstream's received request, so a
   single fabricated output cannot satisfy all three independent observers.

### 4.2 Real-Envoy xDS acceptance harness (replaces `.tmp/`)

Promote `.tmp/envoy-xds-validation/envoy.yaml` into a tracked, automated harness
that boots a **real Envoy** against the controller and asserts an ACKed
`config_dump` containing the expected resources. This closes the currently
fully-unverified "compiled config is accepted by a real Envoy" gap. Runs in CI
(see §5).

### 4.3 Layered coverage (no real API key anywhere in CI)

1. **Real-Envoy xDS acceptance (per PR, fast):** §4.2 — real Envoy + controller
   (+ Postgres source), assert `config_dump`/ACK + Postgres `applied`.
2. **Docker compose egress smoke (per PR):** the unified compose stack
   (controller `SOURCE=postgres` + Envoy over ADS + ext_authz + sandbox + mock
   upstream) runs the §4.1 four-source assertions.
3. **kind/k3d cluster egress smoke (slower lane / nightly):** apply
   `deploy/k8s/base/{25,26,27}-*.yaml`, run a **credential-only, mock-upstream**
   variant of `k3s-egress-smoke.sh` asserting the full security matrix (xDS ACK,
   secret-not-in-env, NetworkPolicy bypass-denied, ext_authz 403, Postgres ACK
   quorum). Reuses the existing 806-line smoke's assertions; strips the real
   Anthropic round-trip.
4. **Rust egress CI lane (per PR):** `cargo test` over `authority.rs`,
   `ext_authz.rs`, `enforcer.rs` with a Postgres service (mirrors the existing Go
   lane's Postgres + Alembic-head setup).

## 5. Design — D: Real-Envoy CI Topology

Layered, approved selection:

- **Per-PR fast gate:** `func-e`-launched real Envoy binary inside a Go test
  (§4.2), connecting to the controller and asserting `config_dump`/ACK. Runs in
  the existing Go lane. **This is the primary always-on real-Envoy gate.**
- **Docker:** the docker-compose egress smoke (§4.3-2) is the compose-form real
  Envoy check (approved option ②), runnable both locally and in CI.
- **Nightly / slower lane:** the kind cluster job (§4.3-3) exercises the real
  manifests and full security matrix (approved option ③).

CI additions to `.github/workflows/ci.yml`:

- Extend the Go lane (or add a job) to run the `func-e` real-Envoy acceptance
  test.
- Add a **Docker compose egress smoke** job (per PR).
- Add a **kind egress smoke** job (nightly or slow lane, not blocking every PR).
- Add a **Rust egress** job (build + `cargo test` egress modules + Postgres
  service).

`deploy/deploy.sh`: repoint `k8s verify` at the egress smoke (or add
`k8s verify-egress`), and remove reliance on the manual `.tmp/` scaffold.

## 6. Delivery Sequence (each step's DoD = "CI reproducibly emits cross-correlated evidence")

1. **B — Docker onto the controller.** Wire compose + bootstrap + socket paths;
   flag-gated; legacy path preserved. DoD: local Docker sandbox egress fully
   controller-driven; flag-off unchanged.
2. **C-1 — Real-Envoy acceptance harness.** Promote `.tmp/` into a `func-e` Go
   test; assert `config_dump`/ACK + Postgres `applied`.
3. **C-2 — Docker compose egress smoke.** Four-source assertions on the unified
   compose stack with a mock upstream.
4. **C-3 — kind egress smoke.** Credential-only, mock-upstream variant of the
   k3s smoke on real manifests.
5. **C-4 — Rust egress CI lane.** `cargo test` egress modules with Postgres.
6. **D — CI + deploy.sh convergence.** Land the CI jobs; repoint `deploy.sh`;
   retire the manual `.tmp/` reference; document the Docker/K8s parity + verify
   commands.

## 7. Validation Matrix Mapping (to parent spec §23)

- **Security:** secret-absent-from-env/config/logs, direct-egress-denied,
  wrong-token-denied, CONNECT-denied-on-credential-listener → C-2 + C-3
  four-source assertions.
- **Resilience (subset):** force xDS NACK → last-known-good retained; disconnect
  xDS → existing policy continues; stop ext_authz → new requests fail closed →
  covered by C-1/C-3 where feasible; full resilience matrix and HA failover are
  in the deferred HA spec.
- **Functional:** mock-upstream credentialed round-trip in CI; real-model
  round-trip remains the operator's local smoke.

## 8. Risks and Mitigations

- **Docker bootstrap rewrite regresses the legacy path.** Mitigation: flag-gated;
  legacy entrypoint retained; flag-off path asserted unchanged in the compose
  smoke.
- **`func-e` Envoy version drift vs pinned `v1.39.0` digest.** Mitigation: pin the
  harness Envoy to the same digest used in compose/manifests; the hand-rolled
  `*V139` prost messages in `lds_backend.rs` are Docker-legacy only and unaffected
  by the controller path.
- **kind job flakiness/slowness.** Mitigation: keep it off the per-PR blocking
  path (nightly/slow lane); the per-PR gate is `func-e` + compose smoke.
- **Running the controller single-replica in e2e hides the HA race.** Accepted:
  HA is an explicit deferred gap; e2e here validates correctness, not concurrent
  writers. The follow-on HA spec must add a multi-writer race test.

## 9. Open Follow-on Specs (created by this effort's completion)

1. Go controller **HA / single-writer** (leader election or partitioned
   ownership) + concurrent-writer race test.
2. Parent **Phase 2** authz/broker isolation; **Phase 5** Rust HTTP proxy removal.
3. **Outbox** real delivery consumer (or formally demote the delivery columns).
4. **Production PKI** (cert-manager/SPIRE) replacing the bootstrap script.
5. **Multi-host Docker** ext_authz per-call identity.
