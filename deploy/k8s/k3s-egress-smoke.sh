#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

KUBECTL="${KUBECTL:-kubectl}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
SANDBOX_NS="${JOYSAFETER_K8S_NAMESPACE:-joysafeter-sandboxes}"
API_URL="${API_URL:-http://127.0.0.1:8000}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d%H%M%S)}"
SMOKE_EMAIL="${SMOKE_EMAIL:-k3s-egress-${RUN_ID}@example.com}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:-K3sEgressSmokePass123!}"
SKIP_SIGNUP="${SKIP_SIGNUP:-false}"
SMOKE_SECRET_NAME="${SMOKE_SECRET_NAME:-k3s-egress-secret-${RUN_ID}}"
EXISTING_SECRET_NAME="${EXISTING_SECRET_NAME:-}"
SMOKE_ENV_NAME="${SMOKE_ENV_NAME:-k3s-egress-env-${RUN_ID}}"
SMOKE_AGENT_NAME="${SMOKE_AGENT_NAME:-k3s-egress-agent-${RUN_ID}}"
DEFAULT_SMOKE_MODEL="${DEFAULT_SMOKE_MODEL:-claude-sonnet-4-20250514}"
SMOKE_MODEL="${SMOKE_MODEL:-}"
SMOKE_TIMEOUT_SEC="${SMOKE_TIMEOUT_SEC:-600}"
WAIT_SECONDS="${WAIT_SECONDS:-180}"
TASK_WAIT_SECONDS="${TASK_WAIT_SECONDS:-600}"
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"
PATCH_EGRESS_CONFIG="${PATCH_EGRESS_CONFIG:-true}"
RUN_SECRET_CONNECTIVITY_TEST="${RUN_SECRET_CONNECTIVITY_TEST:-true}"
EXPECTED_OUTPUT_FRAGMENT="${EXPECTED_OUTPUT_FRAGMENT:-K3S_EGRESS_OK}"
ALLOW_UPSTREAM_MODEL_ERROR="${ALLOW_UPSTREAM_MODEL_ERROR:-false}"

PORT_FORWARD_PID=""
GATEWAY_PORT_FORWARD_PID=""

log() { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok() { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }

stop_port_forwards_on_exit() {
  if [[ -n "$PORT_FORWARD_PID" ]]; then
    kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$GATEWAY_PORT_FORWARD_PID" ]]; then
    kill "$GATEWAY_PORT_FORWARD_PID" >/dev/null 2>&1 || true
  fi
}
trap stop_port_forwards_on_exit EXIT

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

api_live() {
  curl -fsS "${API_URL}/api/v1/health/live" >/dev/null 2>&1
}

ensure_api() {
  if api_live; then
    return
  fi

  if [[ "$API_URL" != "http://127.0.0.1:8000" && "$API_URL" != "http://localhost:8000" ]]; then
    echo "API is not reachable at ${API_URL}" >&2
    exit 1
  fi

  log "API not reachable directly; starting temporary port-forward svc/api 8000:8000"
  "$KUBECTL" -n "$CONTROL_NS" port-forward svc/api 8000:8000 >/tmp/joysafeter-k3s-api-port-forward.log 2>&1 &
  PORT_FORWARD_PID="$!"

  for _ in $(seq 1 30); do
    if api_live; then
      return
    fi
    sleep 1
  done

  warn "port-forward log:"
  sed -n '1,80p' /tmp/joysafeter-k3s-api-port-forward.log >&2 || true
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
  local deployment="$1"
  "$KUBECTL" -n "$CONTROL_NS" rollout status "deployment/$deployment" --timeout=300s
}

patch_egress_config() {
  if [[ "$PATCH_EGRESS_CONFIG" != "true" ]]; then
    return
  fi

  log "Patching k3s egress config on ConfigMap/Secret"
  local host control_token cm_patch
  host="$(base_host)"
  control_token="${JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN:-}"

  cm_patch="$(
    python3 - "$host" <<'PY'
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
deduped = []
for item in allowed:
    if item and item not in deduped:
        deduped.append(item)

print(json.dumps({
    "data": {
        "JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED": "true",
        "JOYSAFETER_EGRESS_GATEWAY_URL": "http://joysafeter-egress-gateway.joysafeter-control.svc.cluster.local:8088",
        "JOYSAFETER_EGRESS_GATEWAY_HOST": "0.0.0.0",
        "JOYSAFETER_EGRESS_GATEWAY_PORT": "8088",
        "JOYSAFETER_EGRESS_GATEWAY_REQUIRE_SANDBOX_TOKEN": "true",
        "JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS": ",".join(deduped),
    }
}, separators=(",", ":")))
PY
  )"
  "$KUBECTL" -n "$CONTROL_NS" patch configmap joysafeter-config --type merge -p "$cm_patch" >/dev/null

  if [[ -n "$control_token" ]]; then
    local secret_patch
    secret_patch="$(
      JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN="$control_token" python3 <<'PY'
import base64
import json
import os

token = os.environ["JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN"].strip()
if not token:
    raise SystemExit("control token must not be empty")
print(json.dumps({
    "data": {
        "JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN": base64.b64encode(token.encode()).decode()
    }
}, separators=(",", ":")))
PY
    )"
    "$KUBECTL" -n "$CONTROL_NS" patch secret joysafeter-secret --type merge -p "$secret_patch" >/dev/null
  fi

  log "Restarting egress gateway and orchestrator to pick up egress config"
  "$KUBECTL" -n "$CONTROL_NS" rollout restart deployment/joysafeter-egress-gateway >/dev/null
  "$KUBECTL" -n "$CONTROL_NS" rollout restart deployment/joysafeter-orchestrator >/dev/null
  wait_rollout joysafeter-egress-gateway
  wait_rollout joysafeter-orchestrator
}

