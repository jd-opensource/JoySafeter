#!/usr/bin/env bash
set -euo pipefail

KUBECTL="${KUBECTL:-kubectl}"

runtime_guard_fail() {
  printf 'runtime architecture guard failed: %s\n' "$*" >&2
  exit 1
}

runtime_guard_log() {
  printf '\033[0;36m▶ runtime guard: %s\033[0m\n' "$*"
}

runtime_guard_require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    runtime_guard_fail "$1 is required"
  fi
}

runtime_guard_python_json() {
  runtime_guard_require_cmd python3
  python3 "$@"
}

runtime_guard_assert_rendered_manifests() {
  local root="$1"
  local base="$2"

  [[ -d "$root" ]] || runtime_guard_fail "repo root not found: $root"
  [[ -d "$base" ]] || runtime_guard_fail "k8s base directory not found: $base"

  runtime_guard_log "checking rendered manifests"
  runtime_guard_python_json - "$base" <<'PY'
import pathlib
import re
import sys

base = pathlib.Path(sys.argv[1])
required = [
    base / "01-config.yaml",
    base / "02-rbac.yaml",
    base / "26-egress-authz.yaml",
    base / "27-egress-envoy.yaml",
    base / "40-app.yaml",
]
for path in required:
    if not path.exists():
        raise SystemExit(f"required manifest missing: {path}")

rbac = (base / "02-rbac.yaml").read_text()
app = (base / "40-app.yaml").read_text()
config = (base / "01-config.yaml").read_text()
authz = (base / "26-egress-authz.yaml").read_text()
envoy = (base / "27-egress-envoy.yaml").read_text()

if "name: joysafeter-orchestrator" not in rbac or "resources: [\"pods\"]" not in rbac:
    raise SystemExit("orchestrator sandbox pod RBAC is missing")
if "resources: [\"pods/exec\"]" not in rbac or "verbs: [\"create\"]" not in rbac:
    raise SystemExit("orchestrator pods/exec create RBAC is missing")
if "resources: [\"pods/log\"]" not in rbac or "verbs: [\"get\"]" not in rbac:
    raise SystemExit("orchestrator bounded Pod log read RBAC is missing")
if "resources: [\"events\"]" not in rbac:
    raise SystemExit("orchestrator Pod event observability RBAC is missing")
if not re.search(r'resources:\s*\["events"\][\s\S]*?verbs:\s*\[[^\]]*"list"', rbac):
    raise SystemExit("orchestrator Pod event list RBAC is missing")
if "resources: [\"networkpolicies\"]" not in rbac:
    raise SystemExit("orchestrator NetworkPolicy RBAC is missing")
if not re.search(r'resources:\s*\["networkpolicies"\][\s\S]*?verbs:\s*\[[^\]]*"delete"', rbac):
    raise SystemExit("orchestrator NetworkPolicy delete RBAC is missing")
if "serviceAccountName: joysafeter-orchestrator" not in app:
    raise SystemExit("orchestrator Deployment must run as joysafeter-orchestrator ServiceAccount")
if "enableServiceLinks: false" not in app:
    raise SystemExit("orchestrator must disable Kubernetes service-link env collisions")
if 'joysafeter.io/control-plane-active: "true"' not in app:
    raise SystemExit("orchestrator Service must select only the active Pod label")
if 'joysafeter.io/control-plane-active: "true"' not in authz:
    raise SystemExit("ext_authz Service must select only the active Pod label")
if 'joysafeter.io/control-plane-active: "false"' not in app:
    raise SystemExit("orchestrator Pod template must start with the active label cleared")
if "fieldPath: metadata.namespace" not in app or "name: JOYSAFETER_POD_NAMESPACE" not in app:
    raise SystemExit("orchestrator Pod namespace downward API env is missing")
if "containerPort: 18000" not in app or "name: xds" not in app:
    raise SystemExit("orchestrator dedicated Rust xDS port is missing")
if "secretName: joysafeter-rust-xds-server-tls" not in app:
    raise SystemExit("orchestrator dedicated Rust xDS TLS Secret mount is missing")
if "kind: DaemonSet" not in envoy or "name: joysafeter-egress-envoy" not in envoy:
    raise SystemExit("egress Envoy must run as a node-local DaemonSet")
if "internalTrafficPolicy: Local" not in envoy:
    raise SystemExit("egress Envoy Service must route only to node-local endpoints")
if "host_id: __NODE_NAME__" not in envoy or "fieldPath: spec.nodeName" not in envoy:
    raise SystemExit("egress Envoy node metadata must bind host_id to spec.nodeName")
if "kind: HorizontalPodAutoscaler" in envoy:
    raise SystemExit("node-local Envoy DaemonSet must not have an HPA")
if "joysafeter-egress-controller.joysafeter-control.svc.cluster.local" in envoy:
    raise SystemExit("base Envoy bootstrap still targets the temporary Go xDS controller")
if "joysafeter-orchestrator.joysafeter-control.svc.cluster.local" not in envoy:
    raise SystemExit("base Envoy bootstrap does not target embedded Rust xDS")
for key in (
    "JOYSAFETER_CONTROL_PLANE_HA_ENABLED",
    "JOYSAFETER_CONTROL_PLANE_LOCK_KEY",
    "JOYSAFETER_CONTROL_PLANE_HEALTH_BIND",
    "JOYSAFETER_EGRESS_XDS_MTLS",
    "JOYSAFETER_EGRESS_XDS_CERT_FILE",
    "JOYSAFETER_EGRESS_XDS_CLIENT_CA_FILE",
    "JOYSAFETER_EGRESS_XDS_CLIENT_DNS_SAN",
    "JOYSAFETER_EGRESS_XDS_BIND",
    "JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE",
    "JOYSAFETER_MAX_CONCURRENT_TASKS",
    "JOYSAFETER_MAX_SCHEDULING_TASKS",
    "JOYSAFETER_SCHEDULER_BATCH_SIZE",
    "JOYSAFETER_SANDBOX_CPU",
    "JOYSAFETER_SANDBOX_MEMORY_MB",
    "JOYSAFETER_SANDBOX_DISK_MB",
):
    if key not in config:
        raise SystemExit(f"sandbox resource configuration is missing: {key}")
if 'JOYSAFETER_CONTROL_PLANE_HA_ENABLED: "true"' not in config:
    raise SystemExit("orchestrator single-active control plane must be enabled")
if 'JOYSAFETER_EGRESS_XDS_BIND: 0.0.0.0:18000' not in config:
    raise SystemExit("embedded Rust xDS listener must be enabled by default")
if 'JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE: "true"' not in config:
    raise SystemExit("Rust xDS durable reconciliation must be enabled by default")
if not re.search(r'readinessProbe:[\s\S]*?path:\s*/healthz[\s\S]*?port:\s*health', app):
    raise SystemExit("orchestrator Deployment readiness must include cold standbys")
if not re.search(r'path:\s*/healthz[\s\S]*?port:\s*health', app):
    raise SystemExit("orchestrator liveness must use the process /healthz endpoint")
if re.search(r'(?m)^\s*(command|args):\s*\[?[^\n]*kubectl', app):
    raise SystemExit("orchestrator manifest still invokes kubectl")
if "kubectl.kubernetes.io/last-applied-configuration" in app:
    raise SystemExit("static orchestrator manifest contains kubectl last-applied annotation")
PY
}

