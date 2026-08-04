# JoySafeter k3s Sandbox Plane

This directory contains Kubernetes manifests for two different purposes:

- `deploy/k8s/overlays/sandbox-plane/` — production entry for a self-hosted k3s sandbox execution plane. Company-managed production environments run frontend, backend API, worker, PostgreSQL, Redis, object storage, and business ingress.
- `deploy/k8s/base/`, `deploy/k8s/overlays/local/`, and the `k3s-*-smoke.sh` scripts — local or validation stacks. They may deploy local API/frontend/worker/PostgreSQL/Redis and are not the production shape when company infrastructure owns those services.

## Production Sandbox Plane

Use this when only sandbox-related services should run in k3s:

```bash
kubectl apply -f deploy/k8s/base/00-namespaces.yaml

# Create joysafeter-secret from your company secret manager or a local env file.
kubectl -n joysafeter-control create secret generic joysafeter-secret \
  --from-env-file=deploy/k8s/overlays/sandbox-plane/secret.env \
  --dry-run=client -o yaml | kubectl apply -f -

# Render/validate before applying.
OVERLAY=deploy/k8s/overlays/sandbox-plane \
SMOKE_IMAGE=<internal-image-with-curl> \
deploy/k8s/validate-sandbox-plane-readiness.sh

# Apply only the sandbox execution plane.
kubectl apply -k deploy/k8s/overlays/sandbox-plane
```

The sandbox-plane overlay intentionally does not deploy `api`, `worker`, `frontend`, `postgres`, `redis`, `joysafeter-db-init`, or `skillspector`.

After apply, validate through the company-managed Backend API:

```bash
API_URL=https://<company-api-host> deploy/k8s/k3s-task-smoke.sh

API_URL=https://<company-api-host> \
ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=... \
ANTHROPIC_MODEL=... \
deploy/k8s/k3s-egress-smoke.sh
```

## Local Full-Stack Smoke

The base/local path is only for local k3s/k3d validation. It starts local PostgreSQL, Redis, SkillSpector, API, worker, orchestrator, and frontend with development defaults. Do not use it as the production deployment when company infrastructure owns those services.

## Model Gateway Allowlist

The API validates model gateway hosts before saving/testing Secrets, and the
orchestrator uses the same allowlist when preparing sandbox LLM egress. Local
k3s defaults include:

```text
JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS=api.anthropic.com,api.openai.com,generativelanguage.googleapis.com,ai-api.jdcloud.com,*.jdcloud.com
```

`ANTHROPIC_BASE_URL=https://ai-api.jdcloud.com/...` is valid with this default.
Add any other private gateway host here before creating or testing a Secret.

This allowlist is necessary but not sufficient for production K8s. Secret-backed
tasks require the durable policy authority, node-local Envoy DaemonSet, and explicit
provider capability switch:

```text
JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED=true
JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=true
JOYSAFETER_EGRESS_ENVOY_CREDENTIAL_URL=https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8443
JOYSAFETER_EGRESS_ENVOY_FORWARD_PROXY_URL=https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8080
```

The base manifests keep both feature flags false, so a normal local deployment
remains fail-closed. Production must provision the required TLS Secrets through
cert-manager or enterprise PKI before enabling them. For ephemeral k3s proof
only, `deploy/k8s/pki/bootstrap-egress-pki.sh` creates short-lived certificates
under a temporary directory and never stores private keys in the repository.

Watch dynamic sandbox pods:

```bash
kubectl -n joysafeter-sandboxes get pods \
  -l app.kubernetes.io/name=joysafeter-sandbox -w
```

## Sandbox resource governance and diagnostics

`JOYSAFETER_MAX_CONCURRENT_TASKS` is a database-authoritative, cluster-wide
admission limit across all orchestrator replicas. Pending-to-scheduling claims
are serialized with a PostgreSQL transaction advisory lock and count both
`scheduling` and `running` tasks, so replicas cannot independently oversubscribe
the configured cap. Capacity-blocked Redis candidates are returned to the queue
instead of being discarded. `JOYSAFETER_MAX_SCHEDULING_TASKS` separately bounds
concurrent sandbox resolution work per orchestrator process, and
`JOYSAFETER_SCHEDULER_BATCH_SIZE` bounds each scheduler drain batch.

The base runtime config sets CPU, memory, and ephemeral-storage budgets through
`JOYSAFETER_SANDBOX_CPU`, `JOYSAFETER_SANDBOX_MEMORY_MB`, and
`JOYSAFETER_SANDBOX_DISK_MB`. The orchestrator applies each configured value as
both a Kubernetes request and limit, so the scheduler reserves the capacity and
the runner cannot burst beyond the same budget. Production overlays should tune
these values to match node capacity and workload size rather than removing them.

