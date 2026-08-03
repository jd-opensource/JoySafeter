# tonic 0.14 / envoy-types Unification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the deliberate dual-`envoy-types` state (0.5.1 runtime + 0.7.6 compile-time via the `prost14` rename) in `backend/app/joysafeter_orchestrator_rs` by unifying the crate onto tonic 0.14 / prost 0.14 / envoy-types 0.7.6, with zero runtime behavior change.

**Architecture:** An atomic dependency-and-API migration. Because `src/grpc/server.rs` registers the runner AgentBridge, ADS, and ext_authz services on one `tonic::transport::Server` (and tonic forbids mixing major versions on one builder), the runtime services plus the two standalone servers (`src/xds_server.rs`, `src/kernel/ext_authz.rs`) migrate together. Equivalence is proven by byte-comparing compiled xDS resources before/after and by the docker + k3s e2e egress smokes.

**Tech Stack:** Rust, tonic 0.14, prost 0.14, tonic-prost-build 0.14, envoy-types 0.7.6, rustls (aws-lc-rs), Envoy Delta xDS/ADS + ext_authz, Docker Compose, k3s/k3d.

## Global Constraints

- **Execution precondition:** Do NOT start until the node-local Envoy + Rust xDS rewrite (`docs/superpowers/specs/2026-08-03-node-local-envoy-rust-xds-rewrite.md`) has passed its live production cutover verification. This plan is written ahead of time.
- **envoy-types pinned to `=0.7.6`** — do not chase a newer version.
- **No behavior change** — gRPC wire protocol, mTLS semantics, and xDS/ext_authz allow/deny logic stay identical. Proven by evidence, never assumed from "it compiles."
- **No compatibility shims** — no dual-server, no dual-stack "for now," no `#[allow]` papering, no local re-export shims. The new stack is the only stack.
- **Systematic root-cause, fix-by-class** — for the envoy-types type-surface changes, enumerate the diff up front (Task 2) and fix each class uniformly; fixing `error[E0560]` one at a time as the compiler surfaces them is disallowed.
- **Isolation:** all work on a dedicated worktree/branch; lands as ONE PR gated on both e2e smokes.
- **Crate dir:** every `cargo`/path command runs from `backend/app/joysafeter_orchestrator_rs` unless noted. Repo root is the git root.
- **Non-compiling window (read this):** After Task 3 bumps the deps, the crate does **not** compile until Task 6 finishes. This is inherent to an atomic tonic major bump — there is no intermediate green build. Tasks 3–6 are verified by *error-class reduction* (the expected remaining error categories shrink task by task); the authoritative `cargo build` + unit-test green gate is **Task 7**. Do not fake per-task green in this window.

---

## File Structure

Files touched, by responsibility:

- `backend/app/joysafeter_orchestrator_rs/Cargo.toml` — dependency pins (tonic/prost/envoy-types, build-deps).
- `backend/app/joysafeter_orchestrator_rs/build.rs` — codegen switch to `tonic_prost_build`.
- `backend/app/joysafeter_orchestrator_rs/src/grpc/joysafeter.rs` — regenerated gRPC stubs (checked-in output).
- `backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs` — shared tonic server (AgentBridge + ADS + ext_authz) transport/API adaptation.
- `backend/app/joysafeter_orchestrator_rs/src/xds_server.rs` — standalone K8s-plane ADS server transport/TLS.
- `backend/app/joysafeter_orchestrator_rs/src/kernel/ext_authz.rs` — standalone K8s-plane ext_authz server transport/TLS + `service::auth::v3` types.
- `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs` — largest envoy-types consumer (ADS impl + resource builders).
- `backend/app/joysafeter_orchestrator_rs/src/xds/compiler.rs` — drop `prost14` rename + the 7 `#[prost(prost_path = "prost14")]` overrides.
- `backend/app/joysafeter_orchestrator_rs/src/main.rs` — keep the aws-lc-rs `CryptoProvider` install; adapt any transport wiring.
- `docs/superpowers/notes/2026-08-03-envoy-types-0.5.1-to-0.7.6-typediff.md` — **new**, the systematic type-surface delta (Task 2 deliverable).
- `backend/app/joysafeter_orchestrator_rs/tests/xds_resource_equivalence.rs` — **new**, the before/after protobuf-`Any` byte-diff equivalence oracle.

---