assert_egress_config() {
  local enabled gateway_url gateway_token
  enabled="$("$KUBECTL" -n "$CONTROL_NS" get configmap joysafeter-config -o jsonpath='{.data.JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED}')"
  gateway_url="$("$KUBECTL" -n "$CONTROL_NS" get configmap joysafeter-config -o jsonpath='{.data.JOYSAFETER_EGRESS_GATEWAY_URL}')"
  gateway_token="$("$KUBECTL" -n "$CONTROL_NS" get secret joysafeter-secret -o jsonpath='{.data.JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN}' || true)"
  if [[ "$enabled" != "true" ]]; then
    echo "JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED is not true in ${CONTROL_NS}/joysafeter-config" >&2
    exit 1
  fi
  if [[ "$gateway_url" != "http://joysafeter-egress-gateway.joysafeter-control.svc.cluster.local:8088" ]]; then
    echo "JOYSAFETER_EGRESS_GATEWAY_URL is not the expected in-cluster gateway URL: ${gateway_url}" >&2
    exit 1
  fi
  if [[ -z "$gateway_token" ]]; then
    echo "JOYSAFETER_EGRESS_GATEWAY_CONTROL_TOKEN is missing in ${CONTROL_NS}/joysafeter-secret" >&2
    exit 1
  fi
}

assert_gateway_ready() {
  if curl -fsS "http://127.0.0.1:18088/readyz" >/dev/null 2>&1; then
    return
  fi

  log "Starting temporary port-forward svc/joysafeter-egress-gateway 18088:8088"
  "$KUBECTL" -n "$CONTROL_NS" port-forward svc/joysafeter-egress-gateway 18088:8088 >/tmp/joysafeter-k3s-egress-gateway-port-forward.log 2>&1 &
  GATEWAY_PORT_FORWARD_PID="$!"
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:18088/readyz" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  warn "egress gateway port-forward log:"
  sed -n '1,80p' /tmp/joysafeter-k3s-egress-gateway-port-forward.log >&2 || true
  echo "egress gateway /readyz did not become healthy" >&2
  exit 1
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
expected_fragment = f"/sandbox/{sandbox_id}/egress/llm"
if expected_fragment not in base_url:
    raise SystemExit(f"ANTHROPIC_BASE_URL was not rewritten to gateway route: {base_url}")

if not env.get("JOYSAFETER_EGRESS_GATEWAY_SANDBOX_TOKEN"):
    raise SystemExit("JOYSAFETER_EGRESS_GATEWAY_SANDBOX_TOKEN missing from pod env")
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
if "joysafeter-egress-gateway" not in text:
    raise SystemExit("NetworkPolicy does not allow egress gateway service")
if "ipBlock" in text:
    raise SystemExit("NetworkPolicy must not use ipBlock upstream egress")
PY
}

