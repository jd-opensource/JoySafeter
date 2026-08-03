# tonic 0.12→0.14 / envoy-types Unification — Design

- **Date:** 2026-08-03
- **Status:** Designed; execution deferred until after the Rust xDS rewrite passes its production cutover
- **Scope:** `backend/app/joysafeter_orchestrator_rs` dependency stack (tonic, prost, envoy-types) and the three tonic gRPC servers it hosts
- **Driver:** Pure tech-debt cleanup — no new feature depends on this

## Goal and non-goals

**Goal.** Eliminate the deliberate dual-`envoy-types` state in the orchestrator crate
(`=0.5.1` runtime + `=0.7.6` compile-time via the `prost14` rename) and unify the whole
crate onto a single stack: **tonic 0.14 / prost 0.14 / envoy-types 0.7.6**. Success means a
single dependency stack, a clean dependency tree, and **no runtime behavior change** — the
gRPC wire protocol, mTLS semantics, and the xDS/ext_authz allow/deny decision logic all stay
identical.

**Non-goals.**
- Do NOT upgrade `envoy-types` beyond `0.7.6` (no chasing 0.7.x-latest or a new major).
- Do NOT introduce new Envoy features or change any xDS/ext_authz behavior.
- Do NOT refactor the xDS control-plane logic.
- Do NOT add compatibility shims or dual-mode/rollback scaffolding (the product is pre-launch;
  a clean effective refactor is preferred over compat debt).

**Execution precondition.** This migration is written now but executed **only after the
node-local Envoy + Rust xDS rewrite (`2026-08-03-node-local-envoy-rust-xds-rewrite.md`)
completes its live production cutover verification.** Stacking an unverified-in-production
xDS rewrite with a tonic major bump would make failure attribution ambiguous.

## Why this is deliberate and coupled (background)

The crate today intentionally compiles two `envoy-types` versions; the build log showing
`Compiling envoy-types v0.5.1` AND `v0.7.6` is expected, not a conflict.

- `envoy-types = "=0.5.1"` → runtime (Delta xDS/ADS + ext_authz), bound to tonic 0.12 / prost 0.13.
- `envoy-types-v076 = { package = "envoy-types", version = "=0.7.6" }` → compile-time protobuf
  baseline only, bound to tonic 0.14 / prost 0.14; consumed only by `src/xds/compiler.rs` via
  the `prost14` rename + `#[prost(prost_path = "prost14")]`. Compiled Envoy resources cross the
  0.5.1↔0.7.6 boundary as protobuf `Any` bytes, which are wire-compatible — that is why the two
  stacks safely coexist.

## Approach principles (systematic root-cause; no band-aids)

These are hard requirements on HOW the eventual execution is done, not optional style:

1. **Root-cause before action.** When a compile error, test failure, or smoke failure
   appears during the migration, diagnose WHY at the level of the underlying cause (a proto
   field renamed between Envoy API snapshots; a tonic type that moved crates; a feature-flag
   behavior change) before changing anything. Do not act on the surface symptom alone.
2. **No incremental band-aids.** Forbidden: fixing envoy-types struct-literal errors one at a
   time as the compiler surfaces them, sprinkling `#[allow]`, papering over a moved API with a
   local re-export/shim, or leaving a half-migrated dual-stack "for now." Piecemeal patches here
   compound into long-tail breakage (后患无穷). Each class of change is understood and applied
   uniformly across all its sites in one pass.
3. **Fix the class, not the instance.** If the same kind of divergence appears in 2+ places
   (e.g. a field-shape change recurring across listener/cluster/route builders), stop and
   resolve it as one systematic change across every site, not N local edits.
4. **Prove equivalence, don't assume it.** "No behavior change" is verified by evidence (byte
   comparison of compiled resources + the e2e smokes), never asserted because the code still
   compiles.

## The atomic constraint and migration ordering

**Hard constraint.** `src/grpc/server.rs` (~line 7220-7245) registers three services on ONE
`tonic::transport::Server`: the runner AgentBridge (generated from `proto/joysafeter.proto`),
the ADS `AggregatedDiscoveryServiceServer`, and the ext_authz `AuthorizationServer`. tonic
forbids mixing different-major-version services on one builder, so AgentBridge + ADS +
ext_authz must migrate to tonic 0.14 **atomically**, together with switching the runtime
`envoy-types` from 0.5.1 to 0.7.6. Two standalone servers on the same stack migrate in the same
change: `src/xds_server.rs` (K8s-plane ADS) and `src/kernel/ext_authz.rs` (K8s-plane ext_authz).

**Ordering.** Done on an isolated worktree/branch, structured as ordered commits. Intermediate
commits may not compile — this is inherent to an atomic major-version migration — and the work
lands as a single reviewable PR gated on e2e smoke before merge:

1. Dependency pin adjustments (see "Dependency changes").
2. Codegen switch in `build.rs` + regenerate `src/grpc/joysafeter.rs`.
3. Transport/TLS API adaptation across the three servers.
4. envoy-types unification (0.5.1→0.7.6) + `src/xds/compiler.rs` simplification.
5. Remove the dual-pin remnants; `cargo build` green.

## Dependency changes (`Cargo.toml`)

