# Production k3s Overlay Contract

This directory documents the production overlay contract. Do not apply the base
manifests directly to production without replacing local-only dependencies and
Secrets.

Required production changes:

- Replace local `emptyDir` PostgreSQL/Redis with managed or HA services.
- Replace all `:latest` images with immutable tags or digests from a private
  registry.
- Provide `JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN` from a Kubernetes Secret
  manager, external-secrets operator, SealedSecret, or equivalent platform
  secret source. Do not use the local-dev token in `base/01-config.yaml`.
- Set `JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=true` only after the gateway
  Deployment is running, NetworkPolicy enforcement works in the cluster CNI,
  and long-run egress validation passes.
- Keep real provider/model credentials in JoySafeter managed Secrets/Vault.
  They must not appear in Kubernetes Secret manifests, Pod specs, ConfigMaps, or
  gateway policy files.

Minimum production patch shape:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: joysafeter-config
  namespace: joysafeter-control
data:
  JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED: "true"
  JOYSAFETER_EGRESS_GATEWAY_URL: http://joysafeter-egress-gateway.joysafeter-control.svc.cluster.local:8088
  JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS: api.anthropic.com,api.openai.com,generativelanguage.googleapis.com,ai-api.jdcloud.com,*.jdcloud.com
  POSTGRES_HOST: <managed-postgres-host>
  REDIS_URL: <managed-redis-url>
---
apiVersion: v1
kind: Secret
metadata:
  name: joysafeter-secret
  namespace: joysafeter-control
type: Opaque
stringData:
  JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN: <strong-random-control-token>
```

Validation gate before declaring production-ready:

```bash
ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=https://ai-api.jdcloud.com/anthropic \
VALIDATION_MODE=egress \
DURATION_SECONDS=21600 \
INTERVAL_SECONDS=300 \
FAIL_FAST=true \
deploy/k8s/k3s-long-run.sh
```

The validation scripts preserve evidence and intentionally do not delete runtime
objects or database rows. Run platform-owned cleanup separately only after the
team approves the lifecycle policy for deleting per-sandbox NetworkPolicies and
gateway policies.
