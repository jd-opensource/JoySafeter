# k8s Sandbox-Execution-Plane Deploy Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `deploy.sh k8s deploy` so k8s mode runs ONLY the sandbox execution plane (orchestrator-rs + egress Envoy DaemonSet + sandbox Pods/RBAC/policy + auto-bootstrapped in-cluster egress PKI), with api/worker/frontend/skillspector/postgres/redis staying in docker and the sole boundary being the k8s orchestrator reaching the docker Postgres+Redis bus over plain TCP.

**Architecture:** Two independent topologies. `deploy.sh local` (pure-docker) is the unchanged regression baseline. `deploy.sh k8s deploy` applies a new local colima overlay `overlays/sandbox-plane-local` (base MINUS api/worker/frontend/skillspector/postgres/redis/db-init, keeping orchestrator + `26-egress-authz` + `27-egress-envoy` + `50-sandbox-policy` + `02-rbac` + `00-namespaces` + `01-config`), auto-runs `bootstrap-egress-pki.sh`, and points the orchestrator's `DATABASE_URL`/`REDIS_URL` at the docker bus via a deploy-time-discovered colima host address; the docker side is brought up by a new `compose --profile k8s-bus` face = local MINUS the orchestrator MINUS the docker per-sandbox egress plane, publishing PG/Redis to the boundary. All egress mTLS (Envoy ↔ orchestrator xDS/ext_authz) stays in-cluster and reuses the existing PKI SANs unchanged.

**Tech Stack:** bash, kubectl/kustomize, docker-compose, colima k3s, Rust orchestrator (config only), Envoy.

## Global Constraints
- **Pure-docker mode (`deploy.sh local`) MUST stay unchanged and green.** It is the regression baseline: no edit in this plan may alter the `run_local_compose`/`configure_local_compose_env`/`--profile local-redis --profile sandbox` behavior or the services those profiles bring up. Verified by re-running `deploy.sh local` in the acceptance task.
- **No compatibility scaffolding — the new path is the only path.** Do not keep the old "apply the whole stack" `k3s-smoke.sh` behavior behind a flag; rewrite/retire it. Do not add feature toggles to fall back to the pre-refactor k8s deploy.
- **Egress control↔Envoy mTLS stays IN-CLUSTER.** orchestrator-rs (xDS + ext_authz) runs in k8s co-located with the egress Envoy; the mTLS link uses the existing in-cluster svc-DNS SANs. Never move xDS/ext_authz across the docker↔k8s boundary, never change the PKI SANs for the local case.
- **Credential-decrypt (ext_authz) stays with the orchestrator.** The credential broker / ext_authz server is embedded in orchestrator-rs and stays in-cluster. Never split it out.
- **Commit-scoping:** the working tree has unrelated parallel changes. NEVER `git add -A` / `git add .`. Always stage the explicit paths listed in each task's Commit step.
- **Branch & user:** all work is on branch `joysafeter-v2` (git user `yuzzjj`). Do not switch branches; do not force-push; do not amend existing commits.
- **Secrets discipline:** never write a real model key / token to a committed file. The local overlay reuses the in-repo dev `joysafeter-secret` from `01-config.yaml` (dev-only placeholders already committed there).

---

### Task 1: Create the local k8s sandbox-execution-plane overlay (`overlays/sandbox-plane-local`)

**Files:**
- Create: `deploy/k8s/overlays/sandbox-plane-local/kustomization.yaml`
- Validate: `kubectl kustomize deploy/k8s/overlays/sandbox-plane-local`

