#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck source=runtime-architecture-guard.sh
source "$SCRIPT_DIR/runtime-architecture-guard.sh"

KUBECTL="${KUBECTL:-kubectl}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
EGRESS_NS="${JOYSAFETER_EGRESS_NAMESPACE:-joysafeter-egress}"
SANDBOX_NS="${JOYSAFETER_K8S_NAMESPACE:-joysafeter-sandboxes}"
API_URL="${API_URL:-}"
API_PORT_FORWARD_PORT="${API_PORT_FORWARD_PORT:-}"
ORCHESTRATOR_HEALTH_PORT_FORWARD_PORT="${ORCHESTRATOR_HEALTH_PORT_FORWARD_PORT:-}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d%H%M%S)}"
SMOKE_EMAIL="${SMOKE_EMAIL:-k3s-egress-${RUN_ID}@example.com}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:-K3sEgressSmokePass123!}"
SKIP_SIGNUP="${SKIP_SIGNUP:-false}"
SMOKE_SECRET_NAME="${SMOKE_SECRET_NAME:-k3s-egress-secret-${RUN_ID}}"
EXISTING_SECRET_NAME="${EXISTING_SECRET_NAME:-}"
SMOKE_ENV_NAME="${SMOKE_ENV_NAME:-k3s-egress-env-${RUN_ID}}"
SMOKE_AGENT_NAME="${SMOKE_AGENT_NAME:-k3s-egress-agent-${RUN_ID}}"
DEFAULT_SMOKE_MODEL="${DEFAULT_SMOKE_MODEL:-claude-sonnet-4-20250514}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-}"
SMOKE_MODEL="${SMOKE_MODEL:-$ANTHROPIC_MODEL}"
SMOKE_TIMEOUT_SEC="${SMOKE_TIMEOUT_SEC:-600}"
WAIT_SECONDS="${WAIT_SECONDS:-180}"
TASK_WAIT_SECONDS="${TASK_WAIT_SECONDS:-600}"
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"
PATCH_EGRESS_CONFIG="${PATCH_EGRESS_CONFIG:-true}"
RESTORE_EGRESS_CONFIG="${RESTORE_EGRESS_CONFIG:-true}"
BUILD_EGRESS_IMAGES="${BUILD_EGRESS_IMAGES:-false}"
K3D_CLUSTER_NAME="${K3D_CLUSTER_NAME:-joysafeter}"
RUN_SECRET_CONNECTIVITY_TEST="${RUN_SECRET_CONNECTIVITY_TEST:-true}"
EXPECTED_OUTPUT_FRAGMENT="${EXPECTED_OUTPUT_FRAGMENT:-K3S_EGRESS_OK}"
# Keep the default empty: this smoke validates egress, not provider-specific
# prompt behavior. JDCloud-compatible validation on 2026-08-03 showed minimal
# Messages requests succeed through Envoy, while Claude Code's default
# title/thinking/experimental-beta request shape needed compatibility env vars.
# Set this explicitly only when provider system-prompt behavior is under test.
SMOKE_SYSTEM_PROMPT="${SMOKE_SYSTEM_PROMPT:-}"
ALLOW_UPSTREAM_MODEL_ERROR="${ALLOW_UPSTREAM_MODEL_ERROR:-false}"
EGRESS_PREFLIGHT_ONLY="${EGRESS_PREFLIGHT_ONLY:-false}"
EGRESS_BYPASS_PROBE_ENABLED="${EGRESS_BYPASS_PROBE_ENABLED:-true}"
EGRESS_BYPASS_PROBE_CLEANUP="${EGRESS_BYPASS_PROBE_CLEANUP:-true}"
EGRESS_BYPASS_PROBE_IMAGE="${EGRESS_BYPASS_PROBE_IMAGE:-joysafeter-backend:latest}"

PORT_FORWARD_PID=""
XDS_STATUS_PORT_FORWARD_PID=""
ORIGINAL_EGRESS_CONFIG=""
BYPASS_PROBE_RESOURCES=()
BYPASS_PROBE_URL=""

log() { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok() { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }

cleanup_on_exit() {
  if [[ -n "$PORT_FORWARD_PID" ]]; then
    kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
    wait "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
    PORT_FORWARD_PID=""
  fi
  if [[ -n "$XDS_STATUS_PORT_FORWARD_PID" ]]; then
    kill "$XDS_STATUS_PORT_FORWARD_PID" >/dev/null 2>&1 || true
    wait "$XDS_STATUS_PORT_FORWARD_PID" >/dev/null 2>&1 || true
    XDS_STATUS_PORT_FORWARD_PID=""
  fi
  if [[ "$EGRESS_BYPASS_PROBE_CLEANUP" == "true" && "${#BYPASS_PROBE_RESOURCES[@]}" -gt 0 ]]; then
    "$KUBECTL" -n "$SANDBOX_NS" delete "${BYPASS_PROBE_RESOURCES[@]}" \
      --ignore-not-found=true --wait=true --timeout=30s >/dev/null 2>&1 || true
  fi
  if [[ "$RESTORE_EGRESS_CONFIG" == "true" && -n "$ORIGINAL_EGRESS_CONFIG" ]]; then
    "$KUBECTL" -n "$CONTROL_NS" patch configmap joysafeter-config \
      --type merge -p "$ORIGINAL_EGRESS_CONFIG" >/dev/null 2>&1 || true
    "$KUBECTL" -n "$CONTROL_NS" rollout restart deployment/joysafeter-orchestrator \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup_on_exit EXIT

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required" >&2
    exit 1
  fi
}

json_get() {
  local path="$1"
  local input
  input="$(cat)"
  JSON_INPUT="$input" python3 - "$path" <<'PY'
import json
import os
import sys

path = sys.argv[1].split(".")
try:
    cur = json.loads(os.environ["JSON_INPUT"])
except json.JSONDecodeError:
    sys.exit(1)

for part in path:
    if isinstance(cur, dict):
        cur = cur.get(part)
    else:
        cur = None
    if cur is None:
        sys.exit(1)

if isinstance(cur, (dict, list)):
    print(json.dumps(cur, separators=(",", ":")))
else:
    print(cur)
PY
}

json_body() {
  python3 - "$@" <<'PY'
import json
import sys

pairs = [arg.split("=", 1) for arg in sys.argv[1:]]
print(json.dumps({key: value for key, value in pairs}, separators=(",", ":")))
PY
}

base_host() {
  python3 - "$ANTHROPIC_BASE_URL" <<'PY'
import sys
from urllib.parse import urlparse

host = urlparse(sys.argv[1]).hostname
if not host:
    raise SystemExit("ANTHROPIC_BASE_URL must include a host")
print(host)
PY
}

probe_name_suffix() {
  python3 - "$1" <<'PY'
import sys

value = sys.argv[1].lower()
safe = "".join(ch if ch.isalnum() else "-" for ch in value).strip("-")
print(safe[:24].strip("-") or "probe")
PY
}

api_live() {
  [[ -n "$API_URL" ]] || return 1
  curl -fsS "${API_URL}/api/v1/health/live" >/dev/null 2>&1
}

start_api_port_forward() {
  local local_port log_path
  local_port="${API_PORT_FORWARD_PORT:-$((18000 + RANDOM % 1000))}"
  API_URL="http://127.0.0.1:${local_port}"
  log_path="/tmp/joysafeter-k3s-api-port-forward-${local_port}.log"

  log "Starting temporary port-forward svc/api ${local_port}:8000"
  "$KUBECTL" -n "$CONTROL_NS" port-forward svc/api "${local_port}:8000" >"$log_path" 2>&1 &
  PORT_FORWARD_PID="$!"

  for _ in $(seq 1 30); do
    if api_live; then
      return
    fi
    sleep 1
  done

  warn "port-forward log:"
  sed -n '1,80p' "$log_path" >&2 || true
  echo "API did not become reachable at ${API_URL}" >&2
  exit 1
}

ensure_api() {
  if [[ -z "$API_URL" ]]; then
    start_api_port_forward
    return
  fi

  if api_live; then
    return
  fi

  echo "API did not become reachable at ${API_URL}" >&2
  exit 1
}

post_json() {
  local path="$1"
  local body="$2"
  shift 2
  curl -sS -X POST "${API_URL}${path}" \
    -H "Content-Type: application/json" \
    "$@" \
    -d "$body"
}

assert_success() {
  local response="$1"
  local context="$2"
  if [[ "$(printf '%s' "$response" | json_get success 2>/dev/null || true)" != "True" && \
        "$(printf '%s' "$response" | json_get success 2>/dev/null || true)" != "true" ]]; then
    echo "${context} failed:" >&2
    printf '%s\n' "$response" >&2
    exit 1
  fi
}

wait_rollout() {
  local workload="$1"
  local namespace="${2:-$CONTROL_NS}"
  "$KUBECTL" -n "$namespace" rollout status "$workload" --timeout=300s
}

build_and_import_egress_images() {
  if [[ "$BUILD_EGRESS_IMAGES" != "true" ]]; then
    return
  fi
  require_cmd docker
  log "Building Rust orchestrator image"
  "$ROOT/deploy/deploy.sh" build --orchestrator-only
  if command -v k3d >/dev/null 2>&1 && \
     k3d cluster list -o json 2>/dev/null | grep -q "\"name\":\"${K3D_CLUSTER_NAME}\""; then
    log "Importing Rust orchestrator image into k3d cluster ${K3D_CLUSTER_NAME}"
    k3d image import joysafeter-orchestrator-rs:latest -c "$K3D_CLUSTER_NAME"
  else
    warn "No matching k3d cluster found; the Kubernetes cluster must pull the built images itself"
  fi
}

install_shared_egress_plane() {
  log "Installing ephemeral three-domain egress PKI"
  KUBECTL="$KUBECTL" \
    JOYSAFETER_CONTROL_NAMESPACE="$CONTROL_NS" \
    JOYSAFETER_EGRESS_NAMESPACE="$EGRESS_NS" \
    JOYSAFETER_K8S_NAMESPACE="$SANDBOX_NS" \
    "$SCRIPT_DIR/pki/bootstrap-egress-pki.sh"

  log "Applying TLS-enabled node-local Envoy control/data-plane manifests"
  "$KUBECTL" apply -f "$SCRIPT_DIR/base/26-egress-authz.yaml"
  "$KUBECTL" apply -f "$SCRIPT_DIR/base/27-egress-envoy.yaml"

  log "Restarting Rust xDS orchestrator and node-local Envoy"
  "$KUBECTL" -n "$CONTROL_NS" rollout restart deployment/joysafeter-orchestrator >/dev/null
  "$KUBECTL" -n "$EGRESS_NS" rollout restart daemonset/joysafeter-egress-envoy >/dev/null
  wait_rollout deployment/joysafeter-orchestrator "$CONTROL_NS"
  wait_rollout daemonset/joysafeter-egress-envoy "$EGRESS_NS"
}

patch_egress_config() {
  if [[ "$PATCH_EGRESS_CONFIG" != "true" ]]; then
    return
  fi

  local current_config host cm_patch
  current_config="$("$KUBECTL" -n "$CONTROL_NS" get configmap joysafeter-config -o json)"
  ORIGINAL_EGRESS_CONFIG="$(CONFIG_JSON="$current_config" python3 <<'PY'
import json
import os

data = json.loads(os.environ["CONFIG_JSON"]).get("data", {})
keys = [
    "JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED",
    "JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED",
    "JOYSAFETER_EGRESS_AUTHZ_MTLS",
    "JOYSAFETER_EGRESS_XDS_BIND",
    "JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE",
    "JOYSAFETER_EGRESS_ENVOY_CREDENTIAL_URL",
    "JOYSAFETER_EGRESS_ENVOY_FORWARD_PROXY_URL",
    "JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS",
]
restore = {key: data[key] if key in data else None for key in keys}
print(json.dumps({"data": restore}, separators=(",", ":")))
PY
)"

  log "Enabling durable authority and Envoy-only K8s egress for this validation"
  host="$(base_host)"
  cm_patch="$(python3 - "$host" <<'PY'
import json
import sys

host = sys.argv[1]
allowed = [
    "api.anthropic.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
    "ai-api.jdcloud.com",
    "*.jdcloud.com",
    host,
]
deduped = list(dict.fromkeys(item for item in allowed if item))
print(json.dumps({"data": {
    "JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED": "true",
    "JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED": "true",
    "JOYSAFETER_EGRESS_AUTHZ_MTLS": "true",
    "JOYSAFETER_EGRESS_XDS_BIND": "0.0.0.0:18000",
    "JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE": "true",
    "JOYSAFETER_EGRESS_ENVOY_CREDENTIAL_URL": "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8443",
    "JOYSAFETER_EGRESS_ENVOY_FORWARD_PROXY_URL": "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8080",
    "JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS": ",".join(deduped),
}}, separators=(",", ":")))
PY
)"
  "$KUBECTL" -n "$CONTROL_NS" patch configmap joysafeter-config --type merge -p "$cm_patch" >/dev/null
  "$KUBECTL" -n "$CONTROL_NS" rollout restart deployment/joysafeter-orchestrator >/dev/null
  wait_rollout deployment/joysafeter-orchestrator "$CONTROL_NS"
}