## Task 0: Isolate the workspace and capture the baseline build fingerprint

**Files:**
- None modified (branch/worktree + captured artifacts only).

**Interfaces:**
- Produces: a clean baseline branch; `cargo tree` and `cargo build` baseline logs for later comparison.

- [ ] **Step 1: Create the isolated worktree/branch**

Run (from repo root):
```bash
git worktree add .worktrees/tonic-014 -b chore/tonic-014-envoy-types-unification
cd .worktrees/tonic-014/backend/app/joysafeter_orchestrator_rs
```
Expected: new worktree created on branch `chore/tonic-014-envoy-types-unification`.

- [ ] **Step 2: Confirm the pre-migration dual-version state**

Run:
```bash
cargo tree -i envoy-types 2>/dev/null || grep -n 'name = "envoy-types"' Cargo.lock
```
Expected: both `envoy-types 0.5.1` and `envoy-types 0.7.6` present.

- [ ] **Step 3: Capture a green baseline (build + unit tests)**

Run:
```bash
cargo build 2>&1 | tee /tmp/tonic-baseline-build.log
cargo test --no-run 2>&1 | tee /tmp/tonic-baseline-testbuild.log
```
Expected: both succeed on the pre-migration tree. This is the "known good" reference.

- [ ] **Step 4: Commit a marker (empty) so the branch point is explicit**

```bash
git commit --allow-empty -m "chore: begin tonic 0.14 / envoy-types unification"
```

---

## Task 1: Add the xDS resource equivalence oracle (golden bytes on the CURRENT stack)

This is the only genuinely test-first task: capture golden compiled-resource bytes on the pre-migration tree so Task 7 can prove the migration changed nothing on the wire. It builds on the existing deterministic `encode_to_vec()` test in `src/xds/compiler.rs`.

**Files:**
- Create: `backend/app/joysafeter_orchestrator_rs/tests/xds_resource_equivalence.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/tests/fixtures/xds_golden/` (golden `.bin` files)
- Reference: `src/xds/compiler.rs` (`compile_kubernetes`, `compile_for_provider`, existing test `compiles_deterministic_lds_rds_cds_without_secret_values`)

**Interfaces:**
- Consumes: `joysafeter_orchestrator::xds::compiler::{compile_kubernetes, compile_for_provider, CompileInput, CompilerConfig}` (verify exact exported paths with `grep -n 'pub fn compile' src/xds/compiler.rs`).
- Produces: golden fixture files `tests/fixtures/xds_golden/<case>.bin` and a test `xds_resource_bytes_match_golden` that other tasks must keep green.

- [ ] **Step 1: Write the equivalence test that DUMPS golden bytes when missing and asserts equality when present**

Create `tests/xds_resource_equivalence.rs`:
```rust
//! Proves the compiled xDS resource bytes are byte-identical across the
//! tonic/envoy-types migration. Run once on the pre-migration tree to write
//! the golden fixtures; the post-migration tree must reproduce them exactly.
use std::path::PathBuf;

use joysafeter_orchestrator::xds::compiler::{self, CompileInput, CompilerConfig};
// NOTE: adjust the import path/args to match the actual public signature —
// verify with: grep -n "pub fn compile_kubernetes" src/xds/compiler.rs

fn golden_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/xds_golden")
}

/// Deterministically serialize a compiled snapshot to bytes.
/// Reuse the same encode_to_vec() path the in-module test uses.
fn encode_case(case: &str) -> Vec<u8> {
    let config = CompilerConfig::from_env(vec!["169.254.0.0/16".to_string()])
        .expect("compiler config");
    let input = fixture_input(case); // build a fixed CompileInput for `case`
    let snapshot = compiler::compile_kubernetes(&config, &input).expect("compile");
    snapshot.encode_to_vec()
}

fn fixture_input(case: &str) -> CompileInput<'static> {
    // Build a FIXED, secret-free policy input for the named case.
    // Mirror the inputs already constructed in src/xds/compiler.rs tests
    // (compiles_deterministic_lds_rds_cds_without_secret_values).
    match case {
        "kubernetes-basic" => todo_build_basic_input(),
        other => panic!("unknown case {other}"),
    }
}

fn check(case: &str) {
    let got = encode_case(case);
    let path = golden_dir().join(format!("{case}.bin"));
    if std::env::var("UPDATE_XDS_GOLDEN").is_ok() || !path.exists() {
        std::fs::create_dir_all(golden_dir()).unwrap();
        std::fs::write(&path, &got).unwrap();
        return;
    }
    let want = std::fs::read(&path).expect("golden fixture");
    assert_eq!(got, want, "compiled xDS bytes for `{case}` changed");
}

#[test]
fn xds_resource_bytes_match_golden() {
    check("kubernetes-basic");
}
```

