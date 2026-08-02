#!/usr/bin/env bash
# =============================================================================
# Docker egress MULTI-TENANT ISOLATION validation (complex, real scenarios).
# =============================================================================
# Beyond the single-sandbox smoke, this proves the per-tenant security
# properties that matter in production, all through the REAL controller-driven
# Envoy + ext_authz (mock upstream, no real key):
#
#   1. Distinct credentials: two sandboxes backed by DIFFERENT platform secrets
#      each inject ONLY their own credential at the egress boundary.
#   2. Cross-tenant isolation: sandbox A's runner token presented on sandbox B's
#      Envoy socket is DENIED (403) — a sandbox cannot impersonate another or
#      reuse a stolen token against a different sandbox's credential route.
#   3. Bogus token denied (403) on both.
#
# Requires the controller-mode stack already up (deploy/egress-compose-smoke.sh
# infra). Uses the same helpers.
# =============================================================================
set -euo pipefail

SMOKE_API_PORT="${SMOKE_API_PORT:-8000}"
API_URL="${API_URL:-http://localhost:${SMOKE_API_PORT}}"
DB_CONTAINER="${DB_CONTAINER:-joysafeter-db}"
SOCKET_VOLUME="${JOYSAFETER_ENVOY_SOCKET_VOLUME:-joysafeter-sockets}"
HELPER_IMAGE="${BACKEND_FULL_IMAGE:-joysafeter-backend:latest}"
MOCK_HOST="joysafeter-egress-mock-upstream"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-joysafeter}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d%H%M%S)}"
WAIT_SECONDS="${WAIT_SECONDS:-120}"

log()  { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }
die()  { printf '\033[0;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
has()  { case "$2" in *"$1"*) return 0 ;; *) return 1 ;; esac; }