assert_egress_config() {
  local authority enabled credential_url forward_url
  authority="$("$KUBECTL" -n "$CONTROL_NS" get configmap joysafeter-config -o jsonpath='{.data.JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED}')"
  enabled="$("$KUBECTL" -n "$CONTROL_NS" get configmap joysafeter-config -o jsonpath='{.data.JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED}')"
  credential_url="$("$KUBECTL" -n "$CONTROL_NS" get configmap joysafeter-config -o jsonpath='{.data.JOYSAFETER_EGRESS_ENVOY_CREDENTIAL_URL}')"
  forward_url="$("$KUBECTL" -n "$CONTROL_NS" get configmap joysafeter-config -o jsonpath='{.data.JOYSAFETER_EGRESS_ENVOY_FORWARD_PROXY_URL}')"
  [[ "$authority" == "true" ]] || { echo "durable egress authority is not enabled" >&2; exit 1; }
  [[ "$enabled" == "true" ]] || { echo "K8s egress management is not enabled" >&2; exit 1; }
  [[ "$credential_url" == https://joysafeter-egress-envoy.*:8443 ]] || { echo "unexpected credential URL: $credential_url" >&2; exit 1; }
  [[ "$forward_url" == https://joysafeter-egress-envoy.*:8080 ]] || { echo "unexpected forward URL: $forward_url" >&2; exit 1; }
}

assert_node_local_envoy_ready() {
  local local_port status_url log_path
  local_port="${ORCHESTRATOR_HEALTH_PORT_FORWARD_PORT:-$((19000 + RANDOM % 1000))}"
  status_url="http://127.0.0.1:${local_port}"
  log_path="/tmp/joysafeter-k3s-rust-xds-port-forward-${local_port}.log"

  log "Starting temporary port-forward svc/joysafeter-orchestrator ${local_port}:8081"
  "$KUBECTL" -n "$CONTROL_NS" port-forward svc/joysafeter-orchestrator "${local_port}:8081" \
    >"$log_path" 2>&1 &
  XDS_STATUS_PORT_FORWARD_PID="$!"

  for _ in $(seq 1 30); do
    if curl -fsS "${status_url}/ready" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  curl -fsS "${status_url}/ready" >/dev/null || {
    sed -n '1,80p' "$log_path" >&2 || true
    echo "active Rust xDS orchestrator did not become ready" >&2
    exit 1
  }
  local metrics
  metrics="$(curl -fsS "${status_url}/metrics")"
  METRICS="$metrics" python3 <<'PY'
import os
import re

connected = 0.0
bad = []

metric_line = re.compile(r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+0-9.eE]+)$')

def labels_map(raw):
    labels = {}
    if not raw:
        return labels
    for item in re.finditer(r'([^=,]+)="((?:\\.|[^"])*)"', raw):
        labels[item.group(1)] = item.group(2)
    return labels

for line in os.environ["METRICS"].splitlines():
    if line.startswith("joysafeter_rust_xds_connected_nodes "):
        connected = float(line.rsplit(" ", 1)[1])
        continue
    match = metric_line.match(line)
    if not match:
        continue
    name = match.group("name")
    labels = labels_map(match.group("labels"))
    value = float(match.group("value"))
    if value <= 0:
        continue
    if name == "joysafeter_rust_xds_ack_total" and labels.get("result") == "nack":
        bad.append(f"xDS NACK observed for {labels.get('type', 'unknown')}: {value:g}")
    if name == "joysafeter_rust_xds_snapshot_events_total" and labels.get("result") in {"rolled_back", "timed_out"}:
        bad.append(f"snapshot {labels.get('result')}: {value:g}")
    if name == "joysafeter_rust_xds_reconcile_total" and labels.get("result") == "failed":
        bad.append(f"reconcile {labels.get('result')}: {value:g}")

if connected < 1:
    raise SystemExit("no Envoy node is connected to ADS over mTLS")
if bad:
    raise SystemExit("Rust xDS reported unhealthy state: " + "; ".join(bad))
PY
}

wait_for_task_sandbox() {
  local task_id="$1"
  local token="$2"
  local sandbox_id=""
  local status=""

  for _ in $(seq 1 "$WAIT_SECONDS"); do
    local response
    response="$(curl -sS "${API_URL}/api/v1/tasks/${task_id}" -H "Authorization: Bearer ${token}")"
    status="$(printf '%s' "$response" | json_get data.status 2>/dev/null || true)"
    sandbox_id="$(printf '%s' "$response" | json_get data.sandbox_id 2>/dev/null || true)"
    if [[ -n "$sandbox_id" && "$sandbox_id" != "None" ]]; then
      printf '%s\n' "$sandbox_id"
      return
    fi
    if [[ "$status" == "failed" ]]; then
      echo "Task failed before sandbox_id was assigned:" >&2
      printf '%s\n' "$response" >&2
      exit 1
    fi
    sleep 1
  done

  echo "Timed out waiting for task ${task_id} to receive sandbox_id" >&2
  exit 1
}

wait_for_task_terminal() {
  local task_id="$1"
  local token="$2"
  local status=""

  for _ in $(seq 1 "$TASK_WAIT_SECONDS"); do
    local response
    response="$(curl -sS "${API_URL}/api/v1/tasks/${task_id}" -H "Authorization: Bearer ${token}")"
    status="$(printf '%s' "$response" | json_get data.status 2>/dev/null || true)"
    if [[ "$status" == "completed" ]]; then
      printf '%s\n' "$response"
      return
    fi
    if [[ "$status" == "failed" || "$status" == "cancelled" ]]; then
      echo "Task reached terminal non-success status ${status}:" >&2
      printf '%s\n' "$response" >&2
      exit 1
    fi
    sleep 1
  done

  echo "Timed out waiting for task ${task_id} to complete" >&2
  exit 1
}

assert_pod_env_sanitized() {
  local sandbox_id="$1"
  local pod_name="$2"
  local pod_json
  pod_json="$("$KUBECTL" -n "$SANDBOX_NS" get "pod/${pod_name}" -o json)"
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}" \
  POD_JSON="$pod_json" \
  python3 - "$sandbox_id" <<'PY'
import json
import os
import sys

sandbox_id = sys.argv[1]
pod = json.loads(os.environ["POD_JSON"])
env = {}
for container in pod.get("spec", {}).get("containers", []):
    for item in container.get("env", []) or []:
        env[item.get("name")] = item.get("value")

annotations = pod.get("metadata", {}).get("annotations", {}) or {}
if annotations.get("kubectl.kubernetes.io/last-applied-configuration"):
    raise SystemExit(
        "Pod contains kubectl last-applied-configuration annotation; "
        "this can persist sandbox tokens from env"
    )

annotation_text = json.dumps(annotations, separators=(",", ":"))
for name, value in env.items():
    if value and value in annotation_text:
        raise SystemExit(f"pod annotation contains env value for {name}")

real_values = {
    value
    for value in [
        os.environ.get("ANTHROPIC_API_KEY", ""),
        os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
    ]
    if value
}
for name, value in env.items():
    if value in real_values:
        raise SystemExit(f"real model credential leaked into pod env: {name}")

base_url = env.get("ANTHROPIC_BASE_URL", "")
# Durable-authority egress rewrites the sandbox base URL to the per-sandbox
# Envoy route: <envoy>/v1/sandbox/<id>/route/<base64url(route_id)> (e.g. the
# "llm" route encodes to .../route/bGxt). Assert the authority format here.
expected_fragment = f"/v1/sandbox/{sandbox_id}/route/"
if expected_fragment not in base_url:
    raise SystemExit(f"ANTHROPIC_BASE_URL was not rewritten to the Envoy authority route: {base_url}")
if not base_url.startswith("https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8443/"):
    raise SystemExit(f"ANTHROPIC_BASE_URL does not use the TLS node-local Envoy listener: {base_url}")

runner_token = env.get("JOYSAFETER_RUNNER_TOKEN", "")
if not runner_token:
    raise SystemExit("JOYSAFETER_RUNNER_TOKEN missing from pod env")
for name in ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]:
    if env.get(name) != runner_token:
        raise SystemExit(f"{name} was not rewritten to the sandbox runner token")
if env.get("SSL_CERT_FILE") != "/var/run/joysafeter-egress/trust/ca-bundle.crt":
    raise SystemExit(f"sandbox combined CA bundle is not configured: {env.get('SSL_CERT_FILE')}")

init_names = [item.get("name") for item in pod.get("spec", {}).get("initContainers", [])]
if "build-egress-trust-bundle" not in init_names:
    raise SystemExit("sandbox trust-bundle init container is missing")
PY
}

assert_network_policy_shape() {
  local sandbox_id="$1"
  local policy_json
  policy_json="$("$KUBECTL" -n "$SANDBOX_NS" get "networkpolicy/joysafeter-egress-${sandbox_id}" -o json)"
  POLICY_JSON="$policy_json" python3 - "$sandbox_id" <<'PY'
import json
import os
import sys

sandbox_id = sys.argv[1]
policy = json.loads(os.environ["POLICY_JSON"])
selector = policy.get("spec", {}).get("podSelector", {}).get("matchLabels", {})
if selector.get("joysafeter.sandbox_id") != sandbox_id:
    raise SystemExit(f"NetworkPolicy selector is not scoped to sandbox {sandbox_id}: {selector}")

text = json.dumps(policy, separators=(",", ":"))
for forbidden in ["ai-api.jdcloud.com", "api.anthropic.com", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]:
    if forbidden in text:
        raise SystemExit(f"NetworkPolicy contains forbidden upstream/secret material: {forbidden}")

if "joysafeter-orchestrator" not in text:
    raise SystemExit("NetworkPolicy does not allow orchestrator service")
if "joysafeter-egress" not in text or "joysafeter-egress-envoy" not in text:
    raise SystemExit("NetworkPolicy does not allow only the node-local Envoy service")
if "ipBlock" in text:
    raise SystemExit("NetworkPolicy must not use ipBlock upstream egress")
PY
}

assert_generation_applied() {
  local sandbox_id="$1"
  local ready_nodes row generation state connected required acked nacks
  ready_nodes="$("$KUBECTL" -n "$EGRESS_NS" get daemonset joysafeter-egress-envoy -o jsonpath='{.status.numberReady}')"
  ready_nodes="${ready_nodes:-0}"
  for _ in $(seq 1 "$WAIT_SECONDS"); do
    row="$("$KUBECTL" -n "$CONTROL_NS" exec deployment/postgres -- \
      psql -U postgres -d joysafeter -Atc \
      "SELECT g.generation || '|' || COALESCE(a.state, '') || '|' || COALESCE(a.connected_nodes, 0) || '|' || COALESCE(a.required_acks, 0) || '|' || COALESCE(a.acked_acks, 0) FROM joysafeter_egress_group_generations g LEFT JOIN joysafeter_egress_apply_status a ON a.group_key = g.group_key AND a.generation = g.generation WHERE g.desired_policies @> '[{\"sandbox_id\":\"${sandbox_id}\"}]'::jsonb ORDER BY g.generation DESC LIMIT 1" 2>/dev/null || true)"
    if [[ -n "$row" ]]; then
      IFS='|' read -r generation state connected required acked <<<"$row"
      if [[ "$state" == "applied" && "$connected" -ge "$ready_nodes" && "$required" -gt 0 && "$acked" -eq "$required" ]]; then
        nacks="$("$KUBECTL" -n "$CONTROL_NS" exec deployment/postgres -- \
          psql -U postgres -d joysafeter -Atc \
          "SELECT count(*) FROM joysafeter_egress_node_apply_status n JOIN joysafeter_egress_group_generations g ON g.group_key = n.group_key AND g.generation = n.generation WHERE n.generation = ${generation} AND n.status = 'nack' AND g.desired_policies @> '[{\"sandbox_id\":\"${sandbox_id}\"}]'::jsonb" 2>/dev/null || true)"
        [[ "$nacks" == "0" ]] || { echo "generation ${generation} contains xDS NACKs" >&2; exit 1; }
        printf '%s\n' "$generation"
        return
      fi
    fi
    sleep 1
  done
  echo "timed out waiting for an all-node applied generation for sandbox ${sandbox_id}; last=${row:-none}" >&2
  exit 1
}

assert_wrong_token_denied() {
  local pod_name="$1"
  local base_url
  base_url="$("$KUBECTL" -n "$SANDBOX_NS" get "pod/${pod_name}" -o jsonpath='{.spec.containers[0].env[?(@.name=="ANTHROPIC_BASE_URL")].value}')"
  "$KUBECTL" -n "$SANDBOX_NS" exec "pod/${pod_name}" -- /bin/sh -ec '
    command -v curl >/dev/null
    base_url="$1"
    code="$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
      -X POST \
      -H "authorization: Bearer wrong-sandbox-token" \
      -H "x-api-key: wrong-sandbox-token" \
      -H "anthropic-version: 2023-06-01" \
      -H "content-type: application/json" \
      --data "{}" "${base_url%/}/v1/messages" || true)"
    test "$code" = "403"
  ' sh "$base_url"
}

