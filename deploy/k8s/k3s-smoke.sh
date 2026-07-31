#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K8S_DIR="$ROOT/deploy/k8s"
BASE="$K8S_DIR/base"

KUBECTL="${KUBECTL:-kubectl}"
K3D="${K3D:-k3d}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
SANDBOX_NS="${JOYSAFETER_K8S_NAMESPACE:-joysafeter-sandboxes}"
K3D_CLUSTER_NAME="${K3D_CLUSTER_NAME:-joysafeter}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d%H%M%S)}"
MIGRATION_JOB="${MIGRATION_JOB:-joysafeter-db-init-${RUN_ID}}"

CORE_IMAGES=(
  "joysafeter-backend:latest"
  "joysafeter-frontend:latest"
  "joysafeter-orchestrator-rs:latest"
  "joysafeter-skillspector:latest"
)

RUNTIME_IMAGES=(
  "joysafeter-claudecode:latest"
  "joysafeter-codex:latest"
  "joysafeter-native:latest"
)

log() { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok() { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required" >&2
    exit 1
  fi
}

ensure_k3d_cluster() {
  if ! command -v "$K3D" >/dev/null 2>&1; then
    warn "k3d not found. Assuming kubectl already points at a reachable k3s cluster."
    return
  fi

  if "$K3D" cluster list -o json 2>/dev/null | grep -q "\"name\":\"${K3D_CLUSTER_NAME}\""; then
    log "Using existing k3d cluster: $K3D_CLUSTER_NAME"
    "$K3D" kubeconfig merge "$K3D_CLUSTER_NAME" --kubeconfig-switch-context >/dev/null
    return
  fi

  log "Creating local k3s cluster with k3d: $K3D_CLUSTER_NAME"
  "$K3D" cluster create --config "$K8S_DIR/k3d-cluster.yaml"
}

import_k3d_images() {
  if ! command -v "$K3D" >/dev/null 2>&1; then
    warn "k3d not found; skipping local Docker image import. Make sure the k3s cluster can pull configured images."
    return
  fi
  if ! "$K3D" cluster list -o json 2>/dev/null | grep -q "\"name\":\"${K3D_CLUSTER_NAME}\""; then
    warn "k3d cluster '$K3D_CLUSTER_NAME' not found; skipping image import"
    return
  fi

  for image in "${CORE_IMAGES[@]}" "${RUNTIME_IMAGES[@]}"; do
    if docker image inspect "$image" >/dev/null 2>&1; then
      log "Importing image into k3s: $image"
      "$K3D" image import "$image" -c "$K3D_CLUSTER_NAME"
    else
      warn "Docker image not found locally: $image"
    fi
  done
}

wait_rollout() {
  local deployment="$1"
  "$KUBECTL" -n "$CONTROL_NS" rollout status "deployment/$deployment" --timeout=300s
}

main() {
  require_cmd "$KUBECTL"

  ensure_k3d_cluster
  log "Current Kubernetes context: $("$KUBECTL" config current-context)"
  import_k3d_images

  log "Applying namespaces, config, and RBAC"
  "$KUBECTL" apply -f "$BASE/00-namespaces.yaml"
  "$KUBECTL" apply -f "$BASE/01-config.yaml"
  "$KUBECTL" apply -f "$BASE/02-rbac.yaml"

  log "Applying PostgreSQL, Redis, and SkillSpector"
  "$KUBECTL" apply -f "$BASE/10-infra.yaml"
  "$KUBECTL" apply -f "$BASE/20-skillspector.yaml"
  wait_rollout postgres
  wait_rollout redis
  wait_rollout skillspector

  log "Running database migrations"
  local migration_manifest="/tmp/${MIGRATION_JOB}.yaml"
  awk -v job="$MIGRATION_JOB" '
    !renamed && $0 == "  name: joysafeter-db-init" {
      print "  name: " job
      renamed = 1
      next
    }
    { print }
  ' "$BASE/30-db-init.yaml" >"$migration_manifest"
  "$KUBECTL" apply -f "$migration_manifest"
  if ! "$KUBECTL" -n "$CONTROL_NS" wait --for=condition=complete "job/${MIGRATION_JOB}" --timeout=300s; then
    "$KUBECTL" -n "$CONTROL_NS" logs "job/${MIGRATION_JOB}" --all-containers=true || true
    exit 1
  fi

  log "Applying API, worker, orchestrator, frontend, and sandbox policy"
  "$KUBECTL" apply -f "$BASE/40-app.yaml"
  "$KUBECTL" apply -f "$BASE/50-sandbox-policy.yaml"
  wait_rollout joysafeter-egress-gateway
  wait_rollout joysafeter-orchestrator
  wait_rollout worker
  wait_rollout api
  wait_rollout frontend

  log "Checking orchestrator sandbox RBAC (permission check only; no pods are deleted)"
  "$KUBECTL" auth can-i create pods -n "$SANDBOX_NS" \
    --as="system:serviceaccount:${CONTROL_NS}:joysafeter-orchestrator"
  "$KUBECTL" auth can-i delete pods -n "$SANDBOX_NS" \
    --as="system:serviceaccount:${CONTROL_NS}:joysafeter-orchestrator"
  "$KUBECTL" auth can-i create networkpolicies.networking.k8s.io -n "$SANDBOX_NS" \
    --as="system:serviceaccount:${CONTROL_NS}:joysafeter-orchestrator"
  "$KUBECTL" auth can-i patch networkpolicies.networking.k8s.io -n "$SANDBOX_NS" \
    --as="system:serviceaccount:${CONTROL_NS}:joysafeter-orchestrator"

  ok "k3s smoke stack is ready"
  echo ""
  echo "Access:"
  echo "  API:      http://localhost:8000/health"
  echo "  Frontend: http://localhost:3000"
  echo ""
  echo "If direct ports are unavailable, use:"
  echo "  $KUBECTL -n $CONTROL_NS port-forward svc/api 8000:8000"
  echo "  $KUBECTL -n $CONTROL_NS port-forward svc/frontend 3000:3000"
  echo ""
  echo "Watch dynamic sandbox pods:"
  echo "  $KUBECTL -n $SANDBOX_NS get pods -l app.kubernetes.io/name=joysafeter-sandbox -w"
}

main "$@"
