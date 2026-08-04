# Docker E2E Verification (func-e + compose smoke) Implementation Plan

> **Historical / superseded (2026-08-04):** This plan targets the deleted
> independent Go xDS controller. Current Docker verification uses embedded Rust
> ADS; see `../specs/2026-08-03-node-local-envoy-rust-xds-rewrite.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the unified egress architecture two CI-runnable, tamper-evident real-Envoy tests: (C-1) a `func-e` Go test proving the Go controller's compiled xDS is *accepted and ACKed by a real Envoy*, and (C-2) a Docker compose egress smoke proving a sandbox's egress traverses the controller-driven Envoy with credential injection — both against a **mock upstream, no real API key**.

**Architecture:** C-1 runs entirely in the Go test process: start the controller's `SnapshotCache` (file source, plaintext xDS) serving a compiled docker/k8s snapshot, boot a real Envoy via `func-e run` pointed at it, poll Envoy admin `/config_dump` + `/stats` to assert the expected listeners/clusters/routes are present and ACKed. C-2 brings up the unified compose stack (controller `SOURCE=postgres` + Docker Envoy in `controller` mode + orchestrator ext_authz + a sandbox + a mock upstream container) and asserts the four cross-correlated evidence sources.

**Tech Stack:** Go 1.26.5 + `github.com/tetratelabs/func-e` (new test dep), Envoy v1.39.0 (pinned digest, downloaded by func-e or pulled by compose), docker compose, bash, Postgres, `curl`/`jq`.

## Global Constraints

- **Prereq: Plan 1 is merged/landed** (commits `bb2ec45d..96920772`) — C-2 depends on the Docker `controller` xDS mode and the Go docker control-listener existing.
- **No real API key anywhere.** Both tests use a **mock upstream** (a tiny HTTP echo container/handler) as the credential-route target. The real-model round-trip stays the operator's local smoke, out of scope.
- **Tamper-evident, multi-source (user's "真实链路 不是伪造" bar).** C-2 must assert from ≥3 independent sources that cannot all be trivially forged by the test: (a) Envoy admin `/config_dump`+`/stats`, (b) Postgres `joysafeter_egress_apply_status` (`state=applied`, `acked_acks=required_acks`, 0 NACK), (c) data-plane behavior (correct token → mock upstream sees the injected header; wrong/no token → ext_authz 403; direct-to-upstream from sandbox → denied; sandbox env/`config` has no real secret), cross-correlated by Envoy access-log `x-request-id`.
- **Envoy version pinned** to `v1.39.0` (match `deploy/docker-compose.yml` digest and the controller's `envoy_version` node metadata `1.39.0`). func-e must be pinned to that Envoy version via `FUNC_E_ENVOY_VERSION` / its version file.
- **Gate every task yourself:** `export PATH="/opt/homebrew/bin:$PATH"`; Go = `go test -race ./...` + `gofmt -l .`; compose = `docker compose config` then the smoke script; never claim green without the command output.
- Go is installed (go1.26.5, `/opt/homebrew/bin`). `GOTOOLCHAIN=auto`.

---

## File Structure

- `egress-controller/internal/xds/realenvoy_test.go` (Create) — the `func-e` real-Envoy acceptance test, build-tagged `//go:build realenvoy` so it doesn't run in the default `go test` (needs network + Envoy download). Runs in a dedicated CI step.
- `egress-controller/go.mod` / `go.sum` (Modify) — add `github.com/tetratelabs/func-e` test dependency.
- `egress-controller/internal/xds/testdata/realenvoy-bootstrap.yaml` (Create) — Envoy bootstrap: ADS (plaintext) → in-test controller `xds_cluster`, admin on `127.0.0.1:0` (ephemeral) or a fixed loopback port.
- `deploy/mock-upstream/` (Create) — a tiny mock upstream (a 20-line Go or `mendhak/http-https-echo` image) that echoes received headers so the smoke can prove the platform header was injected.
- `deploy/docker-compose.egress-smoke.yml` (Create) — a compose overlay adding the mock upstream + a sandbox runner wired for `controller` mode.
- `deploy/egress-compose-smoke.sh` (Create) — the C-2 smoke driver (bring up, seed a secret+env+sandbox, run the four-source assertions, teardown).
- `.github/workflows/ci.yml` (Modify) — add a `realenvoy` Go step to the egress-controller job; add a `docker-egress-smoke` job (per PR).

---

### Task 1: func-e real-Envoy xDS acceptance test (C-1)