wait_probe_client_succeeded() {
  local pod_name="$1"
  local phase=""
  for _ in $(seq 1 45); do
    phase="$("$KUBECTL" -n "$SANDBOX_NS" get "pod/${pod_name}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    if [[ "$phase" == "Succeeded" ]]; then
      return
    fi
    if [[ "$phase" == "Failed" ]]; then
      "$KUBECTL" -n "$SANDBOX_NS" logs "pod/${pod_name}" --tail=80 >&2 || true
      echo "bypass control probe pod ${pod_name} failed" >&2
      exit 1
    fi
    sleep 1
  done
  "$KUBECTL" -n "$SANDBOX_NS" logs "pod/${pod_name}" --tail=80 >&2 || true
  echo "timed out waiting for bypass control probe pod ${pod_name}; phase=${phase:-unknown}" >&2
  exit 1
}

assert_probe_service_reachable_from_control() {
  local sandbox_id="$1"
  local probe_url="$2"
  local phase="$3"
  local suffix client_name
  suffix="$(probe_name_suffix "$sandbox_id")"
  client_name="js-egress-probe-${suffix}-${phase}"
  BYPASS_PROBE_RESOURCES+=("pod/${client_name}")

  cat <<EOF | "$KUBECTL" -n "$SANDBOX_NS" create -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${client_name}
  labels:
    app.kubernetes.io/name: joysafeter-egress-bypass-control
    joysafeter.probe-run: ${sandbox_id}
    joysafeter.probe-role: control
    joysafeter.probe-phase: ${phase}
spec:
  restartPolicy: Never
  terminationGracePeriodSeconds: 1
  automountServiceAccountToken: false
  securityContext:
    seccompProfile:
      type: RuntimeDefault
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
  containers:
    - name: client
      image: ${EGRESS_BYPASS_PROBE_IMAGE}
      imagePullPolicy: IfNotPresent
      command: ["python", "-c"]
      args:
        - |
          import sys
          import time
          import urllib.request

          url = "${probe_url}"
          last_error = None
          for _ in range(20):
              try:
                  with urllib.request.urlopen(url, timeout=1) as response:
                      body = response.read(64)
                      if response.status < 500 and b"OK" in body:
                          print(f"control probe reached {url} with status={response.status}")
                          raise SystemExit(0)
                      last_error = f"unexpected status/body: status={response.status} body={body!r}"
              except Exception as exc:
                  last_error = str(exc)
              time.sleep(1)
          print(f"control probe could not reach {url}: {last_error}", file=sys.stderr)
          raise SystemExit(1)
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: false
        capabilities:
          drop: ["ALL"]
EOF
  wait_probe_client_succeeded "$client_name"
}