> Implementer note: `todo_build_basic_input()` is a placeholder name for the fixed input builder — copy the concrete `CompileInput` construction from the existing `compiles_deterministic_lds_rds_cds_without_secret_values` test in `src/xds/compiler.rs` so the case is real and secret-free. Do not ship the `todo_` name.

- [ ] **Step 2: Generate the golden fixtures on the pre-migration tree**

Run:
```bash
UPDATE_XDS_GOLDEN=1 cargo test --test xds_resource_equivalence -- --nocapture
```
Expected: PASS; `tests/fixtures/xds_golden/kubernetes-basic.bin` created.

- [ ] **Step 3: Re-run without the update flag to confirm it now guards**

Run:
```bash
cargo test --test xds_resource_equivalence
```
Expected: PASS (bytes match the just-written golden).

- [ ] **Step 4: Commit the oracle + golden bytes (captured on the OLD stack)**

```bash
git add tests/xds_resource_equivalence.rs tests/fixtures/xds_golden/
git commit -m "test(xds): add compiled-resource byte-equivalence oracle with pre-migration golden"
```

---

## Task 2: Enumerate the envoy-types 0.5.1 → 0.7.6 type-surface diff (systematic root-cause, no code change)

Honors the "遇到问题体系化分析根因 / 禁止小修小补" directive: understand every type change up front, as its own reviewable deliverable, before touching call sites.

**Files:**
- Create: `docs/superpowers/notes/2026-08-03-envoy-types-0.5.1-to-0.7.6-typediff.md`

**Interfaces:**
- Produces: a per-message-family delta table that Task 6 consumes to fix by class.

- [ ] **Step 1: List every envoy-types type this crate constructs**

Run (from crate dir):
```bash
grep -rhoE 'envoy_types::pb::[a-zA-Z0-9_:]+' src | sort -u
```
Expected: the full set of `pb::envoy::...` paths (listener/cluster/route/core/auth/ext_authz/tls types).

- [ ] **Step 2: Diff the generated type surface between the two versions**

For each version, locate the generated source and compare the structs/enums for the paths from Step 1:
```bash
find ~/.cargo/registry/src -maxdepth 2 -type d -name 'envoy-types-0.5.1' -o -name 'envoy-types-0.7.6'
```
For each type family (Listener, Cluster, RouteConfiguration, Filter chains, ext_authz/auth v3, TLS transport sockets), record in the note: fields **added**, **removed**, **renamed**, or **retyped**, and the Envoy API snapshot each version tracks.

- [ ] **Step 3: Classify each delta as SAFE (rename/added-optional) or RISK (removed/retyped/semantic)**