**Files:**
- Create: `egress-controller/internal/xds/realenvoy_test.go` (build tag `//go:build realenvoy`)
- Create: `egress-controller/internal/xds/testdata/realenvoy-bootstrap.yaml`
- Modify: `egress-controller/go.mod`, `go.sum`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `internal/compiler.Compiler` + `internal/snapshot.BuildCompiled` (existing) to produce a `cachev3.Snapshot`; `internal/xds` server (existing SnapshotCache + gRPC ADS).
- Produces: a CI-gated test proving a real Envoy ACKs the compiled snapshot.

- [ ] **Step 1: Pin func-e + add the dependency**

Run: `cd egress-controller && GOTOOLCHAIN=auto go get github.com/tetratelabs/func-e@latest` (then record the resolved version). Verify the API you will call by reading its `api` package (`funcE.Run(ctx, []string{"run","-c",bootstrapPath}, api.HomeDir(tmp), api.EnvoyVersion("1.39.0"), api.Out(w), api.Err(w))` — confirm exact signatures against the fetched version; do not guess).

- [ ] **Step 2: Write the failing test**

Create `realenvoy_test.go` (build-tagged). Skeleton (fill exact func-e call from Step 1):

```go
//go:build realenvoy

package xds_test

// TestRealEnvoyAcceptsCompiledDockerSnapshot:
// 1. Compile a docker desired-generation (reuse compiler test fixture) into a Snapshot.
// 2. Start the xDS gRPC server (plaintext) on an ephemeral port with that snapshot in a SnapshotCache keyed by the group.
// 3. Render testdata/realenvoy-bootstrap.yaml with node metadata (the 7 fields incl host_id) + the xds_cluster address = the ephemeral port.
// 4. funcE.Run("run","-c",bootstrap) with EnvoyVersion 1.39.0, admin on 127.0.0.1:<adminPort>.
// 5. Poll http://127.0.0.1:<adminPort>/config_dump until the expected listener names appear (joysafeter_<sandbox>_http and _grpc) OR timeout.
// 6. Assert: config_dump contains both listeners + the ext_authz filter on _http and NOT on _grpc; /stats shows control_plane.connected_state==1 (ACK). No secret string in the dump.
// 7. Shut down Envoy + server.
```

- [ ] **Step 3: Run to verify it fails (RED)**

Run: `cd egress-controller && go test -tags=realenvoy ./internal/xds -run TestRealEnvoyAcceptsCompiledDockerSnapshot -v`
Expected: FAIL (test/function not implemented, or Envoy not yet wired).

- [ ] **Step 4: Implement until GREEN**

Wire steps 1-7. Reuse `compiler` + `snapshot` to build the snapshot and the existing `xds` server constructor (read `internal/xds/server.go` + `manager.go` for how to start it with mTLS disabled). Assert on `/config_dump` JSON (parse with `encoding/json`, walk `configs[].dynamic_listeners`).

Run: `cd egress-controller && go test -tags=realenvoy ./internal/xds -run TestRealEnvoyAcceptsCompiledDockerSnapshot -v`
Expected: PASS. Also `gofmt -l .` clean; `go test -race ./...` (default, no tag) still green.

- [ ] **Step 5: Add the CI step**