While a sandbox is provisioning, the orchestrator records the Pod phase,
scheduling conditions, container waiting/termination state, and recent Pod
Events in the sandbox `config.provisioning` document. Fatal startup failures,
such as an invalid image name or container configuration error, are persisted as
`config.setup_error` before normal task retry and sandbox cleanup run. When the
runner container produced output before failing, the same diagnostic document
includes at most 100 lines and 16 KiB in `details.runner_log_tail`; the
orchestrator never performs an unbounded Pod log read. Its ServiceAccount
therefore has read-only access to Pod logs and Events in the sandbox namespace
in addition to Pod lifecycle permissions.

## API-driven sandbox smoke

For the production `sandbox-plane` overlay, always set `API_URL` to the
company-managed Backend API. The default port-forward behavior below is only for
local full-stack k3s/k3d validation where `svc/api` exists in the cluster.

After the stack is ready, run a real API -> worker -> Rust orchestrator -> k3s
Pod -> runner validation:

```bash
deploy/k8s/k3s-task-smoke.sh
```

The script creates a smoke user, signs in, creates an agent, submits a task,
waits for the sandbox Pod to become Ready, and verifies the runner saw
`RunnerReady` and `StartTask`. It preserves all created records and pods for
inspection.

By default the script starts a temporary `kubectl port-forward svc/api` on a free
local port and points API calls at that forwarded service. Set `API_URL` only when
you intentionally want to target a specific API endpoint, for example a k3d
host-port mapping.

## Secret-backed egress smoke

For the production `sandbox-plane` overlay, always set `API_URL` to the
company-managed Backend API and use the same company production database/Redis
state as the k3s orchestrator.

To validate the production egress path, run the dedicated smoke with a real
Anthropic-compatible Secret. For JDCloud-style gateways, set
`ANTHROPIC_BASE_URL` to the gateway base URL:

```bash
ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=https://ai-api.jdcloud.com/anthropic \
ANTHROPIC_MODEL=Claude-Opus-4.8 \
deploy/k8s/k3s-egress-smoke.sh
```

Like the task smoke, this script defaults to a temporary `svc/api` port-forward.
Set `API_URL` explicitly only for a known-good endpoint that maps to the same
cluster you are validating.

The script installs ephemeral PKI, applies the TLS control/data-plane manifests, enables
the two feature flags for the run, then creates uniquely named smoke data
through the API. By default it restores the original flags on exit. Set
`BUILD_EGRESS_IMAGES=true` to rebuild and import the Rust orchestrator into a
local k3d cluster. It verifies:

- the active Rust orchestrator is ready and at least one Envoy node connects to
  embedded Rust ADS over mTLS;
- the API allowlist accepts and tests the Secret base URL;
- a limited-networking Environment is used;
- the sandbox Pod env has synthetic Envoy URLs, a combined CA bundle, and no
  real model key;
- the sandbox Pod annotations do not persist env values through
  `kubectl.kubernetes.io/last-applied-configuration`;
- the durable generation reaches `applied` with all required ACKs and no NACK;
- a wrong sandbox token receives `403` from ext_authz;
- direct upstream access to the configured Anthropic-compatible messages API
  endpoint, including the base URL scheme/host/port/path, is denied by the
  per-sandbox NetworkPolicy;
- the model-backed Task reaches `completed` and outputs `K3S_EGRESS_OK`.

Without a real Secret, run the structural preflight instead:

```bash
EGRESS_PREFLIGHT_ONLY=true deploy/k8s/k3s-egress-smoke.sh
```

Preflight still targets the live cluster: it checks the API-only runtime guard,
applies/rolls the node-local egress plane, validates the durable-authority config,
requires at least one Envoy node connected over mTLS ADS, and fails on Rust xDS
NACK / reconcile-failure / rollback / timeout metrics. It does not create
platform users, platform Secrets, Environments, Agents, Tasks, sandbox Pods, or
database rows, so it is not a substitute for full model-backed egress smoke.

If you only want to prove egress connectivity with a Secret whose model is not
authorized for the key, set `ALLOW_UPSTREAM_MODEL_ERROR=true`. That mode still
requires Pod, NetworkPolicy, mTLS, ADS, and authz checks, but it does not count as a
full model-backed production validation.

It does not delete users, Secrets, Environments, Agents, Tasks, Pods,
NetworkPolicies, Jobs, namespaces, PVCs, or database rows. Evidence is preserved
for inspection.

## Long-run validation

Run repeated task smokes without deleting historical evidence:

```bash
DURATION_SECONDS=21600 INTERVAL_SECONDS=300 deploy/k8s/k3s-long-run.sh
```

Defaults are 6 hours and one run every 5 minutes. Logs and observations are
written under `/tmp/joysafeter-k3s-long-run-*`. Set `MAX_RUNS=10` for a bounded
run, or `FAIL_FAST=true` if CI should stop at the first failed iteration.

For long-run Secret-backed egress validation:

```bash
VALIDATION_MODE=egress \
ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=https://ai-api.jdcloud.com/anthropic \
DURATION_SECONDS=21600 \
INTERVAL_SECONDS=300 \
deploy/k8s/k3s-long-run.sh
```

## Important production differences

- Do not use the local `emptyDir` PostgreSQL/Redis manifests in production.
- Do not use `latest` tags in production; replace them with immutable tags or
  digests.
- For bare-metal or VM k3s, push images to a private registry and set image
  references in a production overlay. `k3d image import` is local-only.
- `JOYSAFETER_ENVOY_ENABLED=false` disables the old per-sandbox Docker Envoy
  manager; Kubernetes uses one `joysafeter-egress-envoy` DaemonSet Pod per
  eligible execution node, and `internalTrafficPolicy: Local` keeps sandbox
  traffic on that node.
- Sandboxes receive only placeholder credentials and synthetic service URLs.
  Envoy performs routing and header stripping, Rust ext_authz binds the live
  runner token and resolves versioned credentials, and the embedded Rust xDS
  server owns node-local v2 policy publication and ACK/NACK state.
- Production PKI must use separate xDS, authz, and downstream trust domains.
  The controller does not mount the authz client private key; it exists only in
  the Envoy namespace.
- The Rust orchestrator exposes the production mTLS ADS listener on port `18000`
  with `JOYSAFETER_EGRESS_XDS_BIND=0.0.0.0:18000`. It uses the
  `joysafeter-rust-xds-server-tls` identity and exact Envoy client DNS SAN
  verification; the runner gRPC port `9090` remains outside the xDS trust
  boundary. `JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE=true` makes the
  active Rust orchestrator read durable desired generations from PostgreSQL,
  react to `joysafeter_egress_generation`, periodically reconcile, and install
  node-local snapshots for Envoys connected to the Rust ADS listener. This mode
  records nonce-correlated ACK/NACK audit results in
  `joysafeter_rust_xds_shadow_status` and accepted/failed generation lifecycle in
  `joysafeter_rust_xds_shadow_generations`. It also owns the canonical
  `joysafeter_egress_node_apply_status` and `joysafeter_egress_apply_status`
  rows consumed by the policy apply gate, so no separate publisher is required. On
  restart, the reconciler recompiles and restores
  each node group's latest accepted snapshot as last-known-good before attempting
  a newer desired candidate. NACKed generations stay quarantined durably, while
  in-process candidate publication remains gated on connected-node ACKs and rolls
  back immediately on NACK. `JOYSAFETER_EGRESS_XDS_ACK_TIMEOUT_MS` (default
  `30000`) also rolls an unacknowledged candidate back and persists it as failed
  without fabricating an Envoy exchange. Rust connection leases are refreshed
  in both `joysafeter_rust_xds_shadow_node_connections` and canonical
  `joysafeter_egress_node_connections` with
  `JOYSAFETER_EGRESS_XDS_NODE_LEASE_TTL_MS` (default `30000`), and accepted
  lifecycle rows persist their required type URLs, connected-node count, and
  required/acked quorum counts. The active orchestrator also exposes a JSON runtime
  snapshot at `/xds/status` on the control-plane health port; it reports connected
  streams/nodes, source and node groups, candidate/last-good counts, failed
  versions, current highest generation, and state revision. Cold standby or
  xDS-disabled replicas return HTTP 503. Prometheus text metrics are available at
  `/metrics` on the same port and cover active leadership, connected streams and
  nodes, candidate/last-good/failed gauges, ACK/NACK observations, snapshot
  install/restore/accept/rollback/timeout events, and reconciliation outcomes.
  The base Pod template includes scrape annotations for port `8081`.
- In HA deployments, every orchestrator Pod uses `/healthz` for Deployment/PDB
  readiness, while only the PostgreSQL lock holder patches
  `joysafeter.io/control-plane-active=true`. The orchestrator Service selects
  that label, so cold standbys remain rollout-healthy without receiving runner,
  ext_authz, or ADS traffic. `enableServiceLinks: false` is required because the
  Kubernetes-generated `JOYSAFETER_EGRESS_AUTHZ_PORT=tcp://...` variable would
  otherwise collide with the orchestrator's numeric authz-port configuration.
- The repository contains only the embedded Rust xDS control plane. Use the
  normal production release flow to deploy the Rust image, migrations, TLS
  mount, and Service first, then run `deploy/k8s/cutover-rust-xds.sh`; it patches
  only live xDS routing, requires a Rust ADS connection with healthy metrics,
  and scales any legacy controller Deployment to zero. Emergency rollback uses
  the previous validated Rust orchestrator and matching Envoy manifests.
- Sandbox images must contain `/bin/sh` and a standard system CA bundle path so
  the trust-bundle init container can append the downstream CA without replacing
  public roots.
- Runtime sandbox Pod lifecycle, exec, and NetworkPolicy apply all use the
  Kubernetes API directly; the orchestrator no longer shells out to kubectl for
  sandbox control-plane operations.
