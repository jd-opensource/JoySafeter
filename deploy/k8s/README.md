# JoySafeter k3s local smoke

This directory is the first executable k3s path for validating the Rust
`K8sProvider`. It is intentionally smaller than the production target: local
PostgreSQL and Redis run inside the cluster with `emptyDir` storage, and
frontend/API are exposed through k3d NodePort mappings or `kubectl port-forward`.

## Bring up local k3s with k3d

```bash
k3d cluster create --config deploy/k8s/k3d-cluster.yaml
```

Build the images the manifests reference:

```bash
cd deploy
./deploy.sh build --all --arch arm64
```

For amd64 Docker daemons, use `--arch amd64`.

Apply the staged smoke deployment:

```bash
cd ..
deploy/k8s/k3s-smoke.sh
```

The script applies namespaces/RBAC, starts PostgreSQL/Redis/SkillSpector, runs
`alembic upgrade head`, then starts API/worker/orchestrator/frontend. When a
k3d cluster named `joysafeter` is present, it also imports locally built Docker
images into the k3s cluster.

This script is non-destructive for application data: it does not delete
namespaces, pods, PVCs, database rows, users, agents, tasks, or old migration
Jobs. Each migration run uses a unique Job name so previous evidence remains
available.

## Access

The k3d config maps local ports:

- API: `http://localhost:8000/health`
- Frontend: `http://localhost:3000`

If direct ports are unavailable, use port-forwarding:

```bash
kubectl -n joysafeter-control port-forward svc/api 8000:8000
kubectl -n joysafeter-control port-forward svc/frontend 3000:3000
```

Open:

- Frontend: `http://localhost:3000`
- API health: `http://localhost:8000/health`

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
K8s model tasks also require the platform egress gateway and explicit provider
capability switch:

```text
JOYSAFETER_EGRESS_GATEWAY_URL=http://joysafeter-egress-gateway.joysafeter-control.svc.cluster.local:8088
JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN=<strong-random-control-token>
JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=true
```

The base manifests deploy `joysafeter-egress-gateway` but keep
`JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=false` so local k3s remains
fail-closed until a validation run explicitly opts in. The gateway control
token is a platform control-plane secret; never reuse a model/provider key.

Watch dynamic sandbox pods:

```bash
kubectl -n joysafeter-sandboxes get pods \
  -l app.kubernetes.io/name=joysafeter-sandbox -w
```

## API-driven sandbox smoke

After the stack is ready, run a real API -> worker -> Rust orchestrator -> k3s
Pod -> runner validation:

```bash
deploy/k8s/k3s-task-smoke.sh
```

The script creates a smoke user, signs in, creates an agent, submits a task,
waits for the sandbox Pod to become Ready, and verifies the runner saw
`RunnerReady` and `StartTask`. It preserves all created records and pods for
inspection.

## Secret-backed egress smoke

To validate the production egress path, run the dedicated smoke with a real
Anthropic-compatible Secret. For JDCloud-style gateways, set
`ANTHROPIC_BASE_URL` to the gateway base URL:

```bash
ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=https://ai-api.jdcloud.com/anthropic \
deploy/k8s/k3s-egress-smoke.sh
```

The script patches only the k3s ConfigMap/Secret values needed to enable the
gateway, restarts the gateway and orchestrator Deployments so they pick up the
config, then creates uniquely named smoke data through the API. It verifies:

- gateway `/readyz` is healthy;
- the API allowlist accepts and tests the Secret base URL;
- a limited-networking Environment is used;
- the sandbox Pod env has gateway placeholder credentials, not the real model
  key;
- the sandbox Pod annotations do not persist env values through
  `kubectl.kubernetes.io/last-applied-configuration`;
- the per-sandbox NetworkPolicy allows only DNS, orchestrator, and gateway;
- the model-backed Task reaches `completed` and outputs `K3S_EGRESS_OK`.

If you only want to prove gateway connectivity with a Secret whose model is not
authorized for the key, set `ALLOW_UPSTREAM_MODEL_ERROR=true`. That mode still
requires Pod, NetworkPolicy, and gateway checks, but it does not count as a
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
- `JOYSAFETER_ENVOY_ENABLED=false` is intentional here because K8s uses the
  platform `joysafeter-egress-gateway` path rather than Docker/Envoy.
- Production secret-backed K8s requires `joysafeter-egress-gateway` or an
  equivalent provider capability. Sandboxes must only receive placeholder model
  credentials and must reach model/MCP/Git/external services through that
  platform boundary.
- The repository now contains a `joysafeter-egress-gateway` binary with
  fail-closed sandbox token auth, route authorization, header stripping,
  credential injection, upstream forwarding, and an authenticated control API
  for installing/revoking per-sandbox policies. The orchestrator also has a
  low-level gateway control client, `K8sEgressManager` scaffold, and K8s
  limited-networking LLM env rewrite to gateway routes. It can render and apply
  per-sandbox NetworkPolicies that allow only DNS, orchestrator, and gateway
  egress. On orchestrator restart, it can recover live limited-networking
  sandbox policies from DB/Vault and reinstall them into the gateway without
  persisting provider credentials in gateway files or K8s resources. K8s only
  declares `has_egress_management=true` when
  `JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=true` and the gateway/control-plane
  targets are configured.
- The current gateway policy store is in-memory. For multi-replica production
  gateway HA, add a reconciled/shared policy backend that stores no plaintext
  provider secrets, or make the orchestrator continuously re-derive and
  reinstall policies from Vault/DB on gateway instance changes.
- The current provider shells out to `kubectl`; the orchestrator image includes
  kubectl for this path. Replacing this with a native Rust Kubernetes client is
  the next hardening step.

`local-smoke.sh` is kept as a compatibility wrapper and delegates to
`k3s-smoke.sh`.