**Interfaces:**
- Consumes: `deploy/k8s/base` (all base manifests) — specifically keeps `00-namespaces.yaml`, `01-config.yaml`, `02-rbac.yaml`, `26-egress-authz.yaml`, `27-egress-envoy.yaml`, `40-app.yaml` (orchestrator Service+Deployment only), `50-sandbox-policy.yaml`; deletes api/worker/frontend/skillspector/postgres/redis Services+Deployments, `joysafeter-db-init` Job, and the base `10-infra.yaml`/`20-skillspector.yaml` workloads via `$patch: delete`.
- Produces: overlay path `deploy/k8s/overlays/sandbox-plane-local` — the SINGLE k8s deploy face consumed by `deploy.sh k8s deploy` (Task 6). Keeps in-cluster mTLS (`JOYSAFETER_EGRESS_XDS_MTLS=true`, `JOYSAFETER_EGRESS_AUTHZ_MTLS=true` — inherited from base, NOT overridden here, unlike `overlays/local`). Keeps images at `:latest` (colima shared docker runtime, `imagePullPolicy: IfNotPresent`) — NO `images:` retag block (that is the prod `sandbox-plane` overlay's job). Keeps the in-repo dev `joysafeter-secret` (NOT deleted, unlike prod `sandbox-plane`). DATABASE_URL/REDIS_URL are NOT set here; Task 2 patches them.

- [ ] **Step 1: Write `deploy/k8s/overlays/sandbox-plane-local/kustomization.yaml`** with exactly this content:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Local colima-k3s "sandbox execution plane" overlay for `deploy.sh k8s deploy`.
# Runs ONLY: orchestrator-rs (embedded xDS + ext_authz), egress Envoy DaemonSet,
# sandbox namespaces/RBAC/quota/policy, and the in-cluster egress PKI (bootstrapped
# separately by deploy/k8s/pki/bootstrap-egress-pki.sh). Everything else — api,
# worker, frontend, skillspector, postgres, redis — runs in docker (compose
# --profile k8s-bus). All egress control<->Envoy mTLS stays in-cluster and reuses
# the base svc-DNS SANs unchanged (mTLS stays ON here, unlike overlays/local).
resources:
  - ../../base

patches:
  # ---- Delete the services that run in docker (k8s mode) ------------------
  - target: { kind: Service, name: api, namespace: joysafeter-control }
    patch: |-
      apiVersion: v1
      kind: Service
      metadata: { name: api, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Deployment, name: api, namespace: joysafeter-control }
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata: { name: api, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Service, name: worker, namespace: joysafeter-control }
    patch: |-
      apiVersion: v1
      kind: Service
      metadata: { name: worker, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Deployment, name: worker, namespace: joysafeter-control }
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata: { name: worker, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Service, name: frontend, namespace: joysafeter-control }
    patch: |-
      apiVersion: v1
      kind: Service
      metadata: { name: frontend, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Deployment, name: frontend, namespace: joysafeter-control }
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata: { name: frontend, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Service, name: skillspector, namespace: joysafeter-control }
    patch: |-
      apiVersion: v1
      kind: Service
      metadata: { name: skillspector, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Deployment, name: skillspector, namespace: joysafeter-control }
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata: { name: skillspector, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Service, name: postgres, namespace: joysafeter-control }
    patch: |-
      apiVersion: v1
      kind: Service
      metadata: { name: postgres, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Deployment, name: postgres, namespace: joysafeter-control }
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata: { name: postgres, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Service, name: redis, namespace: joysafeter-control }
    patch: |-
      apiVersion: v1
      kind: Service
      metadata: { name: redis, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Deployment, name: redis, namespace: joysafeter-control }
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata: { name: redis, namespace: joysafeter-control }
      $patch: delete
  - target: { kind: Job, name: joysafeter-db-init, namespace: joysafeter-control }
    patch: |-
      apiVersion: batch/v1
      kind: Job
      metadata: { name: joysafeter-db-init, namespace: joysafeter-control }
      $patch: delete
  # ---- Make the egress-PKI-mounted secrets optional so the orchestrator Pod
  # ---- schedules before bootstrap-egress-pki.sh runs (deploy folds PKI in at
  # ---- Task 3; the Envoy DaemonSet already tolerates absent client secrets). --
  - target:
      kind: Deployment
      name: joysafeter-orchestrator
      namespace: joysafeter-control
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: joysafeter-orchestrator
        namespace: joysafeter-control
      spec:
        template:
          spec:
            volumes:
              - name: authz-server-tls
                secret:
                  secretName: joysafeter-egress-authz-server-tls
                  optional: true
              - name: xds-server-tls
                secret:
                  secretName: joysafeter-rust-xds-server-tls
                  optional: true
```
  Note: the base `10-infra.yaml` (postgres+redis) and `20-skillspector.yaml` Deployments/Services are removed by the delete patches above. The base names in `10-infra.yaml` are `postgres`/`redis` (Deployment+Service) and in `20-skillspector.yaml` are `skillspector` (Deployment+Service) — confirm these exact names when writing (grep the base files first if uncertain).

- [ ] **Step 2: Verify the base resource names before relying on the delete patches** — run `kubectl kustomize deploy/k8s/base | grep -nE '^  name: (postgres|redis|skillspector|api|worker|frontend|joysafeter-db-init)$'` — Expected: each of `postgres`, `redis`, `skillspector`, `api`, `worker`, `frontend`, `joysafeter-db-init` appears (as Deployment and/or Service/Job). If a name differs, fix the corresponding delete patch target to match before proceeding.

- [ ] **Step 3: Run `kubectl kustomize deploy/k8s/overlays/sandbox-plane-local > /tmp/spl-render.yaml`** — Expected: exit 0, no error. Then `grep -cE '^kind: (Deployment|Job)$' /tmp/spl-render.yaml` should show ONLY the orchestrator Deployment remaining in `joysafeter-control` (plus the egress-envoy DaemonSet, which is `kind: DaemonSet`, not Deployment). Verify api/worker/frontend/skillspector/postgres/redis/db-init are ABSENT: `grep -E 'name: (api|worker|frontend|skillspector|postgres|redis|joysafeter-db-init)$' /tmp/spl-render.yaml` — Expected: no output.

- [ ] **Step 4: Confirm mTLS stayed ON (in-cluster) in the render** — `grep -E 'JOYSAFETER_EGRESS_(XDS|AUTHZ)_MTLS' /tmp/spl-render.yaml` — Expected: both show `"true"` (this overlay does NOT flip them to false like `overlays/local` does).

- [ ] **Step 5: Confirm the orchestrator, egress-envoy, egress-authz, sandbox policy, and RBAC all survive** — `grep -E 'name: (joysafeter-orchestrator|joysafeter-egress-envoy|joysafeter-egress-authz|joysafeter-sandbox-manager|sandbox-quota|default-deny)$' /tmp/spl-render.yaml` — Expected: all present.

- [ ] **Step 6: Commit** — `git add deploy/k8s/overlays/sandbox-plane-local/kustomization.yaml` + `git commit -m "feat(deploy): add local k8s sandbox-execution-plane overlay"`

---

### Task 2: Point the in-cluster orchestrator's DATABASE_URL/REDIS_URL at the docker bus (colima host address, discovery-driven)

**Files:**
- Modify: `deploy/k8s/overlays/sandbox-plane-local/kustomization.yaml` (append a ConfigMap JSON-patch block + a hostAliases patch)
- Validate: `kubectl kustomize deploy/k8s/overlays/sandbox-plane-local | grep -A2 'DATABASE_URL'`

**Interfaces:**
- Consumes: `overlays/sandbox-plane-local` from Task 1; base `01-config.yaml` keys `DATABASE_URL` (`postgres://postgres:postgres@postgres:5432/joysafeter`), `REDIS_URL` (`redis://redis:6379/0`), `POSTGRES_HOST`, `POSTGRES_PORT`.
- Produces: the orchestrator's `DATABASE_URL`/`REDIS_URL`/`POSTGRES_HOST` now resolve to a stable in-cluster hostAlias name `joysafeter-docker-bus`, mapped to the colima host IP at deploy time by `deploy.sh` (Task 6) via env substitution. The overlay ships a placeholder `__DOCKER_BUS_IP__` that `deploy.sh` replaces with the discovered IP. Confirms `JOYSAFETER_SANDBOX_PROVIDER=k8s` (already in base), in-cluster xDS bind `0.0.0.0:18000`, ext_authz bind `0.0.0.0:18090` (already in base — unchanged).

**Colima host-address discovery (PINNED mechanism):** On colima, docker and k3s share one VM; a k3s Pod cannot use `host.docker.internal` (that alias exists only inside the docker bridge, not inside k3s Pods). The docker-published PG/Redis ports (`0.0.0.0:5432`/`0.0.0.0:6379`, see Task 4) are reachable from k3s Pods at the **k3s node's internal IP** (the colima VM address). Discover it at deploy time with:
`kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}'`
On single-node colima this yields the VM IP (historically `192.168.5.1` per the colima env note, but it MUST be discovered live, not hardcoded — it can change across colima recreate). `deploy.sh` (Task 6) captures this into `DOCKER_BUS_IP` and substitutes it into the rendered manifests via a `hostAliases` entry `joysafeter-docker-bus -> $DOCKER_BUS_IP`, so the ConfigMap URLs stay static (`@joysafeter-docker-bus:5432`) and only the IP mapping is dynamic.

- [ ] **Step 1: Append to `deploy/k8s/overlays/sandbox-plane-local/kustomization.yaml`** a ConfigMap patch redirecting the bus URLs to the hostAlias, plus a Deployment patch adding the hostAlias placeholder:
```yaml
  # ---- k8s mode: orchestrator reaches the DOCKER-hosted PG/Redis bus --------
  # The bus URLs point at a stable in-cluster hostAlias name; deploy.sh maps
  # `joysafeter-docker-bus` to the discovered colima node InternalIP at apply
  # time (see plan Task 6). Plain TCP — no mTLS across this single boundary.
  - target:
      kind: ConfigMap
      name: joysafeter-config
      namespace: joysafeter-control
    patch: |-
      - op: replace
        path: /data/DATABASE_URL
        value: postgres://postgres:postgres@joysafeter-docker-bus:5432/joysafeter
      - op: replace
        path: /data/REDIS_URL
        value: redis://joysafeter-docker-bus:6379/0
      - op: replace
        path: /data/POSTGRES_HOST
        value: joysafeter-docker-bus
  - target:
      kind: Deployment
      name: joysafeter-orchestrator
      namespace: joysafeter-control
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: joysafeter-orchestrator
        namespace: joysafeter-control
      spec:
        template:
          spec:
            hostAliases:
              - ip: "__DOCKER_BUS_IP__"
                hostnames:
                  - joysafeter-docker-bus
```
  Rationale for hostAliases over baking the IP into the URL: keeps the committed manifest free of an environment-specific IP (no churn), and confines the one dynamic value to a single `__DOCKER_BUS_IP__` token that `deploy.sh` substitutes at apply time.

- [ ] **Step 2: Run `kubectl kustomize deploy/k8s/overlays/sandbox-plane-local > /tmp/spl-render.yaml`** — Expected: exit 0. Then `grep -E 'DATABASE_URL|REDIS_URL|POSTGRES_HOST|joysafeter-docker-bus|__DOCKER_BUS_IP__' /tmp/spl-render.yaml` — Expected: `DATABASE_URL: postgres://postgres:postgres@joysafeter-docker-bus:5432/joysafeter`, `REDIS_URL: redis://joysafeter-docker-bus:6379/0`, `POSTGRES_HOST: joysafeter-docker-bus`, and a `hostAliases` entry with `ip: "__DOCKER_BUS_IP__"` mapping `joysafeter-docker-bus`.

- [ ] **Step 3: Confirm sandbox provider + xDS/ext_authz binds are the in-cluster defaults** — `grep -E 'JOYSAFETER_SANDBOX_PROVIDER|JOYSAFETER_EGRESS_XDS_BIND|JOYSAFETER_EGRESS_AUTHZ_BIND' /tmp/spl-render.yaml` — Expected: `JOYSAFETER_SANDBOX_PROVIDER: k8s`, `JOYSAFETER_EGRESS_XDS_BIND: 0.0.0.0:18000`, `JOYSAFETER_EGRESS_AUTHZ_BIND: 0.0.0.0:18090` (unchanged from base — the orchestrator uses its in-cluster ServiceAccount for the K8sProvider and serves xDS/ext_authz in-cluster).

- [ ] **Step 4: Commit** — `git add deploy/k8s/overlays/sandbox-plane-local/kustomization.yaml` + `git commit -m "feat(deploy): point k8s orchestrator at docker bus via colima hostAlias"`

---

### Task 3: Fold `bootstrap-egress-pki.sh` into the k8s deploy as an idempotent helper

**Files:**
- Create: `deploy/k8s/apply-sandbox-plane.sh` (new k8s-mode deploy entrypoint; replaces the delegation to `k3s-smoke.sh`)
- Validate: `bash -n deploy/k8s/apply-sandbox-plane.sh`

**Interfaces:**
- Consumes: `overlays/sandbox-plane-local` (Tasks 1-2); `deploy/k8s/pki/bootstrap-egress-pki.sh` (mints `joysafeter-rust-xds-server-tls` + `joysafeter-egress-authz-server-tls` in `joysafeter-control`, `joysafeter-egress-envoy-xds-client-tls` + `joysafeter-egress-authz-client-tls` + `joysafeter-egress-downstream-server-tls` in `joysafeter-egress`, and `joysafeter-egress-downstream-ca` ConfigMap in `joysafeter-sandboxes`; SANs baked in: RUST_XDS_SERVER_IDENTITY=`joysafeter-orchestrator.joysafeter-control.svc.cluster.local`, AUTHZ_SERVER_IDENTITY=`joysafeter-egress-authz.joysafeter-control.svc.cluster.local`, ENVOY_IDENTITY=`joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local` — all IN-CLUSTER, unchanged for the local case).
- Produces: `deploy/k8s/apply-sandbox-plane.sh` — the script `deploy.sh k8s deploy` will call (wired in Task 6). It: (1) discovers `DOCKER_BUS_IP`, (2) applies `00-namespaces` first so PKI's namespace precheck passes, (3) runs `bootstrap-egress-pki.sh` (idempotent — it uses `kubectl apply` on generated secrets), (4) renders the overlay with `__DOCKER_BUS_IP__` substituted and applies it, (5) waits on the orchestrator Deployment + egress-envoy DaemonSet rollout.

- [ ] **Step 1: Write `deploy/k8s/apply-sandbox-plane.sh`** with exactly this content:
```bash
#!/usr/bin/env bash
# Apply ONLY the JoySafeter sandbox execution plane to the current k8s context
# (colima k3s locally): orchestrator-rs + egress Envoy DaemonSet + sandbox
# RBAC/policy + auto-bootstrapped in-cluster egress PKI. Everything else runs in
# docker (see deploy.sh local's compose --profile k8s-bus). Idempotent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K8S_DIR="$ROOT/deploy/k8s"
OVERLAY="$K8S_DIR/overlays/sandbox-plane-local"
BASE="$K8S_DIR/base"

KUBECTL="${KUBECTL:-kubectl}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
EGRESS_NS="${JOYSAFETER_EGRESS_NAMESPACE:-joysafeter-egress}"

log() { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok() { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }
err() { printf '\033[0;31m✗ %s\033[0m\n' "$*" >&2; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "$1 is required"; exit 1; }
}

require_cmd "$KUBECTL"
require_cmd openssl

# 1) Discover the colima node InternalIP the k3s orchestrator uses to reach the
#    docker-published PG/Redis bus. Overridable via DOCKER_BUS_IP for non-colima.
DOCKER_BUS_IP="${DOCKER_BUS_IP:-$("$KUBECTL" get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')}"
if [ -z "$DOCKER_BUS_IP" ]; then
  err "Could not discover k3s node InternalIP (docker bus address). Set DOCKER_BUS_IP=<colima-vm-ip> and retry."
  err "Discover it with: $KUBECTL get node -o wide"
  exit 1
fi
log "Docker bus address (k3s node InternalIP): $DOCKER_BUS_IP"

# 2) Namespaces first — bootstrap-egress-pki.sh prechecks that all three exist.
log "Applying namespaces"
"$KUBECTL" apply -f "$BASE/00-namespaces.yaml"

# 3) Bootstrap the in-cluster egress PKI (idempotent: kubectl apply of secrets).
log "Bootstrapping in-cluster egress PKI (mTLS control<->Envoy)"
KUBECTL="$KUBECTL" bash "$K8S_DIR/pki/bootstrap-egress-pki.sh"

# 4) Render the overlay with the discovered bus IP substituted, then apply.
log "Applying sandbox-execution-plane overlay (bus IP substituted)"
"$KUBECTL" kustomize "$OVERLAY" \
  | sed "s|__DOCKER_BUS_IP__|${DOCKER_BUS_IP}|g" \
  | "$KUBECTL" apply -f -

# 5) Wait on the ONLY workloads this plane owns — orchestrator Deployment and the
#    egress Envoy DaemonSet. Never wait on a deleted control-plane Deployment
#    (that was the stale ProgressDeadline trap).
log "Waiting for orchestrator rollout"
"$KUBECTL" -n "$CONTROL_NS" rollout status deployment/joysafeter-orchestrator --timeout=300s
log "Waiting for egress Envoy DaemonSet rollout"
"$KUBECTL" -n "$EGRESS_NS" rollout status daemonset/joysafeter-egress-envoy --timeout=300s

ok "Sandbox execution plane is ready (orchestrator + egress Envoy + PKI + sandbox policy)"
echo ""
echo "Docker bus address in use: $DOCKER_BUS_IP (joysafeter-docker-bus hostAlias)"
echo "Watch dynamic sandbox pods:"
echo "  $KUBECTL -n ${JOYSAFETER_K8S_NAMESPACE:-joysafeter-sandboxes} get pods -l app.kubernetes.io/name=joysafeter-sandbox -w"
```

- [ ] **Step 2: `chmod +x deploy/k8s/apply-sandbox-plane.sh`** — Expected: file is executable (`ls -l` shows `-rwxr-xr-x`).

- [ ] **Step 3: Run `bash -n deploy/k8s/apply-sandbox-plane.sh`** — Expected: exit 0, no syntax error.

- [ ] **Step 4: Static-check the sed token exists in the render** — `kubectl kustomize deploy/k8s/overlays/sandbox-plane-local | grep -c '__DOCKER_BUS_IP__'` — Expected: `1` (the sed substitution has exactly one target; if 0, the hostAliases patch from Task 2 is missing).

- [ ] **Step 5: Commit** — `git add deploy/k8s/apply-sandbox-plane.sh` + `git commit -m "feat(deploy): add sandbox-plane apply script with auto-PKI and rollout waits"`

---

### Task 4: Add the docker k8s-bus compose face (local MINUS orchestrator MINUS docker egress plane; publish PG/Redis to the boundary)

**Files:**
- Create: `deploy/docker-compose.k8s-bus.yml` (compose override that removes the docker sandbox plane and hardens PG/Redis publishing)
- Validate: `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.k8s-bus.yml --profile local-redis config`

**Interfaces:**
- Consumes: base `deploy/docker-compose.yml` — services `postgres` (publishes `5432`), `redis` (profile `local-redis`, publishes `6379`), `api`, `worker`, `frontend`, `skillspector` (business/default profile); the `sandbox` profile services `orchestrator-rs`, `joysafeter-envoy` (the docker per-sandbox egress plane).
- Produces: a compose face for k8s mode = `docker compose -f docker-compose.yml -f docker-compose.k8s-bus.yml --profile local-redis up -d` bringing up ONLY postgres+redis+api+worker+frontend+skillspector (NO `--profile sandbox`, so orchestrator-rs and joysafeter-envoy never start). PG on `0.0.0.0:5432` and Redis on `0.0.0.0:6379` are reachable from k3s Pods at the colima node IP (Task 2/3's `joysafeter-docker-bus`). This is invoked by `deploy.sh local` when a k8s-mode flag is set (Task 6 wires the docker side; the override file is the mechanism).
  - Note: the docker sandbox plane is excluded simply by NOT passing `--profile sandbox`; this override file additionally pins PG/Redis publish binds to `0.0.0.0` so k3s can reach them, and documents the topology. It does NOT redefine api/worker/frontend/skillspector (they inherit unchanged from base — pure-docker regression safe).

- [ ] **Step 1: Write `deploy/docker-compose.k8s-bus.yml`** with exactly this content:
```yaml
# =============================================================================
# k8s-mode docker face: business services + the PG/Redis BUS in docker; the
# sandbox execution plane (orchestrator-rs + egress Envoy + sandbox Pods) runs
# in k8s (deploy/k8s/apply-sandbox-plane.sh). Overlay ON TOP of docker-compose.yml.
#
# Usage (k8s mode docker side):
#   docker compose -f docker-compose.yml -f docker-compose.k8s-bus.yml \
#     --profile local-redis up -d
#   # NOTE: NO `--profile sandbox` — orchestrator-rs + joysafeter-envoy stay OUT
#   #       of docker in k8s mode; they run in k8s.
#
# The k8s orchestrator reaches these over plain TCP at the colima node InternalIP
# (see deploy/k8s/apply-sandbox-plane.sh -> joysafeter-docker-bus hostAlias).
# =============================================================================
services:
  # Bind PG to all interfaces so k3s Pods (via the colima VM IP) can connect.
  postgres:
    ports:
      - "0.0.0.0:${POSTGRES_PORT_HOST:-5432}:5432"

  # Bind Redis to all interfaces so k3s Pods can reach the global task queue.
  redis:
    ports:
      - "0.0.0.0:${REDIS_PORT_HOST:-6379}:6379"
```
  Rationale: base `docker-compose.yml` already publishes `${POSTGRES_PORT_HOST:-5432}:5432` and `${REDIS_PORT_HOST:-6379}:6379` (which docker binds to `0.0.0.0` by default), so this override is mostly explicit/documentary; keeping it a thin override avoids duplicating the full service definitions and keeps pure-docker (base-only) behavior byte-identical. The orchestrator + docker egress plane are excluded by profile selection, not by redefinition.

- [ ] **Step 2: Run `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.k8s-bus.yml --profile local-redis config --services`** — Expected: the printed service list contains `postgres`, `redis`, `api`, `worker`, `frontend`, `skillspector` and does NOT contain `orchestrator-rs` or `joysafeter-envoy` (they are `sandbox`-profiled and not selected).

- [ ] **Step 3: Confirm PG/Redis publish binds** — `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.k8s-bus.yml --profile local-redis config | grep -A3 -E 'published: "?(5432|6379)'` — Expected: both show `host_ip: 0.0.0.0` (or the merged `0.0.0.0:5432`/`0.0.0.0:6379` publish).

- [ ] **Step 4: Confirm pure-docker (base-only) still renders unchanged** — `docker compose -f deploy/docker-compose.yml --profile local-redis --profile sandbox config --services | sort` — Expected: includes `orchestrator-rs` and `joysafeter-envoy` (base behavior untouched — the override file only affects invocations that pass `-f docker-compose.k8s-bus.yml`).

- [ ] **Step 5: Commit** — `git add deploy/docker-compose.k8s-bus.yml` + `git commit -m "feat(deploy): add k8s-bus docker compose face (business + PG/Redis bus, no docker sandbox plane)"`

---

### Task 5: Add a `deploy.sh local --k8s-bus` docker-side bring-up (business + bus only, no docker sandbox plane)

**Files:**
- Modify: `deploy/deploy.sh` — `run_local_compose()` (~lines 795-814), `run_local_migrations()` (~lines 743-762), and the `local)` dispatch (~lines 2015-2020) to accept a `--k8s-bus` flag selecting the k8s-bus compose face.
- Validate: `bash -n deploy/deploy.sh` and `deploy/deploy.sh local --k8s-bus --help` (dry inspection of the composed command via a `--dry-run`/echo path, see Step 3)

**Interfaces:**
- Consumes: `deploy/docker-compose.k8s-bus.yml` (Task 4); the existing `compose_local_env` helper and `--profile local-redis`/`--profile sandbox` machinery.
- Produces: `deploy.sh local --k8s-bus` — brings up the docker side for k8s mode: `postgres redis api worker frontend skillspector` (via `-f docker-compose.k8s-bus.yml --profile local-redis`, NO `--profile sandbox`), runs migrations against the docker PG. Plain `deploy.sh local` (no flag) is UNCHANGED (pure-docker baseline). This is the docker half that Task 7's acceptance brings up before `deploy.sh k8s deploy`.

- [ ] **Step 1: Add a k8s-bus compose helper + flag parsing in `run_local_compose()`.** Read `deploy/deploy.sh` lines 795-814 and 743-762 first. Introduce a module-level `LOCAL_K8S_BUS=false` and, in the `local)` dispatch (~line 2019, currently `run_local_compose`), parse a leading `--k8s-bus` arg to set `LOCAL_K8S_BUS=true` before calling `run_local_compose`. Then in `run_local_compose()` and `run_local_migrations()`, when `LOCAL_K8S_BUS=true`, add `-f "$SCRIPT_DIR/docker-compose.k8s-bus.yml"` to the compose invocation and DROP `--profile sandbox` (bring up only `postgres redis skillspector api worker frontend`). Concretely, replace the bring-up line (currently `compose_local_env --profile local-redis --profile sandbox up -d --no-build`) with a branch:
```bash
    if [ "${LOCAL_K8S_BUS:-false}" = true ]; then
        # k8s mode docker side: business + PG/Redis bus only; sandbox plane runs in k8s.
        compose_local_env -f "$SCRIPT_DIR/docker-compose.k8s-bus.yml" \
            --profile local-redis up -d --no-build \
            postgres redis skillspector api worker frontend
    else
        compose_local_env --profile local-redis --profile sandbox up -d --no-build
    fi
```
  and similarly guard `run_local_migrations()`'s `up -d --no-build postgres redis skillspector` / `run --rm db-init` lines to include `-f "$SCRIPT_DIR/docker-compose.k8s-bus.yml"` when `LOCAL_K8S_BUS=true` (the migration targets postgres/redis/skillspector/db-init, none of which are sandbox-profiled, so only the `-f` file needs adding).
  IMPORTANT: verify `compose_local_env` forwards arbitrary `-f`/args (grep its definition ~line 837 `compose_local_env ... "$@"`); if it hardcodes the compose file list, thread the extra `-f` through it. Do NOT alter the non-`--k8s-bus` code path.

- [ ] **Step 2: Run `bash -n deploy/deploy.sh`** — Expected: exit 0, no syntax error.

- [ ] **Step 3: Dry-inspect the composed command.** Add a one-off `echo`-guarded check (or use `set -x` transiently in a scratch shell): run `LOCAL_K8S_BUS=true bash -c 'source deploy/deploy.sh 2>/dev/null; declare -f run_local_compose'` is not reliable; instead assert via `grep`: `grep -n 'docker-compose.k8s-bus.yml' deploy/deploy.sh` — Expected: at least the two references added in `run_local_compose` and `run_local_migrations`. And `grep -n 'LOCAL_K8S_BUS' deploy/deploy.sh` — Expected: the flag default, the dispatch parse, and both branch guards.

- [ ] **Step 4: Confirm pure-docker path untouched** — `grep -n 'profile local-redis --profile sandbox up -d --no-build' deploy/deploy.sh` — Expected: the original line still present inside the `else` branch (the `LOCAL_K8S_BUS=false` default keeps `deploy.sh local` byte-identical in behavior).

- [ ] **Step 5: Commit** — `git add deploy/deploy.sh` + `git commit -m "feat(deploy): add deploy.sh local --k8s-bus docker-side bring-up (business + bus, no docker sandbox plane)"`

---

### Task 6: Rewrite `deploy.sh k8s deploy` to apply the sandbox execution plane only (auto-PKI + correct rollout waits)

**Files:**
- Modify: `deploy/deploy.sh` — `k8s_deploy()` (lines 992-999), the K8S_CORE_IMAGES/help text (lines 883-918) as needed, and the comment block at 870-877.
- Validate: `bash -n deploy/deploy.sh`; `deploy/deploy.sh k8s help`

**Interfaces:**
- Consumes: `deploy/k8s/apply-sandbox-plane.sh` (Task 3); existing `require_k8s_context`, `k8s_detect_cluster`, `k8s_load_images` (colima = no-op import), `k8s_warn_missing_core_images`.
- Produces: `deploy.sh k8s deploy` now delegates to `apply-sandbox-plane.sh` (NOT `k3s-smoke.sh`). It applies ONLY the sandbox execution plane, auto-runs PKI, and waits on `deployment/joysafeter-orchestrator` + `daemonset/joysafeter-egress-envoy` — never on api/worker/frontend (deleted from this plane), avoiding the stale ProgressDeadline trap.

- [ ] **Step 1: Repoint `k8s_deploy()`.** Read lines 992-999. Replace the body's final two lines (`log_info "...委托 k3s-smoke.sh..."` and `KUBECTL="$KUBECTL_BIN" "$K8S_DIR/k3s-smoke.sh"`) with:
```bash
    log_info "应用 JoySafeter 沙箱执行平面（orchestrator + egress Envoy + sandbox policy + 自动 PKI），委托 apply-sandbox-plane.sh..."
    KUBECTL="$KUBECTL_BIN" "$K8S_DIR/apply-sandbox-plane.sh"
```
  Keep the preceding `require_k8s_context`, context log, `k8s_warn_missing_core_images`, `k8s_load_images` lines (colima shares the docker runtime, so `:latest` images are already visible — no import needed).

- [ ] **Step 2: Update the k8s command comment block (lines 870-877)** so the `deploy` line reads: `deploy   应用沙箱执行平面（orchestrator + egress Envoy DaemonSet + sandbox RBAC/policy + 自动 PKI），api/worker/frontend/skillspector/PG/Redis 由 docker 承载（委托 apply-sandbox-plane.sh，非破坏性）`. Update `k8s_usage()` (lines 897-918) `deploy` description similarly and its 前置条件 to mention the docker bus must be up first: `先启动 docker 侧总线与业务服务：$0 local --k8s-bus`.

- [ ] **Step 3: Run `bash -n deploy/deploy.sh`** — Expected: exit 0.

- [ ] **Step 4: Confirm the delegation switched** — `grep -n 'apply-sandbox-plane.sh\|k3s-smoke.sh' deploy/deploy.sh` — Expected: `k8s_deploy()` now references `apply-sandbox-plane.sh`; NO remaining reference to `k3s-smoke.sh` inside `k8s_deploy()` (any lingering `k3s-smoke.sh` reference elsewhere is handled in Task 7's deletion).

- [ ] **Step 5: Run `deploy/deploy.sh k8s help`** — Expected: prints the updated usage with the sandbox-execution-plane `deploy` description and the `local --k8s-bus` prerequisite; exit 0.

- [ ] **Step 6: Commit** — `git add deploy/deploy.sh` + `git commit -m "feat(deploy): rewrite k8s deploy to apply sandbox execution plane only"`

---

### Task 7: Retire the old full-stack `k3s-smoke.sh` deploy path (grep-verify no other consumers first)

**Files:**
- Delete: `deploy/k8s/k3s-smoke.sh` (the "apply the whole stack" path, now superseded)
- Modify: `deploy/k8s/README.md` if it references `k3s-smoke.sh` for the deploy flow
- Validate: `grep -rn 'k3s-smoke.sh' deploy/ backend/ docs/` returns no live consumer

**Interfaces:**
- Consumes: confirmation that `k8s_deploy()` no longer calls `k3s-smoke.sh` (Task 6).
- Produces: a single k8s deploy path (`apply-sandbox-plane.sh`). No dead full-stack smoke logic.

- [ ] **Step 1: Grep for ALL references before deleting** — `grep -rn 'k3s-smoke.sh' deploy/ docs/ backend/ .github/ 2>/dev/null` — Expected after Task 6: references only in `deploy/k8s/k3s-smoke.sh` itself and possibly `deploy/k8s/README.md` / historical docs. If any OTHER live script (e.g. CI workflow, another smoke) sources or invokes it, STOP and convert that consumer to `apply-sandbox-plane.sh` (or the appropriate egress/task smoke) in this same task before deleting.

- [ ] **Step 2: Check the k3s-task-smoke / k3s-egress-smoke don't depend on k3s-smoke.sh's full-stack apply** — `grep -n 'k3s-smoke' deploy/k8s/k3s-task-smoke.sh deploy/k8s/k3s-egress-smoke.sh deploy/k8s/k3s-long-run.sh 2>/dev/null` — Expected: no output (they run against an already-deployed cluster / their own apply). If any DO invoke it, repoint them to `apply-sandbox-plane.sh` here.

- [ ] **Step 3: Delete `deploy/k8s/k3s-smoke.sh`** — `git rm deploy/k8s/k3s-smoke.sh`.

- [ ] **Step 4: Fix `deploy/k8s/README.md`** — read it; if it documents `k3s-smoke.sh` as THE deploy step, replace that with `apply-sandbox-plane.sh` (or `deploy.sh k8s deploy`) and note the k8s-mode docker prerequisite (`deploy.sh local --k8s-bus`). If README has no such reference, skip the edit.

- [ ] **Step 5: Verify no dangling references** — `grep -rn 'k3s-smoke.sh' deploy/ 2>/dev/null` — Expected: no output (all live references removed; historical `docs/superpowers/plans/*` may still mention it — those are historical records, leave them).

- [ ] **Step 6: Run `bash -n deploy/deploy.sh` and `bash -n deploy/k8s/apply-sandbox-plane.sh`** — Expected: both exit 0 (nothing broke from the deletion).

- [ ] **Step 7: Commit** — `git add deploy/k8s/k3s-smoke.sh deploy/k8s/README.md` (the `git rm` already stages the deletion; add README only if edited) + `git commit -m "chore(deploy): retire full-stack k3s-smoke.sh deploy path"`

---

### Task 8: Acceptance validation — pure-docker regression + k8s-mode sandbox-Pod git-egress E2E

**Files:**
- No source edits. This is a live-deploy validation task. If a step FAILS, fix in a focused follow-up commit and re-run; do not paper over.
- Validate: the assertions below (live cluster + live docker).

**Interfaces:**
- Consumes: everything from Tasks 1-7 (`overlays/sandbox-plane-local`, `apply-sandbox-plane.sh`, `docker-compose.k8s-bus.yml`, `deploy.sh local --k8s-bus`, `deploy.sh k8s deploy`), the in-repo PKI, and the already-committed sandbox-runner `repos.rs` git-egress fix (preemptive Basic `Authorization` header, committed `112b4e2b`) plus the orchestrator credential broker (`credential_broker.rs:111` logs `credential broker resolved route`).
- Produces: a validated two-topology deploy. No new artifacts.

**Part A — pure-docker regression (baseline MUST stay green):**

- [ ] **Step 1: Bring up pure-docker** — `deploy/deploy.sh local` (NO flag). Expected: all containers `Up (healthy)` — `docker compose -p deploy ps` shows api/worker/frontend/skillspector/postgres/redis/orchestrator-rs/joysafeter-envoy healthy.
- [ ] **Step 2: Register a user + create a claude agent + a git-repo session, fire a task** through the docker api (`http://localhost:8000`). Use a real public repo `https://github.com/octocat/Hello-World.git` with a FAKE token so the git route triggers. Expected: task runs, sandbox is a DOCKER container, and the setup-stage git clone PASSES ext_authz (orchestrator logs `credential broker resolved route ... header=authorization`), reaches real github, and is rejected ONLY on the fake token (NOT a 403 identity-deny). This is the known-green docker behavior — confirms the baseline is intact.
- [ ] **Step 3: Tear down pure-docker cleanly** before the k8s-mode run — `deploy/deploy.sh down` (or `docker compose -p deploy --profile local-redis --profile sandbox down`). Expected: docker stack down so the k8s-mode docker face (which reuses ports 5432/6379/8000) can start fresh.

**Part B — k8s-mode E2E (the original goal):**

- [ ] **Step 4: Bring up the docker side for k8s mode** — `deploy/deploy.sh local --k8s-bus`. Expected: postgres+redis+api+worker+frontend+skillspector `Up (healthy)`; NO `orchestrator-rs`/`joysafeter-envoy` container (they run in k8s). `docker compose -p deploy ps` confirms absence of the sandbox-plane containers. Migrations ran against docker PG.
- [ ] **Step 5: Ensure colima k3s context is current** — `kubectl config current-context` = `colima` (or the intended k3s). If not, `colima start --kubernetes` (stop-then-start if already running so `--kubernetes` takes effect, per the colima env note) and re-select. Expected: `kubectl get node` shows the single colima node Ready.
- [ ] **Step 6: Deploy the sandbox execution plane** — `deploy/deploy.sh k8s deploy`. Expected: script prints the discovered docker bus IP (colima node InternalIP), bootstraps PKI (all 5 secrets + the sandbox downstream CA ConfigMap), applies the overlay, and BOTH `rollout status deployment/joysafeter-orchestrator` and `rollout status daemonset/joysafeter-egress-envoy` report ready within 300s. No `ProgressDeadlineExceeded`. Verify the orchestrator Pod is Running (not `ContainerCreating`/`FailedMount`) — `kubectl -n joysafeter-control get pods -l app.kubernetes.io/name=joysafeter-orchestrator` shows `Running`.
- [ ] **Step 7: Confirm the orchestrator actually reached the docker bus** — `kubectl -n joysafeter-control logs deployment/joysafeter-orchestrator | grep -iE 'connected|postgres|redis|scheduler'` — Expected: evidence of a successful Postgres connection + Redis queue poll loop start (no connection-refused to `joysafeter-docker-bus`). If it can't connect, re-verify `DOCKER_BUS_IP` (`kubectl get node -o wide`) and that docker published 5432/6379 on `0.0.0.0` (Task 4).
- [ ] **Step 8: Register a user + claude agent + git-repo session, fire a task** via the docker api (`http://localhost:8000`) — same repo `https://github.com/octocat/Hello-World.git` + a FAKE token. Expected: api writes the task to docker Postgres + `rpush joysafeter:global_queue` on docker Redis; the k8s orchestrator pops it and creates a sandbox **Pod** — `kubectl -n joysafeter-sandboxes get pods -l app.kubernetes.io/name=joysafeter-sandbox` shows a `joysafeter-<uuid>` Pod reaching `Running`.
- [ ] **Step 9: Assert the k8s-plane git egress passes ext_authz (the acceptance criterion).** In the orchestrator logs: `kubectl -n joysafeter-control logs deployment/joysafeter-orchestrator | grep 'credential broker resolved route'` — Expected: a line `route_id=git:<slug> header=authorization` (the git route resolved + credential injected, proving the in-cluster ext_authz accepted the sandbox's runner-token identity). Then confirm the clone reached the REAL upstream and was rejected ONLY on the fake token — inspect the sandbox Pod / task result: the git clone fails with an upstream AUTH error (bad credentials from github), NOT a 403 identity-deny from Envoy ext_authz. This proves the already-committed `repos.rs` preemptive-Basic-`Authorization` git-egress fix holds on the k8s plane exactly as on docker.
- [ ] **Step 10: Confirm the boundary shape** — the sandbox Pod's egress went sandbox Pod → in-cluster egress Envoy (`joysafeter-egress-envoy.joysafeter-egress`) → in-cluster orchestrator xDS(18000)+ext_authz(18090) over mTLS → real upstream; and the only docker↔k8s traffic was orchestrator→docker PG/Redis. Spot-check: `kubectl -n joysafeter-egress get pods -l app.kubernetes.io/name=joysafeter-egress-envoy` all Running/Ready; `kubectl -n joysafeter-egress logs daemonset/joysafeter-egress-envoy | grep -iE 'cds|lds|ads'` shows it received config from the in-cluster xDS (no `NO_SUPPORTED_VERSIONS_ENABLED` / handshake error).
- [ ] **Step 11: Record the outcome.** If all assertions pass, the refactor is validated end-to-end. If any fail, open a focused follow-up commit (staged paths only) to fix and re-run the failing part. No commit is required for a pure validation pass (nothing changed); if a fix was needed, commit it with a `fix(deploy): ...` message and explicit paths.

---

## Self-review

**Spec-coverage (every spec section → task):**
- Spec "k8s side — applies the sandbox execution plane" → Task 1 (overlay carve) + Task 3 (apply script + PKI) + Task 6 (deploy.sh rewrite).
- Spec "orchestrator env points DATABASE_URL/REDIS_URL at the docker bus" → Task 2.
- Spec "docker side — compose profile/overlay for k8s mode" → Task 4 (compose face) + Task 5 (deploy.sh bring-up).
- Spec "Cross-boundary wiring (colima host address; PIN)" → Task 2 (hostAlias mechanism) + Task 3 (live InternalIP discovery command + `DOCKER_BUS_IP` override knob).
- Spec "all egress mTLS in-cluster, PKI SANs unchanged" → Task 1 Steps 4 (mTLS stays true) + Task 3 (bootstrap reuses in-cluster SANs).
- Spec "Deletions / cleanup" → Task 1 (carve excludes docker services) + Task 7 (retire k3s-smoke.sh).
- Spec "Reconcile overlays/local & overlays/sandbox-plane to a single k8s face" → RESOLVED: `overlays/local` is full-stack in-cluster testing (left as-is, not the deploy face); `overlays/sandbox-plane` is the company-PRODUCTION overlay (external PG/Redis, immutable tags, external secrets — untouched); the NEW `overlays/sandbox-plane-local` is the single LOCAL k8s deploy face for `deploy.sh k8s deploy`. Three distinct shapes, no collision. (Documented in Task 1's header comment.)
- Spec "Testing / acceptance (pure-docker regression + k8s sandbox-Pod git egress)" → Task 8 Parts A & B.

**Placeholder scan:** No "TBD"/"add appropriate"/"similar to Task N". The one intentional token `__DOCKER_BUS_IP__` is a runtime substitution slot with the exact discovery command (`kubectl get node -o jsonpath=...`) and override knob (`DOCKER_BUS_IP`) specified — not an unresolved placeholder. All YAML/bash content is inlined in full (repeated, not cross-referenced).

**Consistency of names across tasks:**
- Overlay path: `deploy/k8s/overlays/sandbox-plane-local` — consistent in Tasks 1, 2, 3, 6.
- Apply script: `deploy/k8s/apply-sandbox-plane.sh` — consistent in Tasks 3, 6, 7.
- Compose file: `deploy/docker-compose.k8s-bus.yml` — consistent in Tasks 4, 5.
- Flag: `deploy.sh local --k8s-bus` / var `LOCAL_K8S_BUS` — consistent in Tasks 5, 8.
- Bus hostAlias: `joysafeter-docker-bus` + token `__DOCKER_BUS_IP__` + env override `DOCKER_BUS_IP` — consistent in Tasks 2, 3, 8.
- PKI secret names + SANs match `bootstrap-egress-pki.sh` verbatim (`joysafeter-rust-xds-server-tls`, `joysafeter-egress-authz-server-tls`, etc.) — Tasks 1, 3.
- Rollout targets: `deployment/joysafeter-orchestrator` + `daemonset/joysafeter-egress-envoy` — consistent in Tasks 3, 6, 8.

**Confirmed decoupling (spec open item 4):** api/worker reach the orchestrator ONLY via the Redis bus — `app/joysafeter_shared/orchestrator_bridge/enqueue.py` does `redis.rpush("joysafeter:global_queue", task_id)`; cancel goes via `relay_sandbox_command_via_redis`. No direct gRPC/DNS coupling from api/worker to the orchestrator Service, so docker api/worker + k8s orchestrator sharing only the PG/Redis bus is safe. NO extra task needed. (`JOYSAFETER_K8S_ORCHESTRATOR_URL` in `01-config.yaml` is the SANDBOX RUNNER's dial-back URL — in-cluster, orchestrator-owned — not an api/worker dependency.)