create_direct_bypass_probe_policies() {
  local sandbox_id="$1"
  local suffix ingress_policy egress_policy
  suffix="$(probe_name_suffix "$sandbox_id")"
  ingress_policy="js-egress-probe-${suffix}-srv-in"
  egress_policy="js-egress-probe-${suffix}-ctl-eg"
  BYPASS_PROBE_RESOURCES+=("networkpolicy/${ingress_policy}" "networkpolicy/${egress_policy}")

  cat <<EOF | "$KUBECTL" -n "$SANDBOX_NS" create -f - >/dev/null
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ${ingress_policy}
  labels:
    app.kubernetes.io/name: joysafeter-egress-bypass-probe
    app.kubernetes.io/part-of: joysafeter
    joysafeter.probe-run: ${sandbox_id}
spec:
  podSelector:
    matchLabels:
      joysafeter.probe-run: ${sandbox_id}
      joysafeter.probe-role: server
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector: {}
      ports:
        - protocol: TCP
          port: 18081
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ${egress_policy}
  labels:
    app.kubernetes.io/name: joysafeter-egress-bypass-control
    app.kubernetes.io/part-of: joysafeter
    joysafeter.probe-run: ${sandbox_id}
spec:
  podSelector:
    matchLabels:
      joysafeter.probe-run: ${sandbox_id}
      joysafeter.probe-role: control
  policyTypes:
    - Egress
  egress:
    - to:
        - podSelector:
            matchLabels:
              joysafeter.probe-run: ${sandbox_id}
              joysafeter.probe-role: server
      ports:
        - protocol: TCP
          port: 18081
EOF
}