main() {
  require_cmd "$KUBECTL"
  require_cmd curl
  require_cmd python3

  if [[ -n "$EXISTING_SECRET_NAME" ]]; then
    SMOKE_SECRET_NAME="$EXISTING_SECRET_NAME"
    RUN_SECRET_CONNECTIVITY_TEST="false"
  fi

  if [[ -z "$EXISTING_SECRET_NAME" && -z "${ANTHROPIC_API_KEY:-}" && -z "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
    echo "Set ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN, or set EXISTING_SECRET_NAME to reuse an existing platform Secret." >&2
    exit 1
  fi

  log "Current Kubernetes context: $("$KUBECTL" config current-context)"
  echo "Control namespace: $CONTROL_NS"
  echo "Sandbox namespace: $SANDBOX_NS"
  echo "API URL:           $API_URL"
  echo "Run ID:            $RUN_ID"
  echo ""
  echo "This script preserves validation data. It does not delete users, agents, secrets, environments, tasks, pods, jobs, namespaces, PVCs, or database rows."
  echo ""

  patch_egress_config
  assert_egress_config
  assert_gateway_ready
  ensure_api

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
    python3 - "$SMOKE_AGENT_NAME" "$SMOKE_MODEL" "$SMOKE_SECRET_NAME" "$SMOKE_ENV_NAME" <<'PY' | \
    curl -sS -X POST "${API_URL}/api/v1/agents" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${token}" \
      -d @-
import json
import sys

payload = {
    "name": sys.argv[1],
    "engine_kind": "claude",
    "system_prompt": "You are a k3s egress smoke test agent. Reply with a short deterministic answer.",
    "tools": [],
    "skills": [],
    "env": {},
    "secret_ref": sys.argv[3],
    "environment_ref": sys.argv[4],
}
if sys.argv[2]:
    payload["model"] = sys.argv[2]
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

  log "Verifying Pod env has gateway placeholders, not real model credentials"
  assert_pod_env_sanitized "$sandbox_id" "$pod_name"

  log "Verifying per-sandbox NetworkPolicy shape"
  assert_network_policy_shape "$sandbox_id"

  log "Waiting for model-backed task completion"
  local final_task final_output
  final_task="$(wait_for_task_terminal "$task_id" "$token")"
  final_output="$(printf '%s' "$final_task" | json_get data.output 2>/dev/null || true)"

  if [[ "$final_output" != *"$EXPECTED_OUTPUT_FRAGMENT"* ]]; then
    if [[ "$ALLOW_UPSTREAM_MODEL_ERROR" == "true" ]]; then
      warn "Task completed but model output did not contain ${EXPECTED_OUTPUT_FRAGMENT}; treating as gateway connectivity-only success because ALLOW_UPSTREAM_MODEL_ERROR=true"
    else
      echo "Task completed but model output did not contain expected fragment '${EXPECTED_OUTPUT_FRAGMENT}'." >&2
      echo "This means the sandbox/gateway path ran, but the model request did not produce the expected business result." >&2
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
  if [[ -n "$final_output" ]]; then
    echo "Output:    ${final_output}"
  fi
  echo ""
  echo "Inspect:"
  echo "  $KUBECTL -n $SANDBOX_NS get pod $pod_name -o yaml"
  echo "  $KUBECTL -n $SANDBOX_NS get networkpolicy joysafeter-egress-$sandbox_id -o yaml"
  echo "  $KUBECTL -n $CONTROL_NS logs deployment/joysafeter-egress-gateway --tail=200"
}

main "$@"
