#!/usr/bin/env bash
set -euo pipefail

KUBECTL="${KUBECTL:-kubectl}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
SANDBOX_NS="${JOYSAFETER_K8S_NAMESPACE:-joysafeter-sandboxes}"
API_URL="${API_URL:-http://127.0.0.1:8000}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d%H%M%S)}"
SMOKE_EMAIL="${SMOKE_EMAIL:-k3s-smoke-${RUN_ID}@example.com}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:-K3sSmokePass123!}"
SMOKE_AGENT_NAME="${SMOKE_AGENT_NAME:-k3s-smoke-agent-${RUN_ID}}"
SMOKE_MODEL="${SMOKE_MODEL:-claude-sonnet-4-20250514}"
SMOKE_TIMEOUT_SEC="${SMOKE_TIMEOUT_SEC:-120}"
WAIT_SECONDS="${WAIT_SECONDS:-90}"

PORT_FORWARD_PID=""

log() { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok() { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }

stop_port_forward_on_exit() {
  if [[ -n "$PORT_FORWARD_PID" ]]; then
    kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
  fi
}
trap stop_port_forward_on_exit EXIT

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

main() {
  require_cmd "$KUBECTL"
  require_cmd curl
  require_cmd python3

  ensure_api

  local password_hash
  password_hash="$(python3 - "$SMOKE_PASSWORD" <<'PY'
import hashlib
import sys

print(hashlib.sha256(sys.argv[1].encode()).hexdigest())
PY
)"

  log "Registering smoke user ${SMOKE_EMAIL}"
  local signup_body signup_response
  signup_body="$(json_body "email=${SMOKE_EMAIL}" "name=k3s Smoke" "password=${password_hash}")"
  signup_response="$(post_json /api/v1/auth/sign-up/email "$signup_body")"
  assert_success "$signup_response" "sign-up"

  log "Signing in"
  local signin_body signin_response token
  signin_body="$(json_body "email=${SMOKE_EMAIL}" "password=${password_hash}")"
  signin_response="$(post_json /api/v1/auth/sign-in/email "$signin_body")"
  assert_success "$signin_response" "sign-in"
  token="$(printf '%s' "$signin_response" | json_get data.access_token)"

  log "Creating smoke agent"
  local agent_body agent_response agent_wire_id agent_id
  agent_body="$(
    python3 - "$SMOKE_AGENT_NAME" "$SMOKE_MODEL" <<'PY'
import json
import sys

print(json.dumps({
    "name": sys.argv[1],
    "engine_kind": "claude",
    "model": sys.argv[2],
    "system_prompt": "You are a k3s smoke test agent. Keep output short.",
    "tools": [],
    "skills": [],
    "env": {},
}, separators=(",", ":")))
PY
  )"
  agent_response="$(post_json /api/v1/agents "$agent_body" -H "Authorization: Bearer ${token}")"
  assert_success "$agent_response" "create-agent"
  agent_wire_id="$(printf '%s' "$agent_response" | json_get data.id)"
  agent_id="${agent_wire_id#agent_}"

  log "Creating smoke task"
  local task_body task_response task_id
  task_body="$(
    python3 - "$agent_id" "$SMOKE_TIMEOUT_SEC" <<'PY'
import json
import sys

print(json.dumps({
    "agent_id": sys.argv[1],
    "prompt": "k3s smoke: reply with OK and stop.",
    "timeout_sec": int(sys.argv[2]),
    "max_retries": 0,
}, separators=(",", ":")))
PY
  )"
  task_response="$(
    post_json /api/v1/tasks "$task_body" \
      -H "Authorization: Bearer ${token}" \
      -H "Idempotency-Key: k3s-smoke-task-${RUN_ID}"
  )"
  assert_success "$task_response" "create-task"
  task_id="$(printf '%s' "$task_response" | json_get data.id)"

  log "Waiting for task ${task_id} to get a sandbox"
  local sandbox_id pod_name
  sandbox_id="$(wait_for_task_sandbox "$task_id" "$token")"
  pod_name="joysafeter-${sandbox_id}"

  log "Waiting for sandbox pod ${pod_name}"
  "$KUBECTL" -n "$SANDBOX_NS" wait --for=condition=Ready "pod/${pod_name}" --timeout="${WAIT_SECONDS}s"

  log "Checking runner handshake logs"
  local pod_logs
  pod_logs="$("$KUBECTL" -n "$SANDBOX_NS" logs "$pod_name" --tail=120)"
  if ! grep -q "RunnerReady sent" <<<"$pod_logs"; then
    echo "RunnerReady was not observed in sandbox logs" >&2
    printf '%s\n' "$pod_logs" >&2
    exit 1
  fi
  if ! grep -q "Received StartTask" <<<"$pod_logs"; then
    echo "StartTask was not observed in sandbox logs" >&2
    printf '%s\n' "$pod_logs" >&2
    exit 1
  fi

  local final_task final_status final_output
  final_task="$(curl -sS "${API_URL}/api/v1/tasks/${task_id}" -H "Authorization: Bearer ${token}")"
  final_status="$(printf '%s' "$final_task" | json_get data.status 2>/dev/null || true)"
  final_output="$(printf '%s' "$final_task" | json_get data.output 2>/dev/null || true)"

  ok "k3s task smoke passed"
  echo "Task:      ${task_id}"
  echo "Status:    ${final_status}"
  echo "Sandbox:   ${sandbox_id}"
  echo "Pod:       ${SANDBOX_NS}/${pod_name}"
  if [[ -n "$final_output" ]]; then
    echo "Output:    ${final_output}"
  fi
  echo ""
  echo "Inspect:"
  echo "  $KUBECTL -n $SANDBOX_NS logs $pod_name --tail=120"
  echo "  curl -sS $API_URL/api/v1/tasks/$task_id -H 'Authorization: Bearer <token>'"
}

main "$@"
