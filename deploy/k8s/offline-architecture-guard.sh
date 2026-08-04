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
  if command -v rg >/dev/null 2>&1; then
    rg -n --hidden -g '!target' -g '!node_modules' -g '!frontend/.next' "$pattern" "$@"
  else
    grep -EnR -I \
      --exclude-dir=target \
      --exclude-dir=node_modules \
      --exclude-dir=.next \
      -- "$pattern" "$@"
  fi
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
  deploy/k8s/base/25-egress-controller.yaml \
  deploy/k8s/go-xds-rollback.sh \
  deploy/k8s/overlays/go-xds-rollback \
  egress-controller \
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
    raise SystemExit("removed legacy xDS controller must not be deployed by the base")
PY

log "checking Rust xDS smoke hooks"
grep -q 'joysafeter_rust_xds_connected_nodes' deploy/k8s/k3s-egress-smoke.sh \
  || fail "k3s egress smoke does not verify Rust xDS node connections"
grep -q 'port-forward svc/joysafeter-orchestrator' deploy/k8s/k3s-egress-smoke.sh \
  || fail "k3s egress smoke does not inspect the Rust xDS status endpoint"
grep -q 'rollout restart daemonset/joysafeter-egress-envoy' deploy/k8s/k3s-egress-smoke.sh \
  || fail "node-local Envoy DaemonSet restart is missing"

log "checking Docker Compose defaults to embedded Rust ADS"
grep -q 'JOYSAFETER_EGRESS_XDS_HOST:.*orchestrator-rs' deploy/docker-compose.yml \
  || fail "Docker Envoy does not default to the orchestrator Rust ADS endpoint"
grep -q 'JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE:.*true' deploy/docker-compose.yml \
  || fail "Docker orchestrator does not enable the PostgreSQL-backed Rust reconciler"
rg_no_match 'go-xds-rollback|joysafeter-egress-controller|egress-controller/' \
  deploy/docker-compose.yml deploy/.env.example deploy/deploy.sh \
  deploy/egress-compose-smoke.sh .github/workflows
rg_no_match 'JOYSAFETER_EGRESS_CONTROLLER_' \
  backend/app/joysafeter_orchestrator_rs/src deploy/docker-compose.yml \
  deploy/.env.example deploy/egress-compose-smoke.sh deploy/k8s/base \
  deploy/k8s/overlays .github/workflows
grep -q 'joysafeter_egress_node_connections' deploy/egress-compose-smoke.sh \
  || fail "Docker egress smoke does not verify canonical Rust Envoy connections"
grep -q 'controller_instance=.*ORCHESTRATOR_INSTANCE' deploy/egress-compose-smoke.sh \
  || fail "Docker egress smoke does not bind canonical connections to the Rust orchestrator instance"
grep -q 'canonical node ACK rows' deploy/egress-compose-smoke.sh \
  || fail "Docker egress smoke does not verify canonical per-node ACK rows"
grep -q 'ISOLATED=true BRING_UP=true' deploy/egress-compose-smoke.sh \
  || fail "Docker egress smoke does not expose isolated random-resource mode"
grep -q 'A/B/C/D control-plane and data-plane proof passed' deploy/egress-compose-smoke.sh \
  || fail "Docker egress smoke does not require the complete four-source proof"
grep -q 'authorized probe returned.*expected 200' deploy/egress-compose-smoke.sh \
  || fail "Docker egress smoke does not fail closed on credential injection"
grep -q 'wrong-token probe returned.*expected 403' deploy/egress-compose-smoke.sh \
  || fail "Docker egress smoke does not fail closed on wrong-token authorization"
grep -q 'x-request-id.*not found in mock upstream log' deploy/egress-compose-smoke.sh \
  || fail "Docker egress smoke does not require request-log cross-correlation"
grep -q 'source_group_key: &desired.source_group_key' \
  backend/app/joysafeter_orchestrator_rs/src/xds_reconciler.rs \
  || fail "Rust xDS compiler input does not preserve the canonical source group for ext_authz"

log "checking production docs and deployment stay Rust-only"
rg_no_match 'Docker sandbox 面 =.*egress-controller|shared Envoy fleet、Go egress-controller' \
  deploy/README.md
rg_no_match 'rollout status deploy/joysafeter-egress-controller|包含 orchestrator、egress-controller|只有 orchestrator、egress-controller' \
  deploy/PRODUCTION_CHECKLIST.md
rg_no_match 'go-xds-rollback|Legacy Go xDS Rollback CI|working-directory: egress-controller' \
  .github/workflows deploy/README.md deploy/PRODUCTION_CHECKLIST.md \
  deploy/EGRESS_MIGRATION.md deploy/deploy.sh deploy/docker-compose.yml \
  deploy/k8s/README.md deploy/k8s/base deploy/k8s/overlays

log "checking shell syntax"
bash -n deploy/k8s/runtime-architecture-guard.sh
bash -n deploy/k8s/k3s-smoke.sh
bash -n deploy/k8s/k3s-task-smoke.sh
bash -n deploy/k8s/k3s-egress-smoke.sh
bash -n deploy/k8s/cutover-rust-xds.sh
bash -n deploy/egress-compose-smoke.sh

log "offline architecture guard passed"