prepare_direct_bypass_probe() {
  local sandbox_id="$1"
  local suffix server_name server_ip probe_url
  suffix="$(probe_name_suffix "$sandbox_id")"
  server_name="js-egress-probe-${suffix}-srv"

  log "Creating temporary in-cluster bypass probe ${SANDBOX_NS}/${server_name}"
  BYPASS_PROBE_RESOURCES+=("pod/${server_name}")
  create_direct_bypass_probe_policies "$sandbox_id"
  cat <<EOF | "$KUBECTL" -n "$SANDBOX_NS" create -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${server_name}
  labels:
    app.kubernetes.io/name: joysafeter-egress-bypass-probe
    joysafeter.probe-run: ${sandbox_id}
    joysafeter.probe-role: server
spec:
  restartPolicy: Never
  terminationGracePeriodSeconds: 1
  automountServiceAccountToken: false
  securityContext:
    seccompProfile:
      type: RuntimeDefault
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
  containers:
    - name: server
      image: ${EGRESS_BYPASS_PROBE_IMAGE}
      imagePullPolicy: IfNotPresent
      command: ["python", "-u", "-c"]
      args:
        - |
          from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

          class Handler(BaseHTTPRequestHandler):
              def do_GET(self):
                  self.send_response(200)
                  self.send_header("content-type", "text/plain")
                  self.end_headers()
                  self.wfile.write(b"OK")
              def log_message(self, *_args):
                  return

          server = ThreadingHTTPServer(("0.0.0.0", 18081), Handler)
          print("bypass probe listening on 0.0.0.0:18081", flush=True)
          server.serve_forever()
      ports:
        - containerPort: 18081
          protocol: TCP
      readinessProbe:
        httpGet:
          path: /
          port: 18081
        periodSeconds: 1
        timeoutSeconds: 1
        failureThreshold: 60
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: false
        capabilities:
          drop: ["ALL"]
EOF
  if ! "$KUBECTL" -n "$SANDBOX_NS" wait --for=condition=Ready "pod/${server_name}" --timeout=90s; then
    "$KUBECTL" -n "$SANDBOX_NS" logs "pod/${server_name}" --tail=80 >&2 || true
    "$KUBECTL" -n "$SANDBOX_NS" get "pod/${server_name}" -o yaml >&2 || true
    echo "bypass probe server did not become Ready" >&2
    exit 1
  fi
  server_ip="$("$KUBECTL" -n "$SANDBOX_NS" get "pod/${server_name}" -o jsonpath='{.status.podIP}')"
  probe_url="http://${server_ip}:18081/"
  assert_probe_service_reachable_from_control "$sandbox_id" "$probe_url" pre
  BYPASS_PROBE_URL="$probe_url"
}

assert_direct_bypass_denied() {
  local pod_name="$1"
  local upstream_url="$2"
  if ! "$KUBECTL" -n "$SANDBOX_NS" exec "pod/${pod_name}" -- /bin/sh -ec '
    command -v curl >/dev/null
    url="$1"
    err_path="/tmp/joysafeter-direct-bypass-${$}.err"
    set +e
    code="$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 8 \
      --noproxy "*" "$url" 2>"$err_path")"
    rc="$?"
    set -e
    if [ "$code" != "000" ]; then
      echo "direct bypass reached controlled probe service: http_status=${code}" >&2
      cat "$err_path" >&2 || true
      rm -f "$err_path"
      exit 42
    fi
    if [ "$rc" -ne 0 ]; then
      rm -f "$err_path"
      exit 0
    fi
    echo "direct bypass probe was inconclusive: curl_exit=${rc} http_status=${code}" >&2
    cat "$err_path" >&2 || true
    rm -f "$err_path"
    exit 43
  ' sh "$upstream_url"; then
    echo "sandbox direct-bypass probe did not prove NetworkPolicy denial for ${upstream_url}" >&2
    exit 1
  fi
}

print_run_context() {
  echo "Control namespace: $CONTROL_NS"
  echo "Egress namespace:  $EGRESS_NS"
  echo "Sandbox namespace: $SANDBOX_NS"
  echo "API URL:           $API_URL"
  echo "Run ID:            $RUN_ID"
  echo ""
}

run_preflight_only() {
  log "Current Kubernetes context: $("$KUBECTL" config current-context)"
  runtime_guard_assert_live_control_plane "$CONTROL_NS" "$SANDBOX_NS"
  runtime_guard_assert_orchestrator_image_api_only "$CONTROL_NS"
  runtime_guard_assert_orchestrator_sandbox_rbac "$CONTROL_NS" "$SANDBOX_NS"
  ensure_api
  print_run_context

  echo "This preflight validates live K8s/Envoy architecture only. It does not create platform users, platform Secrets, environments, agents, tasks, sandbox pods, or database rows."
  echo "It may apply/roll K8s egress-plane manifests, refresh ephemeral PKI Secrets, and temporarily patch the orchestrator egress ConfigMap."
  echo ""

  build_and_import_egress_images
  install_shared_egress_plane
  patch_egress_config
  assert_egress_config
  assert_node_local_envoy_ready
  runtime_guard_assert_live_control_plane "$CONTROL_NS" "$SANDBOX_NS"
  runtime_guard_assert_orchestrator_sandbox_rbac "$CONTROL_NS" "$SANDBOX_NS"
  runtime_guard_assert_sandbox_pods_api_created "$SANDBOX_NS"

  ok "k3s egress preflight passed"
  echo "Full model-backed egress smoke still requires ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN or EXISTING_SECRET_NAME."
}