- `tonic = { version = "0.12", features = ["tls"] }` → `{ version = "0.14", features = ["tls-aws-lc"] }`.
  The bundled `tls` feature was reworked in 0.13+ into `tls-ring` / `tls-aws-lc`; this crate uses
  aws-lc-rs (`main.rs` installs the aws_lc_rs default `CryptoProvider`), so `tls-aws-lc`.
- `prost = "0.13"` → `"0.14"`; `prost-types = "0.13"` → `"0.14"`.
- Remove `prost14 = { package = "prost", version = "0.14" }` (prost becomes single).
- Remove `envoy-types = "=0.5.1"`; rename `envoy-types-v076 = { package = "envoy-types",
  version = "=0.7.6" }` back to `envoy-types = "=0.7.6"`.
- build-deps: `tonic-build = "0.12"` → `"0.14"`, and **add `tonic-prost-build = "0.14"`**
  (0.14 split prost codegen out of `tonic-build` into `tonic-prost-build`).
- May need an explicit runtime `tonic-prost` dependency (generated code's `ProstCodec` moved
  to that crate; already present in the tree via envoy-types 0.7.6).

## Code generation (`build.rs` + generated output)

`build.rs` currently calls
`tonic_build::configure().build_server(true).build_client(false).out_dir(<src/grpc>).compile_protos(...)`.
In 0.14 the prost compilation moves to **`tonic_prost_build::configure()`** for `compile_protos`.
Regenerate the checked-in `src/grpc/joysafeter.rs`, review its diff (notably the `ProstCodec`
path change), and include it in the commit.

## Transport / TLS API adaptation (three servers)

Files: `src/xds_server.rs`, `src/kernel/ext_authz.rs`, `src/grpc/server.rs`.

APIs in use that must be re-validated against tonic 0.14 signatures: `Server::builder`,
`ServerTlsConfig`, `Identity::from_pem`, `Certificate::from_pem`, `.client_ca_root()`,
`.tls_config()`, `InterceptedService`, `#[tonic::async_trait]`,
`Request` / `Response` / `Status` / `Streaming`, and the keepalive / message-size limit
builders. These are largely stable across 0.12→0.14, but **each call site must be verified
against the actual 0.14 API** (especially the TLS type paths and the behavior after the feature
rename). Exact signatures are pinned during the writing-plans phase; this spec only fixes the
surface that needs adaptation. Keep `main.rs`'s
`rustls::crypto::aws_lc_rs::default_provider().install_default()`.

## envoy-types unification (0.5.1 → 0.7.6)

**Do this systematically, not compiler-error-driven.** Before editing, enumerate the actual
type-surface differences between envoy-types 0.5.1 and 0.7.6 for the specific `pb::envoy::...`
messages this crate constructs — identify which Envoy API snapshot each version targets and
which fields/enums changed — and record the delta. Then apply the fixes as one deliberate pass
per message family. Fixing `error[E0560]: no field X` one at a time (a band-aid) is explicitly
disallowed by the approach principles above; it hides whether a field was renamed (safe) versus
removed/semantically changed (a behavior risk).

Consumers to migrate:

- `src/sandbox/lds_backend.rs` — the largest consumer (ADS impl + listener/cluster/route/filter
  constructors). `pb::envoy::...` module paths are largely stable, but 0.5.1 and 0.7.6 track
  different Envoy API snapshots, so **explicit struct literals may need field fixes**;
  `..Default::default()` sites are safer. Align each divergence by class, not by error.
- `src/kernel/ext_authz.rs` — `service::auth::v3` types recompiled against 0.7.6.
- `src/grpc/server.rs`, `src/xds_server.rs` — ADS/auth server wrappers recompiled.
- `src/xds/compiler.rs` **simplifies**: `use prost14::Message` → `use prost::Message`; remove
  the 7 `#[prost(prost_path = "prost14")]` overrides (fall back to the default `::prost`).

## Verification and merge gate

**Local:** `cargo build` + the in-file `#[cfg(test)]` suites in `xds_server.rs`,
`kernel/ext_authz.rs`, `sandbox/lds_backend.rs`, and `src/xds/*`, plus the egress-controller
Go/Rust compiler parity test.

**Merge gate (required):** both e2e egress smokes pass —
- Docker plane: `deploy/egress-compose-smoke.sh`
- K3s plane: `deploy/k8s/k3s-egress-smoke.sh`

These prove the real-Envoy → ADS/ext_authz allow/deny path is unchanged after the migration.
If func-e / Envoy cannot be downloaded on the local macOS host, explicitly mark those smokes as
"CI / capable-environment only" and do NOT report them as passing — no fabricated green.

## Risks and rollback

**Primary risk:** the §"envoy-types unification" proto-snapshot field differences causing a
compile or semantic drift. **Mitigation:** before and after the migration, compile the same
policy fixture and byte-compare the produced LDS/RDS/CDS protobuf `Any` bytes to prove the wire
output is unchanged.

**Rollback:** the whole migration is one isolated branch/PR; it does not merge until both e2e
smokes pass. Because it lands atomically, rollback is simply not merging (or reverting) that
single PR.

## Payoff

After unification, the `prost14` rename, the dual `envoy-types` pins, and the
`#[prost(prost_path = "prost14")]` overrides in `compiler.rs` all disappear, and build time /
binary size drop because the crate no longer compiles two tonic/prost stacks at once.
