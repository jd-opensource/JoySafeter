# Deploy refactor: two clean topologies (pure-docker + k8s-sandbox-plane-only)

Date: 2026-08-04
Status: design approved, pending spec review → writing-plans

## Problem

`deploy.sh k8s deploy` currently deploys the ENTIRE control plane (api, worker,
orchestrator, db, redis, frontend, skillspector) INTO Kubernetes (via
`k3s-smoke.sh`). This contradicts the intended topology and produced confusing,
hard-to-diagnose failures during a git-egress verification attempt:

- The PKI bootstrap (`k8s/pki/bootstrap-egress-pki.sh`) is a hidden, un-invoked
  prerequisite — the in-cluster orchestrator got stuck `ContainerCreating`
  ("secret joysafeter-rust-xds-server-tls not found") with no guidance.
- The egress Envoy plane never came up under the default deploy (k3s-smoke.sh
  applies only a curated control-plane subset), so `joysafeter-egress` had no
  workloads — silently, while the deploy reported "ready".
- A stale `ProgressDeadlineExceeded` condition made idempotent re-runs report
  failure even after the pod recovered.

These are symptoms of one root cause: **the k8s deploy target is wrong.** The
guiding principle (owner-stated 2026-08-04) is:

- **Pure-docker mode (`deploy.sh local`)**: ALL services run in docker. (Works today.)
- **k8s mode**: the control plane and all "other services" stay in **docker**;
  ONLY the **sandbox execution plane and its egress dependencies** run in k8s.

## Target topology

Two modes, each the ONLY path for its shape (no compatibility scaffolding).

### Pure-docker (`deploy.sh local`) — unchanged
Full stack in docker compose (project `deploy`): api, worker, orchestrator
(DockerProvider), db, redis, frontend, skillspector, per-sandbox Envoy egress.
Already validated end-to-end (LLM/MCP/git egress).

### k8s mode
- **docker (control plane)**: api, worker, **orchestrator (K8sProvider)**, db,
  redis, frontend, skillspector — all in docker compose. The orchestrator keeps
  its embedded xDS + ext_authz servers (the single credential-decrypt point stays
  in docker) and additionally:
  - spawns sandbox **Pods** in the k8s cluster via a mounted kubeconfig
    (`JOYSAFETER_SANDBOX_PROVIDER=k8s`, namespace `joysafeter-sandboxes`);
  - exposes its xDS (`:18000`) and ext_authz (`:18090`) endpoints to the colima
    host so the in-cluster egress Envoy can dial back.
- **k8s (sandbox plane ONLY)**: namespaces `joysafeter-egress` + `joysafeter-sandboxes`;
  the egress **Envoy DaemonSet** (node-local) + its SA/ConfigMap/Service; sandbox
  RBAC/ResourceQuota/LimitRange/NetworkPolicy; the egress **PKI secrets**.
- **data flow**: docker orchestrator → (kubeconfig) → create sandbox Pod in
  `joysafeter-sandboxes`. Sandbox Pod → in-cluster egress Envoy (node-local
  DaemonSet). Egress Envoy → (mTLS, back across the boundary) → docker
  orchestrator xDS (config) + ext_authz (per-request identity check + credential
  injection). Egress Envoy → real upstream.

This is coherent for real production too: control plane exposes routable
xDS/ext_authz endpoints; the sandbox cluster's Envoy connects to them over mTLS.

## Components & changes

### k8s side — `deploy.sh k8s deploy` applies the sandbox plane ONLY
- Converge on `k8s/overlays/sandbox-plane` as the SOLE k8s deploy target. It must
  contain exactly: `00-namespaces` (egress + sandboxes only), `27-egress-envoy`
  (DaemonSet + SA + ConfigMap + Service), `50-sandbox-policy`
  (ResourceQuota/LimitRange/NetworkPolicy + the RBAC the docker orchestrator's
  kubeconfig identity needs to manage sandbox Pods), and the config/secret pieces
  the Envoy needs. NO api/worker/orchestrator/frontend/db/redis/skillspector.
- Fold `bootstrap-egress-pki.sh` INTO the deploy flow (auto-run, idempotent) so
  the mTLS secrets are never a hidden prerequisite. It creates:
  `joysafeter-rust-xds-server-tls` is NOT needed in-cluster anymore (the xDS
  server runs in docker) — instead the Envoy needs its **xDS client** + **authz
  client** + **downstream server** certs, and the **CA** to verify the docker
  orchestrator's server certs. PKI SANs for the orchestrator server cert must
  include its boundary-reachable address (see Cross-boundary).