main() {
  require_cmd "$KUBECTL"
  require_cmd curl
  require_cmd python3

  if [[ -n "$EXISTING_SECRET_NAME" ]]; then
    SMOKE_SECRET_NAME="$EXISTING_SECRET_NAME"
    RUN_SECRET_CONNECTIVITY_TEST="false"
  fi

  if [[ "$EGRESS_PREFLIGHT_ONLY" == "true" ]]; then
    run_preflight_only
    return
  fi

  if [[ -z "$EXISTING_SECRET_NAME" && -z "${ANTHROPIC_API_KEY:-}" && -z "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
    echo "Set ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN, or set EXISTING_SECRET_NAME to reuse an existing platform Secret." >&2
    echo "For non-secret structural validation, run: EGRESS_PREFLIGHT_ONLY=true $0" >&2
    exit 1
  fi

  log "Current Kubernetes context: $("$KUBECTL" config current-context)"
  runtime_guard_assert_live_control_plane "$CONTROL_NS" "$SANDBOX_NS"
  runtime_guard_assert_orchestrator_image_api_only "$CONTROL_NS"
  runtime_guard_assert_orchestrator_sandbox_rbac "$CONTROL_NS" "$SANDBOX_NS"
  ensure_api
  print_run_context
  echo "This script preserves validation data. It does not delete users, agents, secrets, environments, tasks, pods, jobs, namespaces, PVCs, or database rows."
  echo ""

  build_and_import_egress_images
  install_shared_egress_plane
  patch_egress_config
  assert_egress_config
  assert_node_local_envoy_ready
  runtime_guard_assert_live_control_plane "$CONTROL_NS" "$SANDBOX_NS"
  runtime_guard_assert_orchestrator_sandbox_rbac "$CONTROL_NS" "$SANDBOX_NS"

  local password_hash
  password_hash="$(python3 - "$SMOKE_PASSWORD" <<'PY'
import hashlib
import sys

print(hashlib.sha256(sys.argv[1].encode()).hexdigest())
PY
)"

  if [[ "$SKIP_SIGNUP" != "true" ]]; then
    log "Registering smoke user ${SMOKE_EMAIL}"
    local signup_body signup_response
    signup_body="$(json_body "email=${SMOKE_EMAIL}" "name=k3s Egress Smoke" "password=${password_hash}")"
    signup_response="$(post_json /api/v1/auth/sign-up/email "$signup_body")"
    assert_success "$signup_response" "sign-up"
  else
    log "Using existing smoke user ${SMOKE_EMAIL}"
  fi

  log "Signing in"
  local signin_body signin_response token
  signin_body="$(json_body "email=${SMOKE_EMAIL}" "password=${password_hash}")"
  signin_response="$(post_json /api/v1/auth/sign-in/email "$signin_body")"
  assert_success "$signin_response" "sign-in"
  token="$(printf '%s' "$signin_response" | json_get data.access_token)"

  local secret_data=""
  if [[ -z "$EXISTING_SECRET_NAME" ]]; then
    secret_data="$(
      ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
      ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}" \
      ANTHROPIC_BASE_URL="$ANTHROPIC_BASE_URL" \
      SMOKE_MODEL="$SMOKE_MODEL" \
      DEFAULT_SMOKE_MODEL="$DEFAULT_SMOKE_MODEL" \
      python3 <<'PY'
import json
import os

data = {
    "ANTHROPIC_BASE_URL": os.environ["ANTHROPIC_BASE_URL"],
    "ANTHROPIC_MODEL": os.environ.get("SMOKE_MODEL") or os.environ["DEFAULT_SMOKE_MODEL"],
}
if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    data["ANTHROPIC_AUTH_TOKEN"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
else:
    data["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
print(json.dumps(data, separators=(",", ":")))
PY
    )"
  fi

  if [[ "$RUN_SECRET_CONNECTIVITY_TEST" == "true" ]]; then
    log "Testing Anthropic-compatible Secret connectivity through API allowlist"
    local test_response
    test_response="$(
      python3 - "$secret_data" <<'PY' | \
      curl -sS -X POST "${API_URL}/api/v1/secrets/test" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${token}" \
        -d @-
import json
import sys

print(json.dumps({
    "provider": "claude",
    "protocol": "anthropic_messages",
    "data": json.loads(sys.argv[1]),
}, separators=(",", ":")))
PY
    )"
    assert_success "$test_response" "secret-connectivity-test"
    if [[ "$(printf '%s' "$test_response" | json_get data.ok 2>/dev/null || true)" != "True" && \
          "$(printf '%s' "$test_response" | json_get data.ok 2>/dev/null || true)" != "true" ]]; then
      echo "Secret connectivity test returned ok=false:" >&2
      printf '%s\n' "$test_response" >&2
      exit 1
    fi
  fi

  if [[ -z "$EXISTING_SECRET_NAME" ]]; then
    log "Creating platform Secret ${SMOKE_SECRET_NAME}"
    local secret_response
    secret_response="$(
      python3 - "$SMOKE_SECRET_NAME" "$secret_data" <<'PY' | \
      curl -sS -X POST "${API_URL}/api/v1/secrets" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${token}" \
        -d @-
import json
import sys

print(json.dumps({
    "name": sys.argv[1],
    "provider": "claude",
    "protocol": "anthropic_messages",
    "data": json.loads(sys.argv[2]),
}, separators=(",", ":")))
PY
    )"
    assert_success "$secret_response" "create-secret"
  else
    log "Reusing existing platform Secret ${SMOKE_SECRET_NAME}"
  fi

  log "Creating limited-networking Environment ${SMOKE_ENV_NAME}"
  local env_response
  env_response="$(
    python3 - "$SMOKE_ENV_NAME" "$SMOKE_SECRET_NAME" "$(base_host)" <<'PY' | \
    curl -sS -X POST "${API_URL}/api/v1/environments" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${token}" \
      -d @-
import json
import sys

print(json.dumps({
    "name": sys.argv[1],
    "description": "k3s egress smoke environment",
    "metadata": {"joysafeter_smoke": "k3s-egress"},
    "config": {
        "type": "cloud",
        "networking": {
            "type": "limited",
            "allowed_hosts": [sys.argv[3]],
            "allow_mcp_servers": False,
            "allow_package_managers": False,
        },
        "secret_refs": [sys.argv[2]],
        "egress_services": [],
    },
}, separators=(",", ":")))
PY
  )"
  assert_success "$env_response" "create-environment"

  log "Creating Secret-backed Agent ${SMOKE_AGENT_NAME}"
  local agent_response agent_wire_id agent_id
  agent_response="$(
    python3 - "$SMOKE_AGENT_NAME" "$SMOKE_MODEL" "$SMOKE_SECRET_NAME" "$SMOKE_ENV_NAME" "$SMOKE_SYSTEM_PROMPT" <<'PY' | \
    curl -sS -X POST "${API_URL}/api/v1/agents" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${token}" \
      -d @-
import json
import sys

