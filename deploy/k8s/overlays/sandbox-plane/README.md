# Sandbox Plane Overlay

This overlay deploys only the JoySafeter sandbox execution plane into a
self-hosted k3s cluster. The company production environment remains responsible
for frontend, backend API, worker, PostgreSQL, Redis, object storage, and general
business ingress.

## Runs In This Cluster

- `joysafeter-orchestrator` for K8s sandbox lifecycle, runner gRPC, ext_authz,
  and single-active durable Rust xDS from PostgreSQL policy state.
- `joysafeter-egress-envoy` as the only sandbox egress data plane.
- Sandbox namespaces, quotas, RBAC, and NetworkPolicies.

## Not Deployed Here

- `api`, `worker`, `frontend`
- `postgres`, `redis`, `joysafeter-db-init`
- `skillspector`

## Required Platform Inputs

1. Create `joysafeter-secret` in `joysafeter-control` from `secret.env.example`
   through ExternalSecrets, SealedSecrets, Vault, or a one-time `kubectl create
   secret` command. Do not commit real secrets.
2. Replace every `CHANGE_ME_*` value in `kustomization.yaml` with company
   production endpoints and immutable image tags.
3. Provision the egress TLS Secrets and sandbox downstream CA bundle. For a
   validation cluster only, `deploy/k8s/pki/bootstrap-egress-pki.sh` can create
   short-lived local PKI.
4. Restrict company PostgreSQL/Redis firewalls so only the sandbox-plane nodes or
   NAT/VPN egress can connect, with TLS enabled.

## Validate

```bash
OVERLAY=deploy/k8s/overlays/sandbox-plane \
SMOKE_IMAGE=<internal-image-with-curl> \
deploy/k8s/validate-sandbox-plane-readiness.sh
```

After applying this overlay, validate the full cross-environment path through
the company backend API:

```bash
API_URL=https://<company-api-host> deploy/k8s/k3s-task-smoke.sh

API_URL=https://<company-api-host> \
ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=... \
ANTHROPIC_MODEL=... \
deploy/k8s/k3s-egress-smoke.sh
```