### docker side — new compose overlay for k8s mode
`deploy/docker-compose.k8s-sandbox.yml` (name TBD-in-plan), layered on the base
compose, that for the orchestrator:
- sets `JOYSAFETER_SANDBOX_PROVIDER=k8s` + `JOYSAFETER_K8S_NAMESPACE=joysafeter-sandboxes`;
- mounts a kubeconfig readable in-container (with the server address rewritten —
  see below);
- publishes xDS `:18000` and ext_authz `:18090` on the colima host;
- sets the egress authority host id / xDS mode for the k8s plane;
- does NOT start the docker per-sandbox Envoy path.

`deploy.sh local` (pure-docker) does NOT load this overlay.

### Cross-boundary wiring (colima-specific; PIN during implementation)
Two risk points that must be verified live on colima:
1. **k8s egress Envoy → docker orchestrator**: the Envoy bootstrap's `xds_cluster`
   and ext_authz cluster must target the orchestrator's **host-reachable address**
   (the colima node/host IP + published port), NOT a `*.svc.cluster.local` DNS
   (the orchestrator is not in-cluster). The orchestrator's xDS/authz **server
   cert SAN must include that address**.
2. **docker orchestrator → k3s API**: the mounted kubeconfig `server:` must be an
   address reachable from INSIDE the orchestrator container (NOT `127.0.0.1`,
   which is the container itself) — e.g. `host.docker.internal` or the colima VM
   IP. RBAC: for local colima the orchestrator may use the admin kubeconfig; the
   sandbox-manager Role/RoleBinding in `50-sandbox-policy` must bind to whatever
   identity that kubeconfig presents (or a dedicated ServiceAccount token).

### Deletions (cleanup of the now-redundant "control plane in k8s" path)
Per "其余服务用 docker" the following are dead as k8s deploy targets and are
removed (each grep-verified for other references first, deleted in focused commits):
- k8s control-plane manifests: `10-infra` (pg/redis), `20-skillspector`,
  `40-app` (api/worker/**in-cluster orchestrator**/frontend), the migration Job,
  and the `02-rbac` ServiceAccount/roles that existed only for the in-cluster
  orchestrator.
- `k3s-smoke.sh`'s "apply the whole control plane" logic — rewritten to apply the
  sandbox-plane overlay + PKI, or replaced by a new focused deploy path.
- `overlays/local`'s in-cluster-orchestrator patch (no in-cluster orchestrator
  exists) — reconciled/merged into `overlays/sandbox-plane`.

Keep whole-feature switches (rollout gates) if any; drop only compat/dead paths.

## Error handling / operability
- Deploy auto-runs PKI; if certs already exist it is idempotent.
- Deploy waits on the egress Envoy DaemonSet rollout (not on any control-plane
  Deployment, which no longer exists in k8s).
- Clear failure messages when the orchestrator cannot reach the k3s API or the
  Envoy cannot reach the orchestrator (the two boundary links).

## Testing / acceptance
1. **Pure-docker regression**: `deploy.sh local` brings up the full stack;
   LLM + MCP + git egress still pass (git egress already fixed+proven).
2. **k8s mode E2E** (the original goal): docker control plane (k8s-sandbox
   overlay) + `deploy.sh k8s deploy` (sandbox plane) → register user → agent with
   git repo session → fire task → **sandbox runs as a k8s Pod** → clone routes
   through the in-cluster egress Envoy whose xDS/ext_authz come from the docker
   orchestrator → confirm the clone passes ext_authz (route resolved + credential
   injected + reaches real upstream), i.e. NO 403 — the git-egress fix holds on
   the k8s plane exactly as on docker.

## Sequencing (strangler; converge, then delete)
1. Converge `overlays/sandbox-plane` as the sole k8s deploy face; fold in PKI.
2. Add the docker k8s-sandbox compose overlay (orchestrator K8sProvider + exposed
   xDS/ext_authz + kubeconfig).
3. Pin cross-boundary wiring (Envoy→host address, kubeconfig server rewrite, PKI
   SANs) — verify live on colima.
4. Rewrite `deploy.sh k8s deploy` to apply sandbox-plane + auto-PKI only.
5. Delete the dead k8s control-plane manifests + old smoke path (focused commits).
6. E2E-validate the k8s sandbox-Pod git egress; keep pure-docker green.

## Open items to resolve in the plan/implementation
- Exact colima host address the in-cluster Envoy uses to reach docker (and its
  stability across colima restarts).
- kubeconfig identity + minimal RBAC for the docker orchestrator to manage Pods
  in `joysafeter-sandboxes`.
- Whether `overlays/sandbox-plane` already contains the right subset or needs
  carving; reconcile with `overlays/local`.
- Which recent Rust-xDS/mTLS assumptions (server identity SANs) bake in an
  in-cluster orchestrator DNS name and must be generalized to the boundary address.