payload = {
    "name": sys.argv[1],
    "engine_kind": "claude",
    "tools": [],
    "skills": [],
    "env": {
        # This smoke validates the JoySafeter egress boundary, not Claude Code's
        # newest Anthropic beta surface. Several Anthropic-compatible gateways
        # accept normal Messages requests but reject Claude Code's default
        # title/thinking/experimental-beta requests. Keep the smoke on the
        # narrowest CLI request shape that still exercises the real model path.
        "CLAUDE_CODE_SIMPLE": "1",
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_CODE_DISABLE_THINKING": "1",
        "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1",
        "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
        "DISABLE_INTERLEAVED_THINKING": "1",
    },
    "secret_ref": sys.argv[3],
    "environment_ref": sys.argv[4],
}
if sys.argv[2]:
    payload["model"] = sys.argv[2]
if sys.argv[5]:
    payload["system_prompt"] = sys.argv[5]
print(json.dumps(payload, separators=(",", ":")))
PY
  )"
  assert_success "$agent_response" "create-agent"
  agent_wire_id="$(printf '%s' "$agent_response" | json_get data.id)"
  agent_id="${agent_wire_id#agent_}"

  log "Creating Secret-backed limited-networking Task"
  local task_response task_id
  task_response="$(
    python3 - "$agent_id" "$SMOKE_ENV_NAME" "$SMOKE_TIMEOUT_SEC" <<'PY' | \
    curl -sS -X POST "${API_URL}/api/v1/tasks" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${token}" \
      -H "Idempotency-Key: k3s-egress-task-${RUN_ID}" \
      -d @-
import json
import sys

print(json.dumps({
    "agent_id": sys.argv[1],
    "environment_ref": sys.argv[2],
    "prompt": "k3s egress smoke: reply exactly with K3S_EGRESS_OK and stop.",
    "timeout_sec": int(sys.argv[3]),
    "max_retries": 0,
}, separators=(",", ":")))
PY
  )"
  assert_success "$task_response" "create-task"
  task_id="$(printf '%s' "$task_response" | json_get data.id)"

  log "Waiting for task ${task_id} to get a sandbox"
  local sandbox_id pod_name
  sandbox_id="$(wait_for_task_sandbox "$task_id" "$token")"
  pod_name="joysafeter-${sandbox_id}"

  log "Waiting for sandbox pod ${pod_name}"
  "$KUBECTL" -n "$SANDBOX_NS" wait --for=condition=Ready "pod/${pod_name}" --timeout="${WAIT_SECONDS}s"

  runtime_guard_assert_sandbox_pods_api_created "$SANDBOX_NS" "$pod_name"

  log "Verifying Pod env has Envoy placeholders, trust bundle, and no real credentials"
  assert_pod_env_sanitized "$sandbox_id" "$pod_name"

  log "Verifying Envoy-only per-sandbox NetworkPolicy shape"
  assert_network_policy_shape "$sandbox_id"

  log "Verifying durable generation is ACKed by every ready Envoy node"
  local generation
  generation="$(assert_generation_applied "$sandbox_id")"

  log "Verifying a wrong sandbox token is denied by ext_authz"
  assert_wrong_token_denied "$pod_name"

  if [[ "$EGRESS_BYPASS_PROBE_ENABLED" == "true" ]]; then
    log "Verifying NetworkPolicy blocks a controlled direct-bypass service"
    prepare_direct_bypass_probe "$sandbox_id"
    assert_direct_bypass_denied "$pod_name" "$BYPASS_PROBE_URL"
    assert_probe_service_reachable_from_control "$sandbox_id" "$BYPASS_PROBE_URL" post
  else
    warn "Skipping controlled direct-bypass NetworkPolicy probe because EGRESS_BYPASS_PROBE_ENABLED=false"
  fi

  log "Waiting for model-backed task completion"
  local final_task final_output
  final_task="$(wait_for_task_terminal "$task_id" "$token")"
  final_output="$(printf '%s' "$final_task" | json_get data.output 2>/dev/null || true)"

  if [[ "$final_output" != *"$EXPECTED_OUTPUT_FRAGMENT"* ]]; then
    if [[ "$ALLOW_UPSTREAM_MODEL_ERROR" == "true" ]]; then
      warn "Task completed but model output did not contain ${EXPECTED_OUTPUT_FRAGMENT}; treating as egress connectivity-only success because ALLOW_UPSTREAM_MODEL_ERROR=true"
    else
      echo "Task completed but model output did not contain expected fragment '${EXPECTED_OUTPUT_FRAGMENT}'." >&2
      echo "This means the sandbox egress path ran, but the model request did not produce the expected business result." >&2
      echo "Secret:    ${SMOKE_SECRET_NAME}" >&2
      echo "Env:       ${SMOKE_ENV_NAME}" >&2
      echo "Agent:     ${SMOKE_AGENT_NAME}" >&2
      echo "Task:      ${task_id}" >&2
      echo "Sandbox:   ${sandbox_id}" >&2
      echo "Pod:       ${SANDBOX_NS}/${pod_name}" >&2
      if [[ -n "$final_output" ]]; then
        echo "Output:    ${final_output}" >&2
      fi
      exit 1
    fi
  fi

  ok "k3s egress smoke passed"
  echo "Secret:    ${SMOKE_SECRET_NAME}"
  echo "Env:       ${SMOKE_ENV_NAME}"
  echo "Agent:     ${SMOKE_AGENT_NAME}"
  echo "Task:      ${task_id}"
  echo "Sandbox:   ${sandbox_id}"
  echo "Pod:       ${SANDBOX_NS}/${pod_name}"
  echo "Generation:${generation}"
  if [[ -n "$final_output" ]]; then
    echo "Output:    ${final_output}"
  fi
  echo ""
  echo "Inspect:"
  echo "  $KUBECTL -n $SANDBOX_NS get pod $pod_name -o yaml"
  echo "  $KUBECTL -n $SANDBOX_NS get networkpolicy joysafeter-egress-$sandbox_id -o yaml"
  echo "  $KUBECTL -n $CONTROL_NS logs deployment/joysafeter-orchestrator --tail=200"
  echo "  $KUBECTL -n $EGRESS_NS logs daemonset/joysafeter-egress-envoy --tail=200"
}

main "$@"