json_get() { python3 -c "import sys,json
d=json.load(sys.stdin)
for p in sys.argv[1].split('.'):
    d=d.get(p) if isinstance(d,dict) else None
    if d is None: break
print(d if d is not None else '')" "$1"; }
authpost() { curl -sS -X POST "${API_URL}$1" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d "$2"; }
assert_success() { [ "$(printf '%s' "$1" | json_get success)" = "True" ] || die "$2 failed: $1"; }
psql_q() { docker exec "$DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"; }

# Probe the per-sandbox Envoy http.sock with a bearer token; echo "STATUS<TAB>BODY".
probe() { # $1=sandbox_id  $2=bearer token
  docker run -i --rm -v "${SOCKET_VOLUME}:/sockets:ro" "$HELPER_IMAGE" python3 - "/sockets/$1/http.sock" "$2" <<'PY'
import socket,sys
sock,tok=sys.argv[1],sys.argv[2]
try:
    s=socket.socket(socket.AF_UNIX); s.settimeout(10); s.connect(sock)
    s.sendall((f"POST /v1/messages HTTP/1.1\r\nHost: llm-egress.internal\r\n"
               f"authorization: Bearer {tok}\r\nx-api-key: {tok}\r\n"
               "content-type: application/json\r\ncontent-length: 2\r\nconnection: close\r\n\r\n{}").encode())
    buf=b""
    while True:
        c=s.recv(65536)
        if not c: break
        buf+=c
except Exception as e:
    sys.stdout.write("000\t"+repr(e)); sys.exit(0)
head,_,body=buf.partition(b"\r\n\r\n")
status=head.split(b"\r\n",1)[0].split(b" ")[1].decode() if head else "000"
sys.stdout.write(status+"\t"+body.decode(errors="replace"))
PY
}

seed_sandbox() { # $1=suffix  $2=platform_token ; prints "SANDBOX_ID RUNNER_TOKEN"
  local sfx="$1" ptoken="$2"
  local secret="iso-secret-${sfx}-${RUN_ID}" env="iso-env-${sfx}-${RUN_ID}" agent="iso-agent-${sfx}-${RUN_ID}"
  local secret_body env_body agent_body task_body
  secret_body="{\"name\":\"$secret\",\"provider\":\"claude\",\"protocol\":\"anthropic_messages\",\"data\":{\"ANTHROPIC_BASE_URL\":\"http://${MOCK_HOST}:8080/v1\",\"ANTHROPIC_AUTH_TOKEN\":\"${ptoken}\"}}"
  assert_success "$(authpost /api/v1/secrets "$secret_body")" "secret-$sfx"
  env_body="{\"name\":\"$env\",\"description\":\"iso\",\"config\":{\"type\":\"cloud\",\"networking\":{\"type\":\"limited\",\"allowed_hosts\":[\"${MOCK_HOST}\"],\"allow_mcp_servers\":false,\"allow_package_managers\":false},\"secret_refs\":[\"$secret\"],\"egress_services\":[]}}"
  assert_success "$(authpost /api/v1/environments "$env_body")" "env-$sfx"
  agent_body="{\"name\":\"$agent\",\"engine_kind\":\"claude\",\"system_prompt\":\"iso\",\"tools\":[],\"skills\":[],\"env\":{},\"secret_ref\":\"$secret\",\"environment_ref\":\"$env\"}"
  local aresp; aresp="$(authpost /api/v1/agents "$agent_body")"
  assert_success "$aresp" "agent-$sfx"
  local aid; aid="$(printf '%s' "$aresp" | json_get data.id)"; aid="${aid#agent_}"
  task_body="{\"agent_id\":\"$aid\",\"environment_ref\":\"$env\",\"prompt\":\"iso\",\"timeout_sec\":600,\"max_retries\":0}"
  local tresp; tresp="$(curl -sS -X POST "${API_URL}/api/v1/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: iso-${sfx}-${RUN_ID}" -d "$task_body")"
  assert_success "$tresp" "task-$sfx"
  local tid; tid="$(printf '%s' "$tresp" | json_get data.id)"
  local sid=""
  for _ in $(seq 1 "$WAIT_SECONDS"); do
    local r; r="$(curl -sS "${API_URL}/api/v1/tasks/${tid}" -H "Authorization: Bearer $TOKEN")"
    sid="$(printf '%s' "$r" | json_get data.sandbox_id)"
    [ -n "$sid" ] && [ "$sid" != "None" ] && break
    case "$(printf '%s' "$r" | json_get data.error)" in *EGRESS_POLICY_APPLY_TIMEOUT*|*EGRESS_POLICY_APPLY_FAILED*) die "control-plane apply failed for $sfx: $(printf '%s' "$r" | json_get data.error)";; esac
    sleep 1
  done
  [ -n "$sid" ] && [ "$sid" != "None" ] || die "no sandbox_id for $sfx"
  # wait applied
  for _ in $(seq 1 "$WAIT_SECONDS"); do
    [ "$(psql_q "SELECT a.state FROM joysafeter_egress_group_generations g JOIN joysafeter_egress_apply_status a ON a.group_key=g.group_key AND a.generation=g.generation WHERE g.desired_policies @> '[{\"sandbox_id\":\"${sid}\"}]'::jsonb ORDER BY g.generation DESC LIMIT 1")" = "applied" ] && break
    sleep 1
  done
  local rtok; rtok="$(docker inspect "joysafeter-${sid}" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^JOYSAFETER_RUNNER_TOKEN=//p' | head -1)"
  [ -n "$rtok" ] || die "no runner token for $sfx sandbox $sid"
  printf '%s %s\n' "$sid" "$rtok"
}

log "Multi-tenant egress isolation — run ${RUN_ID}, API ${API_URL}"
curl -fsS "${API_URL}/api/v1/health/live" >/dev/null 2>&1 || die "API not reachable at ${API_URL}"
EMAIL="iso-${RUN_ID}@example.com"
PHASH="$(python3 -c "import hashlib;print(hashlib.sha256('SmokePass123!'.encode()).hexdigest())")"
curl -sS -X POST "${API_URL}/api/v1/auth/sign-up/email" -H 'Content-Type: application/json' -d "{\"email\":\"$EMAIL\",\"name\":\"Iso\",\"password\":\"$PHASH\"}" >/dev/null
TOKEN="$(curl -sS -X POST "${API_URL}/api/v1/auth/sign-in/email" -H 'Content-Type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$PHASH\"}" | json_get data.access_token)"
[ -n "$TOKEN" ] || die "sign-in failed"