runtime_guard_assert_live_control_plane() {
  local control_ns="$1"
  local sandbox_ns="$2"

  runtime_guard_require_cmd "$KUBECTL"
  runtime_guard_log "checking live namespaces and deployments"
  "$KUBECTL" get namespace "$control_ns" >/dev/null \
    || runtime_guard_fail "control namespace not found: $control_ns"
  "$KUBECTL" get namespace "$sandbox_ns" >/dev/null \
    || runtime_guard_fail "sandbox namespace not found: $sandbox_ns"
  "$KUBECTL" -n "$control_ns" get serviceaccount joysafeter-orchestrator >/dev/null \
    || runtime_guard_fail "orchestrator ServiceAccount missing in $control_ns"
  "$KUBECTL" -n "$control_ns" get deploy joysafeter-orchestrator >/dev/null \
    || runtime_guard_fail "orchestrator Deployment missing in $control_ns"
  "$KUBECTL" auth can-i patch pods -n "$control_ns" \
    --as="system:serviceaccount:${control_ns}:joysafeter-orchestrator" >/dev/null \
    || runtime_guard_fail "orchestrator ServiceAccount cannot patch its active Pod label"
}

runtime_guard_assert_orchestrator_image_api_only() {
  local control_ns="$1"

  runtime_guard_require_cmd "$KUBECTL"
  runtime_guard_require_cmd python3
  runtime_guard_log "checking orchestrator image/runtime has no kubectl dependency"

  local deploy_json
  deploy_json="$($KUBECTL -n "$control_ns" get deploy joysafeter-orchestrator -o json)" \
    || runtime_guard_fail "cannot read orchestrator Deployment"

  DEPLOY_JSON="$deploy_json" python3 - <<'PY'
import json
import os
import sys

deploy = json.loads(os.environ["DEPLOY_JSON"])
template = deploy.get("spec", {}).get("template", {})
spec = template.get("spec", {})
if spec.get("serviceAccountName") != "joysafeter-orchestrator":
    raise SystemExit("orchestrator Deployment is not using joysafeter-orchestrator ServiceAccount")
containers = spec.get("containers") or []
if not containers:
    raise SystemExit("orchestrator Deployment has no containers")
for container in containers:
    for field in ("command", "args"):
        values = container.get(field) or []
        if any("kubectl" in str(value) for value in values):
            raise SystemExit(f"orchestrator container {container.get('name')} {field} invokes kubectl")
PY

  local pod
  pod="$($KUBECTL -n "$control_ns" get pod -l app.kubernetes.io/name=joysafeter-orchestrator -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -z "$pod" ]]; then
    runtime_guard_fail "no live orchestrator Pod found in $control_ns"
  fi

  if "$KUBECTL" -n "$control_ns" exec "$pod" -- sh -c 'command -v kubectl >/dev/null 2>&1' >/dev/null 2>&1; then
    runtime_guard_fail "orchestrator image contains kubectl; runtime must use Kubernetes API client only"
  fi
}

