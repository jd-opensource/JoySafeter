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
