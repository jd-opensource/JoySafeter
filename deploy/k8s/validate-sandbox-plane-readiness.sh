#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OVERLAY="${OVERLAY:-deploy/k8s/overlays/sandbox-plane}"
CONTROL_NS="${CONTROL_NS:-joysafeter-control}"
SANDBOX_NS="${SANDBOX_NS:-joysafeter-sandboxes}"
EGRESS_NS="${EGRESS_NS:-joysafeter-egress}"
SMOKE_IMAGE="${SMOKE_IMAGE:-joysafeter-backend:latest}"
TMP_PARENT="${TMPDIR:-/tmp}"
TMP_DIR="${TMP_DIR:-$TMP_PARENT/joysafeter-sandbox-plane-validation}"
RENDERED="$TMP_DIR/rendered.yaml"

cd "$ROOT"
mkdir -p "$TMP_DIR"

log() {
  printf '\033[0;36m▶ %s\033[0m\n' "$*" >&2
}

fail() {
  printf '\033[0;31mNO-GO: %s\033[0m\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

require_cmd kubectl
require_cmd rg
require_cmd python3

log "Rendering $OVERLAY"
kubectl kustomize "$OVERLAY" >"$RENDERED"

log "Checking sandbox-plane manifest"
if rg -n 'CHANGE_ME_|local-dev-secret|local-dev-jwt|MDEyMzQ1|postgres://postgres:postgres|postgresql://postgres:postgres' "$RENDERED"; then
  fail "rendered manifest contains placeholders or local-development credentials"
fi
if [[ "${ALLOW_LATEST_IMAGES:-false}" != "true" ]] && rg -n 'image: .*:latest($|@| )|JOYSAFETER_IMAGE_.*:.*latest|JOYSAFETER_SANDBOX_IMAGE: .*latest' "$RENDERED"; then
  fail "rendered manifest contains :latest images"
fi
rg 'JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED: "true"' "$RENDERED" >/dev/null \
  || fail "durable egress policy authority is not enabled"
rg 'JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED: "true"' "$RENDERED" >/dev/null \
  || fail "K8s Envoy egress management is not enabled"

python3 - "$RENDERED" <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import sys

rendered = Path(sys.argv[1]).read_text()
forbidden = {
    ("Service", "joysafeter-control", "api"),
    ("Deployment", "joysafeter-control", "api"),
    ("Service", "joysafeter-control", "worker"),
    ("Deployment", "joysafeter-control", "worker"),
    ("Service", "joysafeter-control", "frontend"),
    ("Deployment", "joysafeter-control", "frontend"),
    ("Service", "joysafeter-control", "skillspector"),
    ("Deployment", "joysafeter-control", "skillspector"),
    ("Service", "joysafeter-control", "postgres"),
    ("Deployment", "joysafeter-control", "postgres"),
    ("Service", "joysafeter-control", "redis"),
    ("Deployment", "joysafeter-control", "redis"),
    ("Job", "joysafeter-control", "joysafeter-db-init"),
}
required = {
    ("Service", "joysafeter-control", "joysafeter-orchestrator"),
    ("Deployment", "joysafeter-control", "joysafeter-orchestrator"),
    ("Service", "joysafeter-control", "joysafeter-egress-controller"),
    ("Deployment", "joysafeter-control", "joysafeter-egress-controller"),
    ("Service", "joysafeter-egress", "joysafeter-egress-envoy"),
    ("Deployment", "joysafeter-egress", "joysafeter-egress-envoy"),
    ("NetworkPolicy", "joysafeter-sandboxes", "default-deny"),
    ("NetworkPolicy", "joysafeter-sandboxes", "allow-runner-control-plane"),
}
forbidden_config_keys = {
    "FRONTEND_URL",
    "BACKEND_URL",
    "CORS_ORIGINS",
    "BACKEND_CORS_ORIGINS",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_APP_URL",
    "NEXT_PUBLIC_CSP_NECESSARY_DOMAIN",
    "NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED",
    "NEXT_PUBLIC_MAX_UPLOAD_FILE_BYTES",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_DB",
    "DATABASE_URL",
    "REDIS_URL",
    "STORAGE_LOCAL_PATH",
    "SKILL_SECURITY_SCANNER_URL",
}
found: set[tuple[str, str, str]] = set()
bad_config_keys: list[str] = []
for doc in re.split(r"(?m)^---\s*$", rendered):
    kind_match = re.search(r"(?m)^kind:\s*(\S+)\s*$", doc)
    name_match = re.search(r"(?m)^metadata:\s*\n(?:  .*\n)*?  name:\s*(\S+)\s*$", doc)
    ns_match = re.search(r"(?m)^metadata:\s*\n(?:  .*\n)*?  namespace:\s*(\S+)\s*$", doc)
    if not kind_match or not name_match:
        continue
    kind = kind_match.group(1)
    name = name_match.group(1)
    namespace = ns_match.group(1) if ns_match else ""
    found.add((kind, namespace, name))
    if kind == "ConfigMap" and namespace == "joysafeter-control" and name == "joysafeter-config":
        for key in sorted(forbidden_config_keys):
            if re.search(rf"(?m)^  {re.escape(key)}:", doc):
                bad_config_keys.append(key)

bad = sorted(found & forbidden)
missing = sorted(required - found)
if bad_config_keys:
    print("business/app config keys rendered in sandbox-plane ConfigMap:", file=sys.stderr)
    for key in bad_config_keys:
        print(f"  - {key}", file=sys.stderr)
    raise SystemExit(1)
if bad:
    print("forbidden app/data-plane resources rendered:", file=sys.stderr)
    for item in bad:
        print(f"  - {item[0]}/{item[2]} in {item[1]}", file=sys.stderr)
    raise SystemExit(1)
if missing:
    print("required sandbox-plane resources missing:", file=sys.stderr)
    for item in missing:
        print(f"  - {item[0]}/{item[2]} in {item[1]}", file=sys.stderr)
    raise SystemExit(1)
PY

if [[ -x deploy/k8s/offline-architecture-guard.sh ]]; then
  log "Running offline architecture guard"
  deploy/k8s/offline-architecture-guard.sh
else
  log "Skipping optional offline architecture guard"
fi

if [[ "${SKIP_CLUSTER_CHECKS:-false}" == "true" ]]; then
  log "Skipping live cluster checks"
  printf 'Rendered manifest: %s\n' "$RENDERED"
  exit 0
fi

log "Checking current cluster context"
kubectl config current-context
kubectl get nodes -o wide

log "Checking required namespaces"
kubectl get namespace "$CONTROL_NS" "$EGRESS_NS" "$SANDBOX_NS" >/dev/null

log "Running runtime architecture guards"
if [[ -r deploy/k8s/runtime-architecture-guard.sh ]]; then
  bash -lc "set -euo pipefail; source deploy/k8s/runtime-architecture-guard.sh; runtime_guard_assert_live_control_plane '$CONTROL_NS' '$SANDBOX_NS'; runtime_guard_assert_orchestrator_sandbox_rbac '$CONTROL_NS' '$SANDBOX_NS'; runtime_guard_assert_orchestrator_image_api_only '$CONTROL_NS'"
else
  kubectl auth can-i create pods -n "$SANDBOX_NS" --as="system:serviceaccount:${CONTROL_NS}:joysafeter-orchestrator" >/dev/null \
    || fail "orchestrator service account cannot create sandbox pods"
  kubectl auth can-i create networkpolicies.networking.k8s.io -n "$SANDBOX_NS" --as="system:serviceaccount:${CONTROL_NS}:joysafeter-orchestrator" >/dev/null \
    || fail "orchestrator service account cannot create sandbox NetworkPolicies"
fi

log "Verifying NetworkPolicy enforcement with deny-all egress smoke"
kubectl delete ns joysafeter-np-smoke --ignore-not-found --wait=true >/dev/null 2>&1 || true
cat >"$TMP_DIR/np-smoke.yaml" <<YAML
apiVersion: v1
kind: Namespace
metadata:
  name: joysafeter-np-smoke
---
apiVersion: v1
kind: Pod
metadata:
  name: curl
  namespace: joysafeter-np-smoke
spec:
  restartPolicy: Never
  containers:
    - name: curl
      image: ${SMOKE_IMAGE}
      imagePullPolicy: IfNotPresent
      command: ["sleep", "3600"]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-egress
  namespace: joysafeter-np-smoke
spec:
  podSelector: {}
  policyTypes: ["Egress"]
YAML
kubectl apply -f "$TMP_DIR/np-smoke.yaml" >/dev/null
kubectl -n joysafeter-np-smoke wait pod/curl --for=condition=Ready --timeout=180s >/dev/null
if kubectl -n joysafeter-np-smoke exec curl -- curl -fsS --connect-timeout 3 --max-time 5 https://1.1.1.1 >/tmp/joysafeter-np-smoke.out 2>/tmp/joysafeter-np-smoke.err; then
  cat /tmp/joysafeter-np-smoke.out /tmp/joysafeter-np-smoke.err >&2 || true
  kubectl delete ns joysafeter-np-smoke --ignore-not-found --wait=false >/dev/null 2>&1 || true
  fail "NetworkPolicy did not block direct egress"
fi
kubectl delete ns joysafeter-np-smoke --ignore-not-found --wait=false >/dev/null 2>&1 || true

log "Checking sandbox-plane rollouts"
kubectl -n "$CONTROL_NS" rollout status deploy/joysafeter-egress-controller --timeout=300s
kubectl -n "$EGRESS_NS" rollout status deploy/joysafeter-egress-envoy --timeout=300s
kubectl -n "$CONTROL_NS" rollout status deploy/joysafeter-orchestrator --timeout=300s

log "Sandbox-plane readiness validation passed"
printf 'Rendered manifest: %s\n' "$RENDERED"