runtime_guard_assert_orchestrator_sandbox_rbac() {
  local control_ns="$1"
  local sandbox_ns="$2"
  local as_user="system:serviceaccount:${control_ns}:joysafeter-orchestrator"

  runtime_guard_require_cmd "$KUBECTL"
  runtime_guard_log "checking orchestrator sandbox RBAC"

  local checks=(
    "create pods"
    "get pods"
    "list pods"
    "delete pods"
    "create pods/exec"
    "get pods/log"
    "list events"
    "create networkpolicies.networking.k8s.io"
    "get networkpolicies.networking.k8s.io"
    "list networkpolicies.networking.k8s.io"
    "patch networkpolicies.networking.k8s.io"
    "delete networkpolicies.networking.k8s.io"
  )

  local check verb resource
  for check in "${checks[@]}"; do
    verb="${check%% *}"
    resource="${check#* }"
    "$KUBECTL" auth can-i "$verb" "$resource" -n "$sandbox_ns" --as="$as_user" >/dev/null \
      || runtime_guard_fail "$as_user cannot $verb $resource in $sandbox_ns"
  done
}

runtime_guard_assert_sandbox_pods_api_created() {
  local sandbox_ns="$1"
  local pod_name="${2:-}"

  runtime_guard_require_cmd "$KUBECTL"
  runtime_guard_require_cmd python3
  runtime_guard_log "checking sandbox Pods are API-created and secret-free"

  local selector_args=()
  if [[ -n "$pod_name" ]]; then
    selector_args=("pod" "$pod_name")
  else
    selector_args=("pods" "-l" "app.kubernetes.io/name=joysafeter-sandbox")
  fi

  local pod_json
  pod_json="$($KUBECTL -n "$sandbox_ns" get "${selector_args[@]}" -o json 2>/dev/null || true)"
  if [[ -z "$pod_json" ]]; then
    if [[ -n "$pod_name" ]]; then
      runtime_guard_fail "sandbox Pod not found: $sandbox_ns/$pod_name"
    fi
    runtime_guard_log "no sandbox Pods currently present; skipping Pod annotation scan"
    return 0
  fi

  POD_JSON="$pod_json" python3 - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["POD_JSON"])
items = payload.get("items") if payload.get("kind") == "List" else [payload]
if not items:
    print("no sandbox Pods currently present; skipping Pod annotation scan")
    raise SystemExit(0)
for pod in items:
    meta = pod.get("metadata") or {}
    name = meta.get("name", "<unknown>")
    annotations = meta.get("annotations") or {}
    if "kubectl.kubernetes.io/last-applied-configuration" in annotations:
        raise SystemExit(f"sandbox Pod {name} contains kubectl last-applied annotation")
    labels = meta.get("labels") or {}
    if labels.get("app.kubernetes.io/name") != "joysafeter-sandbox":
        raise SystemExit(f"sandbox Pod {name} is missing joysafeter-sandbox label")
    for container in (pod.get("spec") or {}).get("containers") or []:
        env = {entry.get("name", ""): str(entry.get("value", "")) for entry in (container.get("env") or [])}
        runner_token = env.get("JOYSAFETER_RUNNER_TOKEN", "")
        placeholders = {
            "ANTHROPIC_API_KEY": {"joysafeter-placeholder-anthropic-api-key"},
            "OPENAI_API_KEY": {"joysafeter-placeholder-openai-api-key"},
        }
        sandbox_token_keys = {
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "AZURE_OPENAI_API_KEY",
        }
        for key in sorted(sandbox_token_keys):
            value = env.get(key)
            if not value:
                continue
            if value in placeholders.get(key, set()):
                continue
            if runner_token and value == runner_token:
                continue
            raise SystemExit(
                f"sandbox Pod {name} has a provider credential-shaped env {key} "
                "whose value is neither an approved placeholder nor the sandbox runner token"
            )
PY
}