PTOKEN_A="PLATFORM-A-${RUN_ID}"; PTOKEN_B="PLATFORM-B-${RUN_ID}"
log "Seeding sandbox A (secret token ${PTOKEN_A})"
read -r SID_A RTOK_A < <(seed_sandbox A "$PTOKEN_A")
ok "sandbox A = ${SID_A}"
log "Seeding sandbox B (secret token ${PTOKEN_B})"
read -r SID_B RTOK_B < <(seed_sandbox B "$PTOKEN_B")
ok "sandbox B = ${SID_B}"

# --- Scenario 1: each sandbox injects ONLY its own credential ---
log "[1] Distinct-credential injection per sandbox"
RA="$(probe "$SID_A" "$RTOK_A")"; BODY_A="${RA#*$'\t'}"; [ "${RA%%$'\t'*}" = "200" ] || die "[1] sandbox A probe status ${RA%%$'\t'*}"
has "Bearer ${PTOKEN_A}" "$BODY_A" || die "[1] sandbox A did not inject its own credential (${PTOKEN_A})"
has "Bearer ${PTOKEN_B}" "$BODY_A" && die "[1] sandbox A leaked sandbox B's credential"
has "$RTOK_A" "$BODY_A" && die "[1] sandbox A runner token leaked to upstream (not stripped)"
ok "[1] sandbox A injected only ${PTOKEN_A}"
RB="$(probe "$SID_B" "$RTOK_B")"; BODY_B="${RB#*$'\t'}"; [ "${RB%%$'\t'*}" = "200" ] || die "[1] sandbox B probe status ${RB%%$'\t'*}"
has "Bearer ${PTOKEN_B}" "$BODY_B" || die "[1] sandbox B did not inject its own credential (${PTOKEN_B})"
has "Bearer ${PTOKEN_A}" "$BODY_B" && die "[1] sandbox B leaked sandbox A's credential"
ok "[1] sandbox B injected only ${PTOKEN_B}"

# --- Scenario 2: cross-tenant token isolation (stolen token rejected) ---
log "[2] Cross-tenant isolation: sandbox A's token on sandbox B's socket, and vice versa"
X1="$(probe "$SID_B" "$RTOK_A")"; [ "${X1%%$'\t'*}" = "403" ] || die "[2] sandbox A's token on B's socket returned ${X1%%$'\t'*} (expected 403)"
ok "[2] A's runner token DENIED (403) on B's socket"
X2="$(probe "$SID_A" "$RTOK_B")"; [ "${X2%%$'\t'*}" = "403" ] || die "[2] sandbox B's token on A's socket returned ${X2%%$'\t'*} (expected 403)"
ok "[2] B's runner token DENIED (403) on A's socket"

# --- Scenario 3: bogus token denied on both ---
log "[3] Bogus token denied on both sandboxes"
[ "$(probe "$SID_A" "bogus-${RUN_ID}")" ] # ensure runs
[ "$(probe "$SID_A" "bogus-${RUN_ID}" | cut -f1)" = "403" ] || die "[3] bogus token on A not 403"
[ "$(probe "$SID_B" "bogus-${RUN_ID}" | cut -f1)" = "403" ] || die "[3] bogus token on B not 403"
ok "[3] bogus tokens denied (403) on both"

echo
ok "MULTI-TENANT ISOLATION PROVEN: per-sandbox distinct credential injection, cross-tenant token rejection, bogus-token denial — all through real controller-driven Envoy + ext_authz."
echo "  sandbox A=${SID_A} (cred ${PTOKEN_A}); sandbox B=${SID_B} (cred ${PTOKEN_B})"