Write the note with one row per changed type: `path | change | safe/risk | action`. RISK rows get an explicit equivalence argument (why the byte output is unchanged, referencing Task 1's oracle).

- [ ] **Step 4: Commit the analysis**

```bash
git add docs/superpowers/notes/2026-08-03-envoy-types-0.5.1-to-0.7.6-typediff.md
git commit -m "docs(xds): enumerate envoy-types 0.5.1->0.7.6 type-surface delta"
```

---

## Task 3: Bump the dependency stack (enters the non-compiling window)

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/Cargo.toml` (deps block ~lines 19-37; build-deps ~line 118)

**Interfaces:**
- Produces: the unified single-version dependency graph. Build is expected to break here; that is correct.

- [ ] **Step 1: Edit the `[dependencies]` gRPC block**

Change:
```toml
tonic = { version = "0.12", features = ["tls"] }
prost = "0.13"
prost-types = "0.13"
prost14 = { package = "prost", version = "0.14" }
```
to:
```toml
tonic = { version = "0.14", features = ["tls-aws-lc"] }
prost = "0.14"
prost-types = "0.14"
tonic-prost = "0.14"
```
And change the envoy-types pins:
```toml
envoy-types = "=0.5.1"
envoy-types-v076 = { package = "envoy-types", version = "=0.7.6" }
```
to:
```toml
envoy-types = "=0.7.6"
```

- [ ] **Step 2: Edit `[build-dependencies]`**

Change:
```toml
[build-dependencies]
tonic-build = "0.12"
```
to:
```toml
[build-dependencies]
tonic-build = "0.14"
tonic-prost-build = "0.14"
```

- [ ] **Step 3: Regenerate the lockfile and confirm single-version**

Run:
```bash
cargo update -p tonic --precise 0.14.6 2>/dev/null; cargo generate-lockfile
grep -c 'name = "envoy-types"' Cargo.lock
```
Expected: `1` (only 0.7.6 remains). If `tonic-prost` turns out unused after codegen (Task 4), remove it in Task 7 cleanup.

- [ ] **Step 4: Confirm the build now fails on codegen/API, not on resolution**

Run:
```bash
cargo build 2>&1 | tail -30
```
Expected: dependency resolution succeeds; compilation FAILS (build.rs codegen and/or tonic API mismatches). This is the expected entry into the non-compiling window.

- [ ] **Step 5: Commit the dependency change**

```bash
git add Cargo.toml Cargo.lock
git commit -m "build: bump orchestrator to tonic 0.14 / prost 0.14 / envoy-types 0.7.6 (WIP: build broken)"
```

---

## Task 4: Switch codegen to tonic-prost-build and regenerate the gRPC stubs

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/build.rs`
- Regenerate: `backend/app/joysafeter_orchestrator_rs/src/grpc/joysafeter.rs`

**Interfaces:**
- Consumes: `proto/joysafeter.proto` (unchanged).
- Produces: regenerated `AgentBridgeServer` stubs compiled against tonic 0.14 / `tonic-prost` `ProstCodec`.

- [ ] **Step 1: Update `build.rs` to use `tonic_prost_build` for proto compilation**

Change the codegen call from:
```rust
tonic_build::configure()
    .build_server(true)
    .build_client(false)
    .out_dir(manifest_dir.join("src").join("grpc"))
    .compile_protos(&[&proto_file], &[&proto_dir])?;
```
to:
```rust
tonic_prost_build::configure()
    .build_server(true)
    .build_client(false)
    .out_dir(manifest_dir.join("src").join("grpc"))
    .compile_protos(&[&proto_file], &[&proto_dir])?;
```
> If a builder method name changed in 0.14, run `cargo doc -p tonic-prost-build --open` and match the actual `configure()` builder API; do not guess.

- [ ] **Step 2: Force regeneration of the checked-in stub**

Run:
```bash
touch build.rs proto/joysafeter.proto
cargo build 2>&1 | grep -E 'joysafeter\.rs|ProstCodec|tonic_prost' | head
```
Expected: `src/grpc/joysafeter.rs` is rewritten; remaining errors no longer reference codegen/`ProstCodec`. (Errors in the three servers and envoy-types sites still remain — expected.)

- [ ] **Step 3: Review the regenerated stub diff**

Run:
```bash
git --no-pager diff src/grpc/joysafeter.rs | head -80
```
Expected: only the `ProstCodec`/import path changes (0.12→0.14), no proto message shape changes.

- [ ] **Step 4: Commit codegen switch + regenerated stub**

```bash
git add build.rs src/grpc/joysafeter.rs
git commit -m "build: generate gRPC stubs with tonic-prost-build 0.14 (WIP: build broken)"
```

---

## Task 5: Adapt the transport/TLS API across the three servers

**Files:**
- Modify: `src/xds_server.rs` (~lines 5-76)
- Modify: `src/kernel/ext_authz.rs` (~lines 26-39, 332-351)
- Modify: `src/grpc/server.rs` (~lines 16, 7194-7245)
- Modify: `src/main.rs` (keep aws-lc-rs provider install; adapt any transport wiring)

**Interfaces:**
- Consumes: tonic 0.14 `transport` API.
- Produces: three servers building against tonic 0.14 (envoy-types type errors may still remain — resolved in Task 6).

- [ ] **Step 1: Verify the 0.14 transport/TLS API surface before editing**

Run:
```bash
cargo doc -p tonic --no-deps 2>/dev/null; \
grep -RnoE 'ServerTlsConfig|Identity::from_pem|Certificate::from_pem|client_ca_root|tls_config|InterceptedService|async_trait|max_(de|en)coding_message_size' src | sort -u
```
Confirm each symbol's 0.14 path/signature (TLS types may live behind the `tls-aws-lc` feature; `Certificate`/`Identity` constructors and `client_ca_root` may have moved). Record any moved path.

- [ ] **Step 2: Fix `src/xds_server.rs` imports and TLS builder calls**

Update the `use tonic::transport::{...}` line and the `ServerTlsConfig::new().identity(Identity::from_pem(...)).client_ca_root(Certificate::from_pem(...))` chain to the 0.14 equivalents found in Step 1. Keep behavior identical (mTLS, client-CA, DNS-SAN interceptor, keepalive, message limits, stream cap).

- [ ] **Step 3: Fix `src/kernel/ext_authz.rs` transport imports and TLS builder calls**

Apply the same transport/TLS adjustments to the standalone ext_authz server builder (~line 332) and its `use tonic::transport::{...}` (~line 38).

- [ ] **Step 4: Fix `src/grpc/server.rs` shared-server wiring**

Update the `use tonic::{...}` (~line 16) and the `tonic::transport::Server::builder()...add_service(svc).add_service(ads).add_service(ext_authz_svc).serve(addr)` block (~line 7220) to the 0.14 API. The three services stay on the ONE builder.

- [ ] **Step 5: Confirm transport errors are gone; only envoy-types type errors remain**

Run:
```bash
cargo build 2>&1 | grep -E 'error\[' | grep -vE 'lds_backend|xds/compiler|envoy_types|pb::envoy' | head
```
Expected: no non-envoy-types compile errors remain (empty or only envoy-types-related). Transport/TLS/codegen classes resolved.

- [ ] **Step 6: Commit transport adaptation**

```bash
git add src/xds_server.rs src/kernel/ext_authz.rs src/grpc/server.rs src/main.rs
git commit -m "refactor(grpc): adapt three tonic servers to the 0.14 transport/TLS API (WIP: build broken)"
```

---

## Task 6: Unify envoy-types on 0.7.6 and simplify the compiler (fix by class, per Task 2)

**Files:**
- Modify: `src/sandbox/lds_backend.rs`
- Modify: `src/kernel/ext_authz.rs` (`service::auth::v3` type sites)
- Modify: `src/grpc/server.rs`, `src/xds_server.rs` (ADS/auth server wrappers)
- Modify: `src/xds/compiler.rs`

**Interfaces:**
- Consumes: the Task 2 delta table (SAFE vs RISK per type family).
- Produces: the crate compiling on the unified stack.

- [ ] **Step 1: Simplify `src/xds/compiler.rs` — drop the prost14 rename**

Change `use prost14::Message;` to `use prost::Message;`, and remove every `#[prost(prost_path = "prost14")]` attribute (7 sites; locate with `grep -n 'prost_path = "prost14"' src/xds/compiler.rs`). The default `::prost` now resolves to 0.14.

- [ ] **Step 2: Apply the envoy-types fixes by class, driven by the Task 2 note**

For each type family in the delta note, apply the same fix across all its call sites in `lds_backend.rs` / `ext_authz.rs` / server wrappers in one pass. Do NOT fix errors one-by-one; work family-by-family. For any RISK row, keep the exact same field values (an added optional field stays `None`/default; a rename maps 1:1).

- [ ] **Step 3: Build until green**

Run:
```bash
cargo build 2>&1 | tail -20
```
Expected: `Finished` — the crate compiles on the unified stack. If new error classes appear, return to the Task 2 note and extend it (root-cause), do not patch ad hoc.

- [ ] **Step 4: Confirm the dual version is gone**

Run:
```bash
grep -c 'name = "envoy-types"' Cargo.lock; grep -rn 'prost14\|prost_path' src || echo "no prost14 remnants"
```
Expected: `1` and "no prost14 remnants".

- [ ] **Step 5: Commit the unification**

```bash
git add src/sandbox/lds_backend.rs src/kernel/ext_authz.rs src/grpc/server.rs src/xds_server.rs src/xds/compiler.rs
git commit -m "refactor(xds): unify envoy-types on 0.7.6 and drop the prost14 compile-time baseline"
```

---

## Task 7: Green gate — unit tests + byte-equivalence + Go/Rust parity

**Files:**
- None (verification), plus any `tonic-prost` prune in `Cargo.toml` if unused.

**Interfaces:**
- Consumes: Task 1's golden fixtures (captured on the OLD stack).

- [ ] **Step 1: Run the full crate test suite**

Run:
```bash
cargo test 2>&1 | tail -30
```
Expected: PASS, including the in-file `#[cfg(test)]` suites in `xds_server.rs`, `kernel/ext_authz.rs`, `sandbox/lds_backend.rs`, and `src/xds/*`.

- [ ] **Step 2: Run the equivalence oracle WITHOUT the update flag (the migration must not change bytes)**

Run:
```bash
cargo test --test xds_resource_equivalence
```
Expected: PASS — compiled xDS resource bytes are byte-identical to the pre-migration golden. If it FAILS, that is a real behavior change: diff the resources, root-cause via the Task 2 note, and fix by class. Do NOT regenerate the golden to make it pass.

- [ ] **Step 3: Run the egress-controller Go/Rust compiler parity test**

Run (from repo root):
```bash
cd egress-controller && go test ./internal/compiler/... ./internal/group/...
```
Expected: PASS — parity fixtures still match.

- [ ] **Step 4: Prune `tonic-prost` if the regenerated code did not reference it**

Run (crate dir):
```bash
grep -rn 'tonic_prost' src/grpc/joysafeter.rs || echo "unused"
```
If "unused", remove `tonic-prost` from `Cargo.toml`, `cargo build` again to confirm green, and amend/commit.

- [ ] **Step 5: Commit the green gate marker**

```bash
git commit --allow-empty -m "test: tonic 0.14 unification passes unit + byte-equivalence + parity"
```

---

## Task 8: e2e egress smokes (merge gate — docker + k3s)

Both must pass before the PR merges. If Envoy/func-e cannot run on the local host, mark the blocked smoke "CI / capable-environment only" and do NOT report it as passing.

**Files:**
- None (runs `deploy/` smokes).

- [ ] **Step 1: Build the orchestrator image from the migrated branch**

Run the repo's standard image build for the orchestrator (per `deploy/deploy.sh` / compose build). Expected: image builds from the tonic-0.14 tree.

- [ ] **Step 2: Run the docker-plane egress smoke**

Run (repo root):
```bash
bash deploy/egress-compose-smoke.sh
```
Expected: real Envoy comes up, ADS/ext_authz allow/deny path exercised, script reports success. (Check the script header for required env like an Anthropic key/base URL.)

- [ ] **Step 3: Run the k3s-plane egress smoke**

Run (repo root), providing the env the script needs (`API_URL`/port-forwards, `ANTHROPIC_MODEL`, k3d cluster; see the script header):
```bash
bash deploy/k8s/k3s-egress-smoke.sh
```
Expected: `EXPECTED_OUTPUT_FRAGMENT` (`K3S_EGRESS_OK`) observed; node-local Envoy → Rust ADS/ext_authz path works on the migrated build.

- [ ] **Step 4: Record smoke evidence in the PR and open it**

Paste both smokes' final status into the PR description. If either could not run locally, state exactly which and why (e.g., Envoy download blocked on macOS) and mark it CI-only — no fabricated green. Open the PR; it merges only when both smokes are green (locally or in CI).

---

## Self-Review (completed at authoring)

- **Spec coverage:** §1 goal/non-goals → Global Constraints + Task scoping; §2 atomic ordering → Tasks 3–6 + non-compiling-window note; §3 deps → Task 3; §4 codegen → Task 4; §5 transport/TLS → Task 5; §6 envoy-types + compiler → Task 6; §7 verification/merge gate → Tasks 7–8; §8 risks/rollback → Task 1 oracle + Task 7 Step 2 + PR-not-merged rollback; Approach principles → Task 2 (up-front diff) + Task 6 fix-by-class + "no fake green" gates.
- **Placeholder scan:** the only intentional placeholder is `todo_build_basic_input()` in Task 1, explicitly flagged to be replaced by copying the existing in-module test's input construction; all other steps carry concrete commands/code.
- **Type consistency:** `compile_kubernetes`/`compile_for_provider`/`CompileInput`/`CompilerConfig` are used consistently between Task 1 and Task 6 and flagged for signature verification against `src/xds/compiler.rs`; golden test name `xds_resource_bytes_match_golden` and file `tests/xds_resource_equivalence.rs` are referenced consistently in Tasks 1 and 7.
