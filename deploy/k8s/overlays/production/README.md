# Production Kubernetes Overlay

This overlay is the production target for the unified egress architecture:

- Rust orchestrator is the durable decision plane and credential plane.
- PostgreSQL is the desired-state and apply-state authority.
- Go egress-controller is the HA xDS control plane.
- The shared Envoy fleet is the only sandbox egress data plane.
- The legacy Rust HTTP egress-gateway Service and Deployment are removed.

The overlay intentionally removes the base development Secret and the
`emptyDir` PostgreSQL/Redis workloads. It will not become Ready until the
platform supplies production dependencies.

## Required Platform Inputs

Before applying the overlay:

1. Provide managed PostgreSQL and Redis connectivity. Either create stable
   Services named `postgres` and `redis` in `joysafeter-control`, or patch
   `POSTGRES_HOST`, `DATABASE_URL`, and `REDIS_URL` in `joysafeter-config`.
2. Create `joysafeter-secret` in `joysafeter-control` through ExternalSecrets,
   SealedSecrets, Vault, or an equivalent controller. It must provide at least:
   `POSTGRES_PASSWORD`, `SECRET_KEY`, `JWT_SECRET_KEY`,
   `JOYSAFETER_VAULT_ENCRYPTION_KEY`, and
   `JOYSAFETER_EGRESS_CONTROLLER_DATABASE_URL`.
3. Replace every `:latest` application and sandbox image with an immutable tag
   or digest from the production registry.
4. Provision the five egress TLS Secrets and the sandbox downstream CA bundle.
   `deploy/k8s/pki/bootstrap-egress-pki.sh` is suitable for validation clusters;
   production should use the platform PKI/cert-manager equivalent.
5. Patch public URLs, CORS origins, storage, resource limits, and registry pull
   credentials for the target environment.

Do not place model/provider credentials in Kubernetes manifests. They remain in
JoySafeter managed Secrets/Vault and are resolved per request by ext_authz.

## Render Gate

Render and inspect before apply:

```bash
kubectl kustomize deploy/k8s/overlays/production > /tmp/joysafeter-production.yaml

rg 'joysafeter-egress-gateway|local-dev-secret|local-dev-jwt' \
  /tmp/joysafeter-production.yaml && exit 1 || true
rg 'JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED: "true"' \
  /tmp/joysafeter-production.yaml
rg 'JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED: "true"' \
  /tmp/joysafeter-production.yaml
```

The rendered manifest must contain three orchestrator replicas, three
egress-controller replicas, three shared Envoy replicas, and no legacy gateway.

## Rollout Order

1. Apply namespaces, external service endpoints, external Secret, and PKI.
2. Run the Alembic migration Job and verify the egress control-plane tables.
3. Deploy egress-controller and wait for `/readyz` on every replica.
4. Deploy the shared Envoy fleet and verify xDS mTLS connectivity.
5. Deploy the orchestrator. Readiness checks both gRPC `9090` and dedicated
   ext_authz `18090`; the PDB requires two replicas to remain available.
6. Deploy API, worker, frontend, and sandbox policy resources.
7. Run the egress smoke and long-run validation before admitting production
   sandbox traffic.

## Required Validation

```bash
ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=https://ai-api.jdcloud.com/anthropic \
deploy/k8s/k3s-egress-smoke.sh

ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=https://ai-api.jdcloud.com/anthropic \
VALIDATION_MODE=egress \
DURATION_SECONDS=21600 \
INTERVAL_SECONDS=300 \
FAIL_FAST=true \
deploy/k8s/k3s-long-run.sh
```

Production remains **No-Go** if any generation is `failed`, contains a NACK,
does not reach `acked_acks == required_acks`, or if any sandbox can reach an
upstream directly without the shared Envoy.

## Rollback Boundary

Rollback is release-based, not an in-place state rewrite. Keep the previous
image/manifests available during the observation window. Do not mutate a
`failed` or `superseded` generation back to `published`/`applied`; create a new
generation or roll back the application release. The compatibility gateway and
filesystem xDS code remain temporarily in the repository for this release
window, but they are not part of the production overlay.
