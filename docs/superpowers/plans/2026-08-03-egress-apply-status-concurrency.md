# Egress Controller Apply-Status Concurrency Deep Dive

> **Historical / superseded (2026-08-04):** This implementation record covers
> the deleted Go publisher. Canonical apply-state ownership now lives in the
> embedded Rust ADS reconciler and observer.

Status: implemented and integration-tested on 2026-08-03.

## Goal

Make `joysafeter_egress_apply_status` correct under multi-replica
`egress-controller` concurrency without leader election:

- no lost ACK updates when different controller instances persist ACKs for the
  same `(group_key, generation)` concurrently;
- no permanent stall when ACK/connect events arrive before the aggregate apply
  row is published;
- terminal states remain monotonic (`applied`, `failed`, `superseded` are not
  rewritten by recompute).

## Root Causes Found

1. **Lost aggregate update:** concurrent ACK writers could each compute counts
   from a stale statement snapshot and overwrite the aggregate with an older ACK
   count. The fix serializes recompute with `pg_advisory_xact_lock` per
   `(group_key, generation)` before the recompute SQL runs.
2. **Missed trigger ordering:** ACK/connect can legitimately be persisted before
   the `joysafeter_egress_apply_status` row exists. The ACK recompute then sees
   no target row and does nothing. Without a publish-time recompute, the row can
   stay `published` until the periodic backstop fires. The fix makes non-empty
   `Published` insert/update immediately call the same serialized recompute.
3. **Liveness backstop:** if any event-triggered recompute is missed or fails,
   a periodic sweep recomputes every non-terminal row. This is a safety net, not
   the primary path for normal apply completion.
4. **Integration harness interference:** `go test -tags integration` runs
   packages concurrently by default. The source/status/xDS integration packages
   shared one database and each used global `TRUNCATE`, so one package could
   delete another package's generation rows while a NACK was being persisted,
   surfacing as a foreign-key retry rather than a product NACK bug. Integration
   helpers now hold a shared PostgreSQL advisory lock across each truncating
   test, using an independent one-connection pool so test `pool.Close()` cannot
   deadlock on its own lock connection.

## Implemented Code

- `egress-controller/internal/status/recompute.go`: canonical recompute SQL and
  transaction-scoped advisory lock helper.
- `egress-controller/internal/status/postgres.go`: recompute triggers on ACK,
  connect, disconnect, publish, and ticker; metrics label trigger/result.
- `egress-controller/internal/source/postgres_integration_test.go`,
  `egress-controller/internal/status/postgres_integration_test.go`, and
  `egress-controller/internal/xds/postgres_e2e_integration_test.go`: shared DB
  advisory lock for integration tests that truncate global egress tables.
- `egress-controller/internal/config/config.go`: configurable recompute interval
  through `JOYSAFETER_EGRESS_CONTROLLER_RECOMPUTE_INTERVAL`.
- `egress-controller/internal/telemetry/metrics.go`: Prometheus counter
  `joysafeter_egress_controller_apply_status_recompute_total`.

## Verification

- `cd egress-controller && GOCACHE=/tmp/joysafeter-go-build-cache GOMODCACHE=/tmp/joysafeter-go-pkg-cache go test ./...`
- `cd egress-controller && JOYSAFETER_TEST_DATABASE_URL='postgres://postgres:postgres@127.0.0.1:55441/joysafeter_status_test?sslmode=disable' GOCACHE=/tmp/joysafeter-go-build-cache GOMODCACHE=/tmp/joysafeter-go-pkg-cache go test -tags integration ./internal/status`
- `cd egress-controller && JOYSAFETER_TEST_DATABASE_URL='postgres://postgres:postgres@127.0.0.1:55441/joysafeter_status_test?sslmode=disable' GOCACHE=/tmp/joysafeter-go-build-cache GOMODCACHE=/tmp/joysafeter-go-pkg-cache go test -tags integration -count=1 -timeout=120s ./internal/source ./internal/status ./internal/xds`
- Live k3s after rebuilding/deploying `joysafeter-egress-controller:latest`:
  `deploy/k8s/k3s-egress-smoke.sh` passed with task
  `019fc59f-04b8-7873-8c95-f0f34a7a9046`, sandbox
  `019fc59f-04c6-7541-b4a1-a211e8409e4c`, generation `35`, and output
  `K3S_EGRESS_OK`.
- Live 2×2 HA k3s validation on 2026-08-03 passed with
  `EGRESS_CONTROLLER_REPLICAS=2` and `EGRESS_ENVOY_REPLICAS=2`: task
  `019fc5f7-0088-7e52-b893-b937d870e5e4`, sandbox
  `019fc5f7-0093-7c73-955e-f0f8a665f32b`, generation `42`, and output
  `K3S_EGRESS_OK`. The live DB row for generation `42` was `applied` with
  `connected_nodes=2`, `required_acks=4`, `acked_acks=4`, and node status rows
  contained four ACKs and zero NACKs across both Envoy Pods.

Integration tests cover:

- concurrent ACKs converge to `applied` with the advisory lock;
- an intentionally unlocked recompute documents the historical lost-update
  artifact;
- disconnect shrinks the required ACK set and unblocks apply;
- ticker recompute converges a stale aggregate;
- publish recompute catches an ACK that arrived before the apply-status row;
- terminal states remain monotonic across controller instances.

## Remaining Gaps

- One-shot live HA validation has passed with two controller replicas and two
  Envoy replicas. Remaining HA work is long-run/chaos validation: repeated
  policy update/destroy/reuse cycles while rolling controller, Envoy, and
  orchestrator replicas under active sandbox traffic.
- Durable apply-state metrics exist, but product-facing alerts/SLOs are not yet
  defined.
- The apply-state path proves control-plane convergence; it does not solve FQDN
  enforcement at Kubernetes `NetworkPolicy` layer or upstream error taxonomy.
- JDCloud Anthropic-compatible validation exposed provider-surface drift from
  Claude Code 2.1.220 defaults: the CLI sends `?beta=true`, `anthropic-beta`,
  auto-title requests, `thinking`, metadata, system blocks, streaming, and tool
  schemas. Minimal Messages requests through the shared Envoy route succeeded;
  the smoke now disables Claude Code title/thinking/experimental beta behavior
  for this egress proof. Product-facing provider compatibility and structured
  upstream error taxonomy remain separate gaps.