In `.github/workflows/ci.yml`, extend the `egress-controller` job with a step after the unit tests:
```yaml
      - name: Real-Envoy xDS acceptance (func-e)
        working-directory: egress-controller
        run: go test -tags=realenvoy ./internal/xds -run TestRealEnvoy -v
```
(func-e downloads Envoy at runtime; ensure the job has network. Cache func-e's home dir if the runner supports it.)

- [ ] **Step 6: Commit**

```bash
git add egress-controller/go.mod egress-controller/go.sum \
        egress-controller/internal/xds/realenvoy_test.go \
        egress-controller/internal/xds/testdata/realenvoy-bootstrap.yaml \
        .github/workflows/ci.yml
git commit -m "test(egress-controller): real-Envoy xDS acceptance via func-e (CI-gated)"
```

---

### Task 2: Docker compose egress smoke (C-2)

**Files:**
- Create: `deploy/mock-upstream/` (Dockerfile + tiny echo server, or pin `mendhak/http-https-echo`)
- Create: `deploy/docker-compose.egress-smoke.yml` (overlay: mock upstream + sandbox in controller mode)
- Create: `deploy/egress-compose-smoke.sh`
- Modify: `.github/workflows/ci.yml` (add `docker-egress-smoke` job)

**Interfaces:**
- Consumes: Plan 1's compose controller-mode wiring (`JOYSAFETER_ENVOY_XDS_MODE=controller`, `POLICY_AUTHORITY_ENABLED=true`, `CONTROLLER_SOURCE=postgres`).
- Produces: a reproducible smoke emitting the four-source cross-correlated proof.

- [ ] **Step 1: Mock upstream**

Create `deploy/mock-upstream/` — an echo server that returns the request headers it received (so the smoke can prove the platform credential header arrived and the sandbox-supplied auth was stripped). Prefer a pinned `mendhak/http-https-echo` image referenced from the overlay to avoid building; otherwise a ~25-line Go `net/http` handler echoing `r.Header` as JSON.

- [ ] **Step 2: Compose overlay**

Create `deploy/docker-compose.egress-smoke.yml` layering on `docker-compose.yml`: the mock upstream service (on `joysafeter-network`), and env overrides enabling controller mode (`JOYSAFETER_ENVOY_XDS_MODE=controller`, `JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED=true`, `JOYSAFETER_EGRESS_CONTROLLER_SOURCE=postgres`). The credential route's upstream host points at the mock upstream.

- [ ] **Step 3: Smoke driver — bring up + seed**

Create `deploy/egress-compose-smoke.sh`: `docker compose -f docker-compose.yml -f docker-compose.egress-smoke.yml up -d --wait`; wait for controller `/readyz`; mint a token (per `reference_local_deploy_access.md`), create a secret + environment + sandbox whose egress route targets the mock upstream.

- [ ] **Step 4: Four-source assertions (the core)**

In the same script, assert and fail-hard on any miss:
1. **Envoy config_dump** (`docker exec joysafeter-envoy curl -s 127.0.0.1:9901/config_dump`): the per-sandbox `_http` + `_grpc` listeners present; ext_authz filter on `_http`.
2. **Postgres** (`docker exec joysafeter-postgres psql ...`): `joysafeter_egress_apply_status.state=applied`, `acked_acks=required_acks`, `nacks=0`.
3. **Behavior**: sandbox `curl` through Envoy with the injected placeholder → mock upstream echoes the platform header (proves injection); `curl` with a bogus token → **403**; `curl` direct to the mock upstream IP from the sandbox → **denied**; sandbox container env + inspect has **no real secret**.
4. **Cross-correlate**: grab the Envoy access-log `x-request-id` for the successful call and confirm the mock upstream logged the same id.
Print a per-source PASS line; exit non-zero on any failure. (No scripted `echo OK` as the proof — the proof is the independent artifacts.)

- [ ] **Step 5: Gate locally**

Run: `cd deploy && docker compose -f docker-compose.yml -f docker-compose.egress-smoke.yml config >/dev/null && ./egress-compose-smoke.sh`
Expected: all four sources PASS; script exits 0. Capture the output.

- [ ] **Step 6: CI job**

Add a `docker-egress-smoke` job to `.github/workflows/ci.yml` (per PR) that builds the images, runs `deploy/egress-compose-smoke.sh`, and uploads the config_dump + psql output as artifacts. Also repoint `deploy/deploy.sh`'s egress verify to this script (spec workstream D — or defer D to Plan 3).

- [ ] **Step 7: Commit**

```bash
git add deploy/mock-upstream deploy/docker-compose.egress-smoke.yml \
        deploy/egress-compose-smoke.sh .github/workflows/ci.yml
git commit -m "test(egress): Docker compose egress smoke — four-source tamper-evident e2e (CI)"
```

---

## Self-Review

- **Spec coverage** (sub-spec §4.3 layers 1-2 + §5): C-1 = layer-1 real-Envoy acceptance (func-e, per-PR) ✅; C-2 = layer-2 Docker compose smoke ✅; both mock-upstream/no-key ✅; four-source tamper-evident proof ✅. Layer-3 kind K8s smoke + C-4 Rust lane + D deploy.sh = **Plan 3** (out of scope here).
- **Placeholder scan:** Step 1 of Task 1 explicitly requires verifying func-e's API against the fetched version rather than guessing — this is a real research instruction, not a placeholder; the exact call is pinned before code is written.
- **Prereq:** both tasks assume Plan 1 landed (controller mode + Go control listener). If Plan 1 is not yet merged, run this on the same branch after `96920772`.
- **Type/name consistency:** listener names `joysafeter_<sandbox>_http` / `_grpc` and `orchestrator_grpc` cluster match Plan 1 / the Go compiler.

## Deferred to Plan 3
C-3 (kind/k3d K8s egress smoke, nightly), C-4 (Rust orchestrator CI lane), D (deploy.sh `k8s verify` repointed at the egress smoke + retire the manual `.tmp/envoy-xds-validation/`).
