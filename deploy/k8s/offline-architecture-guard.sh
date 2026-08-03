#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

fail() {
  printf 'offline architecture guard failed: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '\033[0;36m▶ offline guard: %s\033[0m\n' "$*"
}

require_file() {
  [[ -f "$1" ]] || fail "required file missing: $1"
}

require_executable() {
  [[ -x "$1" ]] || fail "required executable missing: $1"
}

rg_match() {
  local pattern="$1"
  shift
  rg -n --hidden -g '!target' -g '!node_modules' -g '!frontend/.next' "$pattern" "$@"
}

rg_no_match() {
  local pattern="$1"
  shift
  local output
  if output="$(rg_match "$pattern" "$@")"; then
    printf '%s\n' "$output" >&2
    fail "forbidden pattern matched: $pattern"
  fi
}

log "checking guard scripts and smoke hooks"
require_executable deploy/k8s/runtime-architecture-guard.sh
require_executable deploy/k8s/offline-architecture-guard.sh
for script in deploy/k8s/k3s-smoke.sh deploy/k8s/k3s-task-smoke.sh deploy/k8s/k3s-egress-smoke.sh; do
  require_file "$script"
  grep -q 'runtime-architecture-guard.sh' "$script" || fail "$script does not source runtime guard"
  grep -q 'runtime_guard_assert_live_control_plane' "$script" || fail "$script does not check live control plane"
  grep -q 'runtime_guard_assert_orchestrator_sandbox_rbac' "$script" || fail "$script does not check sandbox RBAC"
done

grep -q 'deploy/k8s/offline-architecture-guard.sh' .github/workflows/ci.yml \
  || fail "CI does not run offline architecture guard"

log "checking old Rust HTTP gateway path stays deleted"
for deleted in \
  backend/app/joysafeter_orchestrator_rs/src/bin/egress_gateway.rs \
  backend/app/joysafeter_orchestrator_rs/src/egress/gateway.rs \
  backend/app/joysafeter_orchestrator_rs/src/egress/k8s_manager.rs \
  deploy/k8s/local-smoke.sh \
  deploy/mock-upstream/main.go; do
  [[ ! -e "$deleted" ]] || fail "old gateway artifact still exists: $deleted"
done
rg_no_match 'egress_gateway|mod gateway|mod k8s_manager|EgressGateway|K8sEgressManager|rust-egress-authz' \
  backend/app/joysafeter_orchestrator_rs/src deploy/k8s/base deploy/k8s/overlays .github/workflows/ci.yml

log "checking orchestrator runtime is Kubernetes API-only"
rg_no_match 'Command::new\("kubectl"|tokio::process::Command|std::process::Command' \
  backend/app/joysafeter_orchestrator_rs/src
rg_match 'kube::Api|Api<Pod>|Api::<Pod>|Api<NetworkPolicy>|Api::<NetworkPolicy>' \
  backend/app/joysafeter_orchestrator_rs/src/sandbox/k8s.rs \
  backend/app/joysafeter_orchestrator_rs/src/egress/enforcer.rs >/dev/null \
  || fail "orchestrator Kubernetes code does not use kube::Api for Pod/NetworkPolicy operations"

log "checking RBAC supports owned NetworkPolicy lifecycle"
python3 - <<'PY'
import pathlib
import re
import sys

rbac = pathlib.Path("deploy/k8s/base/02-rbac.yaml").read_text()
block_match = re.search(r'apiGroups:\s*\["networking\.k8s\.io"\][\s\S]*?resources:\s*\["networkpolicies"\][\s\S]*?verbs:\s*\[([^\]]+)\]', rbac)
if not block_match:
    raise SystemExit("NetworkPolicy RBAC rule missing")
verbs = {part.strip().strip('"') for part in block_match.group(1).split(',')}
required = {"get", "list", "watch", "create", "update", "patch", "delete"}
missing = sorted(required - verbs)
if missing:
    raise SystemExit(f"NetworkPolicy RBAC missing verbs: {', '.join(missing)}")
app = pathlib.Path("deploy/k8s/base/40-app.yaml").read_text()
if "serviceAccountName: joysafeter-orchestrator" not in app:
    raise SystemExit("orchestrator Deployment must use joysafeter-orchestrator ServiceAccount")
if "name: joysafeter-orchestrator-pod-labeler" not in rbac:
    raise SystemExit("orchestrator active Pod label RBAC is missing")
if not re.search(r'resources:\s*\["pods"\][\s\S]*?verbs:\s*\["get", "patch"\]', rbac):
    raise SystemExit("orchestrator active Pod label patch permission is missing")
base_kustomization = pathlib.Path("deploy/k8s/base/kustomization.yaml").read_text()
if "25-egress-controller.yaml" in base_kustomization:
    raise SystemExit("temporary Go xDS controller must not be deployed by the base")
if not pathlib.Path("deploy/k8s/overlays/go-xds-rollback/kustomization.yaml").exists():
    raise SystemExit("explicit Go xDS emergency rollback overlay is missing")
PY

log "checking Rust xDS smoke hooks"
grep -q 'joysafeter_rust_xds_connected_nodes' deploy/k8s/k3s-egress-smoke.sh \
  || fail "k3s egress smoke does not verify Rust xDS node connections"
grep -q 'port-forward svc/joysafeter-orchestrator' deploy/k8s/k3s-egress-smoke.sh \
  || fail "k3s egress smoke does not inspect the Rust xDS status endpoint"
grep -q 'rollout restart daemonset/joysafeter-egress-envoy' deploy/k8s/k3s-egress-smoke.sh \
  || fail "node-local Envoy DaemonSet restart is missing"

log "checking shell syntax"
bash -n deploy/k8s/runtime-architecture-guard.sh
bash -n deploy/k8s/k3s-smoke.sh
bash -n deploy/k8s/k3s-task-smoke.sh
bash -n deploy/k8s/k3s-egress-smoke.sh
bash -n deploy/k8s/cutover-rust-xds.sh
bash -n deploy/k8s/go-xds-rollback.sh

log "offline architecture guard passed"
