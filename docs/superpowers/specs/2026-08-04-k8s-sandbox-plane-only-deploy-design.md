# Deploy refactor: two clean topologies (pure-docker + k8s-sandbox-execution-plane)

Date: 2026-08-04 (redesigned)
Status: design under review → writing-plans

## Problem

`deploy.sh k8s deploy` currently pushes the ENTIRE stack into Kubernetes (via
`k3s-smoke.sh`, which actually applies only a curated control-plane subset). This
neither matches the intended topology nor works cleanly, and produced confusing
failures during a git-egress verification attempt:

- PKI (`k8s/pki/bootstrap-egress-pki.sh`) is a hidden, un-invoked prerequisite →
  the orchestrator hung `ContainerCreating` ("secret joysafeter-rust-xds-server-tls
  not found") with no guidance.
- The egress Envoy plane was never applied by the default deploy, so
  `joysafeter-egress` had no workloads — silently, while deploy said "ready".
- A stale `ProgressDeadlineExceeded` made idempotent re-runs report failure.

Root cause: **the k8s deploy has no clean topology.** The guiding principle
(owner, 2026-08-04): pure-docker = everything in docker; k8s mode = **only the
sandbox execution dependencies run in k8s; the other services stay in docker.**

## What counts as a "sandbox execution dependency" (the key call)

`orchestrator-rs` is dual-role: it schedules tasks (via the Postgres+Redis bus,
shared with api/worker) AND it serves the sandbox egress control plane (embedded
xDS + ext_authz) that the sandbox's Envoy depends on, AND it drives the sandbox
Pod lifecycle (K8sProvider). Because the egress control ↔ Envoy link is **mTLS**,
splitting it across the docker↔k8s boundary is the single painful piece
(host-reachable address + cert SANs + reverse-dial + kubeconfig-in-container).

Therefore **orchestrator-rs is treated as a sandbox execution dependency and runs
IN k8s**, co-located with the egress Envoy and sandbox Pods it serves. This keeps
the mTLS control↔Envoy link in-cluster (svc DNS) — which is exactly what the
existing k8s manifests and PKI already assume (`RUST_XDS_SERVER_IDENTITY =
joysafeter-orchestrator.joysafeter-control.svc`, `40-app` has the orchestrator,
`02-rbac` has its ServiceAccount). It also lets the orchestrator use an in-cluster
ServiceAccount for the K8sProvider (no kubeconfig gymnastics).

## Target topology

Two modes, each the ONLY path for its shape (no compatibility scaffolding).

### Pure-docker (`deploy.sh local`) — unchanged
Full stack in docker compose (project `deploy`). Already validated end-to-end
(LLM/MCP/git egress).

### k8s mode
- **k8s (sandbox execution plane)**: `orchestrator-rs` (embedded xDS + ext_authz;
  in-cluster ServiceAccount for K8sProvider) + egress **Envoy DaemonSet**
  (node-local) + **sandbox Pods** + sandbox RBAC/ResourceQuota/LimitRange/
  NetworkPolicy + egress **PKI** (mTLS all in-cluster).
- **docker (other services + the bus)**: api, worker, frontend, skillspector,
  **postgres, redis**.
- **boundary (single, easy link)**: the k8s `orchestrator-rs` connects OUT to the
  docker-hosted **Postgres + Redis** bus over plain TCP. No mTLS across the
  boundary. api/worker (docker) use the same local bus; they reach the orchestrator
  only indirectly through the bus (task enqueue via Redis, state via Postgres),
  so no direct docker↔k8s RPC is required on the hot path.

Data flow (k8s mode): api (docker) writes task to Postgres + `rpush` Redis (docker
bus) → orchestrator (k8s) pops from Redis, creates a sandbox **Pod** → sandbox Pod
→ in-cluster egress Envoy → (in-cluster mTLS) orchestrator xDS (config) + ext_authz
(identity check + credential injection) → real upstream.

Bus-placement rationale: Postgres/Redis stay in docker because `deploy.sh local`
already runs them reliably; k8s then deploys NO stateful components (smallest,
simplest k8s footprint). Trade-off: the orchestrator's hot bus loop crosses the
boundary (fine on colima via the host address; acceptable). If we later want the
orchestrator's bus loop local, move PG/Redis into k8s and let api/worker cross
instead — deferred, not now.

## Components & changes

### k8s side — `deploy.sh k8s deploy` applies the sandbox execution plane
Applies: namespaces (control + egress + sandboxes as needed by the in-cluster
orchestrator/Envoy/pods), `02-rbac` (orchestrator SA/roles — now CORRECT), the
orchestrator Deployment/Service (carved from `40-app`, WITHOUT api/worker/frontend),
`27-egress-envoy` (DaemonSet), `50-sandbox-policy`, and auto-runs
`bootstrap-egress-pki.sh` (fold in; no hidden prerequisite). The orchestrator
Deployment env points `DATABASE_URL`/`REDIS_URL` at the docker bus (host-reachable
address), keeps egress authority + in-cluster xDS/ext_authz.

### docker side — a compose profile/overlay for k8s mode
Runs api, worker, frontend, skillspector, postgres, redis — i.e. `deploy.sh local`
MINUS the orchestrator and MINUS the docker per-sandbox egress plane (those live in
k8s now). Postgres/Redis are published to a boundary-reachable address for the k8s
orchestrator.

### Cross-boundary wiring (colima-specific; PIN during implementation)
- k8s orchestrator → docker Postgres(5432)/Redis(6379): via the colima host/node
  address (e.g. `host.docker.internal`-equivalent from a k3s pod). Verify live.
- All egress mTLS (Envoy ↔ orchestrator xDS/ext_authz) is IN-CLUSTER → uses the
  existing PKI SANs unchanged. This is the big simplification vs the prior draft.

### Deletions / cleanup (redundant now, remove in focused commits after grep-verify)
- From the k8s deploy: api/worker/frontend Deployments (they run in docker),
  `20-skillspector` (docker), `10-infra` Postgres/Redis (docker bus).
- `k3s-smoke.sh`'s "apply the whole stack" path — rewritten to apply the sandbox
  execution plane only + auto-PKI.
- Reconcile `overlays/local` / `overlays/sandbox-plane` to this single k8s face.

## Testing / acceptance
1. **Pure-docker regression**: `deploy.sh local` full stack; LLM+MCP+git egress
   still pass.
2. **k8s mode E2E** (original goal): docker side (api/worker/frontend/skillspector
   + PG/Redis) + `deploy.sh k8s deploy` (orchestrator + egress Envoy + sandbox
   plane + PKI) → register user → agent + git-repo session → fire task → **sandbox
   runs as a k8s Pod** → clone routes through the in-cluster egress Envoy (xDS +
   ext_authz from the in-cluster orchestrator) → confirm clone passes ext_authz
   (route resolved + credential injected + reaches real upstream), NO 403 — the
   git-egress fix holds on the k8s plane as on docker.

## Sequencing (strangler; converge, then delete)
1. Carve the k8s "sandbox execution plane" set (orchestrator + egress Envoy +
   sandbox policy + RBAC + PKI); fold PKI into deploy.
2. Point the k8s orchestrator at the docker bus (DATABASE_URL/REDIS_URL host addr).
3. Add the docker compose profile/overlay = local MINUS orchestrator MINUS docker
   egress plane; publish PG/Redis to the boundary.
4. Rewrite `deploy.sh k8s deploy` to apply the sandbox execution plane + auto-PKI
   only; wait on the orchestrator + Envoy DaemonSet rollout.
5. Delete the now-docker services from the k8s deploy path + old smoke logic.
6. E2E-validate the k8s sandbox-Pod git egress; keep pure-docker green.

## Open items to resolve in the plan/implementation
- Exact colima host address the k8s orchestrator uses to reach docker PG/Redis
  (and stability across colima restarts).
- Whether to keep both `joysafeter-control` (orchestrator) and the egress/sandbox
  namespaces, or collapse; reconcile with `overlays/sandbox-plane`.
- Confirm no code path assumes api/worker are in the SAME cluster as the
  orchestrator (they now differ: docker vs k8s), beyond the PG/Redis bus.
- Bus hot-path latency across the boundary — acceptable locally; note for prod.
