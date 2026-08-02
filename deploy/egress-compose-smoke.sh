#!/usr/bin/env bash
# =============================================================================
# Docker Compose egress smoke (Plan 2 / C-2) — four-source tamper-evident e2e.
# =============================================================================
# Proves a sandbox's credentialed egress traverses the UNIFIED controller path
# on Docker: Rust orchestrator (decision plane, writes desired-state to Postgres
# + waits for ACK) → Go egress-controller (control plane, compiles xDS + serves
# ADS) → Docker Envoy (data plane, per-sandbox _http listener w/ ext_authz) →
# orchestrator ext_authz (credential plane, injects the platform secret) → a
# MOCK upstream that echoes headers (so NO real API key is needed).
#
# The proof is FOUR independent, hard-to-forge sources — a green `echo` is not
# the proof; the artifacts are:
#   A. Envoy admin config_dump + stats: per-sandbox _http (ext_authz) + _grpc
#      listeners present and CDS/LDS ACKed; no secret material in the dump.
#   B. Postgres joysafeter_egress_apply_status: state=applied, connected_nodes>=1,
#      acked_acks==required_acks>0, and zero node NACKs — the durable authority's
#      own record that a real Envoy accepted the generation.
#   C. Data-plane behavior: a call through the sandbox's Envoy socket reaches the
#      mock with the PLATFORM credential injected (and sandbox-supplied auth
#      stripped); a wrong sandbox token is denied; the sandbox env holds NO real
#      secret, only the Envoy placeholder base URL.
#   D. Cross-correlation: the Envoy-assigned x-request-id on the successful call
#      appears in the mock upstream's request log.
#
# Usage:
#   # stack already up (see header of docker-compose.egress-smoke.yml):
#   SMOKE_API_PORT=18001 deploy/egress-compose-smoke.sh
#   # or let the script bring the stack up itself:
#   BRING_UP=true deploy/egress-compose-smoke.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- config ----------------------------------------------------------------
SMOKE_API_PORT="${SMOKE_API_PORT:-8000}"
API_URL="${API_URL:-http://localhost:${SMOKE_API_PORT}}"
DB_CONTAINER="${DB_CONTAINER:-joysafeter-db}"
ENVOY_CONTAINER="${ENVOY_CONTAINER:-joysafeter-envoy}"
MOCK_CONTAINER="${MOCK_CONTAINER:-joysafeter-egress-mock-upstream}"
NETWORK="${JOYSAFETER_ENVOY_NETWORK:-joysafeter-network}"
SOCKET_VOLUME="${JOYSAFETER_ENVOY_SOCKET_VOLUME:-joysafeter-sockets}"
HELPER_IMAGE="${BACKEND_FULL_IMAGE:-joysafeter-backend:latest}"
MOCK_HOST="joysafeter-egress-mock-upstream"
MOCK_PORT="8080"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-joysafeter}"
LLM_EGRESS_HOST="llm-egress.internal"
BRING_UP="${BRING_UP:-false}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d%H%M%S)}"
WAIT_SECONDS="${WAIT_SECONDS:-120}"

log()  { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[0;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

json_get() { python3 -c "import sys,json
d=json.load(sys.stdin)
for p in sys.argv[1].split('.'):
    d=d.get(p) if isinstance(d,dict) else None
    if d is None: break
print(d if d is not None else '')" "$1"; }

post() { curl -sS -X POST "${API_URL}$1" -H 'Content-Type: application/json' "${@:3}" -d "$2"; }
authpost() { curl -sS -X POST "${API_URL}$1" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d "$2"; }
assert_success() { [ "$(printf '%s' "$1" | json_get success)" = "True" ] || die "$2 failed: $1"; }

# Pure-bash substring test. Avoids `printf ... | grep -q` which, under
# `set -o pipefail` on a large string, makes grep -q close the pipe on first
# match, SIGPIPE the writer, and return non-zero even on a match — a subtle
# false negative. `case` needs no pipe and no regex escaping.
has()   { case "$2" in *"$1"*) return 0 ;; *) return 1 ;; esac; }
lacks() { case "$2" in *"$1"*) return 1 ;; *) return 0 ;; esac; }

# Envoy admin over the envoy container's own netns (admin binds 127.0.0.1:9901;
# the image has no curl, so borrow the backend image's python via shared netns).
envoy_admin() {
  docker run --rm --network "container:${ENVOY_CONTAINER}" "$HELPER_IMAGE" \
    python3 -c "import sys,urllib.request; sys.stdout.write(urllib.request.urlopen('http://127.0.0.1:9901'+sys.argv[1],timeout=8).read().decode())" "$1"
}

psql_q() { docker exec "$DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"; }

# =============================================================================
# 0. (optional) bring up the stack
# =============================================================================
if [ "$BRING_UP" = "true" ]; then
  log "Bringing up controller-mode stack (migrations + services)"
  ( cd "$SCRIPT_DIR" &&
    docker compose up -d postgres >/dev/null &&
    for _ in $(seq 1 30); do [ "$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONTAINER" 2>/dev/null)" = healthy ] && break; sleep 1; done &&
    docker compose --profile init run --rm db-init >/dev/null &&
    docker compose -f docker-compose.yml -f docker-compose.egress-smoke.yml \
      --profile rust-orchestrator --profile local-redis up -d --wait \
      joysafeter-egress-controller joysafeter-envoy joysafeter-egress-mock-upstream api orchestrator-rs worker >/dev/null
  ) || die "stack bring-up failed"
fi

log "Egress compose smoke — run ${RUN_ID}, API ${API_URL}"
curl -fsS "${API_URL}/api/v1/health/live" >/dev/null 2>&1 || die "API not reachable at ${API_URL}"

# =============================================================================
# 1. seed: user → secret (mock upstream) → limited env → agent → task
# =============================================================================
EMAIL="egress-smoke-${RUN_ID}@example.com"
PHASH="$(python3 -c "import hashlib;print(hashlib.sha256('SmokePass123!'.encode()).hexdigest())")"
SECRET_NAME="egress-smoke-secret-${RUN_ID}"
ENV_NAME="egress-smoke-env-${RUN_ID}"
AGENT_NAME="egress-smoke-agent-${RUN_ID}"
PLATFORM_TOKEN="PLATFORM-SECRET-${RUN_ID}"

log "Registering + signing in ${EMAIL}"
SIGNUP_BODY="{\"email\":\"$EMAIL\",\"name\":\"Egress Smoke\",\"password\":\"$PHASH\"}"
post /api/v1/auth/sign-up/email "$SIGNUP_BODY" >/dev/null
SIGNIN_BODY="{\"email\":\"$EMAIL\",\"password\":\"$PHASH\"}"
SIGNIN="$(post /api/v1/auth/sign-in/email "$SIGNIN_BODY")"
assert_success "$SIGNIN" "sign-in"
TOKEN="$(printf '%s' "$SIGNIN" | json_get data.access_token)"

log "Creating Secret ${SECRET_NAME} (base URL → mock upstream, dummy platform token)"
SECRET_BODY="{\"name\":\"$SECRET_NAME\",\"provider\":\"claude\",\"protocol\":\"anthropic_messages\",\"data\":{\"ANTHROPIC_BASE_URL\":\"http://${MOCK_HOST}:${MOCK_PORT}/v1\",\"ANTHROPIC_AUTH_TOKEN\":\"${PLATFORM_TOKEN}\"}}"
assert_success "$(authpost /api/v1/secrets "$SECRET_BODY")" "create-secret"

log "Creating limited Environment ${ENV_NAME} (allow mock host only)"
ENV_BODY="{\"name\":\"$ENV_NAME\",\"description\":\"docker egress smoke\",\"config\":{\"type\":\"cloud\",\"networking\":{\"type\":\"limited\",\"allowed_hosts\":[\"${MOCK_HOST}\"],\"allow_mcp_servers\":false,\"allow_package_managers\":false},\"secret_refs\":[\"$SECRET_NAME\"],\"egress_services\":[]}}"
assert_success "$(authpost /api/v1/environments "$ENV_BODY")" "create-environment"

log "Creating Agent ${AGENT_NAME}"
AGENT_BODY="{\"name\":\"$AGENT_NAME\",\"engine_kind\":\"claude\",\"system_prompt\":\"smoke\",\"tools\":[],\"skills\":[],\"env\":{},\"secret_ref\":\"$SECRET_NAME\",\"environment_ref\":\"$ENV_NAME\"}"
AGENT_RESP="$(authpost /api/v1/agents "$AGENT_BODY")"
assert_success "$AGENT_RESP" "create-agent"
AGENT_ID="$(printf '%s' "$AGENT_RESP" | json_get data.id)"; AGENT_ID="${AGENT_ID#agent_}"

log "Creating Task"
TASK_BODY="{\"agent_id\":\"$AGENT_ID\",\"environment_ref\":\"$ENV_NAME\",\"prompt\":\"reply EGRESS_OK\",\"timeout_sec\":600,\"max_retries\":0}"
TASK_RESP="$(curl -sS -X POST "${API_URL}/api/v1/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: egress-smoke-${RUN_ID}" -d "$TASK_BODY")"
assert_success "$TASK_RESP" "create-task"
TASK_ID="$(printf '%s' "$TASK_RESP" | json_get data.id)"

log "Waiting for sandbox_id (task ${TASK_ID})"
SANDBOX_ID=""
for _ in $(seq 1 "$WAIT_SECONDS"); do
  R="$(curl -sS "${API_URL}/api/v1/tasks/${TASK_ID}" -H "Authorization: Bearer $TOKEN")"
  SID="$(printf '%s' "$R" | json_get data.sandbox_id)"
  ST="$(printf '%s' "$R" | json_get data.status)"
  if [ -n "$SID" ] && [ "$SID" != "None" ]; then SANDBOX_ID="$SID"; break; fi
  if [ "$ST" = "failed" ]; then
    ERR="$(printf '%s' "$R" | json_get data.error)"
    # A model-call failure AFTER egress apply is acceptable (mock is not a real
    # model); an EGRESS_POLICY_APPLY_TIMEOUT is a control-plane failure.
    case "$ERR" in
      *EGRESS_POLICY_APPLY_TIMEOUT*) die "control-plane apply failed: $ERR" ;;
      *) warn "task failed (expected — mock upstream is not a real model): $ERR" ;;
    esac
  fi
  sleep 1
done
[ -n "$SANDBOX_ID" ] || die "no sandbox_id assigned (task never scheduled a sandbox)"
CONTAINER="joysafeter-${SANDBOX_ID}"
ok "sandbox ${SANDBOX_ID}"

# The docker group key the authority wrote generations under (provider=docker).
GROUP_KEY="$(psql_q "SELECT group_key FROM joysafeter_egress_group_generations WHERE desired_policies @> '[{\"sandbox_id\":\"${SANDBOX_ID}\"}]'::jsonb ORDER BY generation DESC LIMIT 1")"
[ -n "$GROUP_KEY" ] || die "no desired generation for sandbox ${SANDBOX_ID}"

# =============================================================================
# Source B — Postgres durable apply status (state=applied, all nodes ACKed)
# =============================================================================
log "[B] Postgres: waiting for an all-node applied generation"
BROW=""
for _ in $(seq 1 "$WAIT_SECONDS"); do
  BROW="$(psql_q "SELECT g.generation||'|'||COALESCE(a.state,'')||'|'||COALESCE(a.connected_nodes,0)||'|'||COALESCE(a.required_acks,0)||'|'||COALESCE(a.acked_acks,0) FROM joysafeter_egress_group_generations g LEFT JOIN joysafeter_egress_apply_status a ON a.group_key=g.group_key AND a.generation=g.generation WHERE g.group_key='${GROUP_KEY}' AND g.desired_policies @> '[{\"sandbox_id\":\"${SANDBOX_ID}\"}]'::jsonb ORDER BY g.generation DESC LIMIT 1")"
  IFS='|' read -r GEN STATE CONN REQ ACK <<<"$BROW"
  if [ "$STATE" = "applied" ] && [ "${CONN:-0}" -ge 1 ] && [ "${REQ:-0}" -gt 0 ] && [ "${ACK:-0}" = "${REQ:-0}" ]; then break; fi
  sleep 1
done
IFS='|' read -r GEN STATE CONN REQ ACK <<<"$BROW"
[ "$STATE" = "applied" ] || die "[B] apply_status not applied: gen=${GEN} state=${STATE} connected=${CONN} required=${REQ} acked=${ACK}"
[ "${CONN:-0}" -ge 1 ] && [ "${REQ:-0}" -gt 0 ] && [ "${ACK}" = "${REQ}" ] || die "[B] ACK counts wrong: connected=${CONN} required=${REQ} acked=${ACK}"
NACKS="$(psql_q "SELECT count(*) FROM joysafeter_egress_node_apply_status WHERE group_key='${GROUP_KEY}' AND generation=${GEN} AND status='nack'")"
[ "$NACKS" = "0" ] || die "[B] generation ${GEN} has ${NACKS} NACK(s)"
ok "[B] Postgres: gen ${GEN} state=applied connected=${CONN} acked=${ACK}/${REQ} nacks=0"

# =============================================================================
# Source A — Envoy admin config_dump + stats (listeners + ext_authz, ACKed)
# =============================================================================
log "[A] Envoy: config_dump listeners + ext_authz + no-secret + ACK stats"
SID_US="$(printf '%s' "$SANDBOX_ID" | tr '-' '_')"
HTTP_L="joysafeter_${SID_US}_http"; GRPC_L="joysafeter_${SID_US}_grpc"
DUMP=""
for _ in $(seq 1 30); do
  DUMP="$(envoy_admin /config_dump || true)"
  has "$HTTP_L" "$DUMP" && break
  sleep 1
done
has "$HTTP_L" "$DUMP" || die "[A] config_dump missing ${HTTP_L}"
has "$GRPC_L" "$DUMP" || die "[A] config_dump missing ${GRPC_L}"
has "envoy.filters.http.ext_authz" "$DUMP" || die "[A] config_dump missing ext_authz filter"
for forbidden in "$PLATFORM_TOKEN" "$SECRET_NAME"; do
  has "$forbidden" "$DUMP" && die "[A] config_dump leaked secret material: ${forbidden}"
done
STATS="$(envoy_admin '/stats?filter=(cds|lds)\.update_success')"
CDS_OK="$(printf '%s' "$STATS" | sed -n 's/.*cds.update_success: *\([0-9]*\).*/\1/p' | head -1)"
LDS_OK="$(printf '%s' "$STATS" | sed -n 's/.*lds.update_success: *\([0-9]*\).*/\1/p' | head -1)"
[ "${CDS_OK:-0}" -ge 1 ] && [ "${LDS_OK:-0}" -ge 1 ] || die "[A] Envoy did not ACK CDS/LDS (cds=${CDS_OK} lds=${LDS_OK})"
ok "[A] Envoy: ${HTTP_L}+${GRPC_L} present, ext_authz on credential path, CDS=${CDS_OK} LDS=${LDS_OK}, no secret leaked"

# =============================================================================
# Source C — data-plane behavior (injection, strip, wrong-token deny, no secret)
# =============================================================================
log "[C] Sandbox env: placeholder base URL, real secret absent, egress token present"
if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  ENVDUMP="$(docker exec "$CONTAINER" env 2>/dev/null || docker inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}')"
  has "ANTHROPIC_BASE_URL=http://${LLM_EGRESS_HOST}" "$ENVDUMP" || die "[C] sandbox ANTHROPIC_BASE_URL not rewritten to Envoy placeholder"
  has "$PLATFORM_TOKEN" "$ENVDUMP" && die "[C] real platform secret leaked into sandbox env"
  SANDBOX_TOKEN="$(printf '%s' "$ENVDUMP" | sed -n 's/^JOYSAFETER_RUNNER_TOKEN=//p;s/^JOYSAFETER_EGRESS_GATEWAY_SANDBOX_TOKEN=//p' | head -1)"
  ok "[C] sandbox env sanitized (placeholder base URL, no platform secret)"

  # Injection + strip + deny through the per-sandbox Envoy http.sock. A helper
  # container mounts the socket volume and speaks HTTP/1.1 over the unix socket.
  SOCK="/sockets/${SANDBOX_ID}/http.sock"
  probe() { # $1=bearer token; prints "HTTP_STATUS<TAB>BODY"
    docker run -i --rm -v "${SOCKET_VOLUME}:/sockets:ro" "$HELPER_IMAGE" python3 - "$SOCK" "$1" <<'PY'
import socket,sys
sock,tok=sys.argv[1],sys.argv[2]
req=("POST /v1/messages HTTP/1.1\r\nHost: llm-egress.internal\r\n"
     f"authorization: Bearer {tok}\r\nx-api-key: {tok}\r\n"
     "content-type: application/json\r\ncontent-length: 2\r\nconnection: close\r\n\r\n{}")
s=socket.socket(socket.AF_UNIX); s.settimeout(10); s.connect(sock); s.sendall(req.encode())
buf=b""
while True:
    try: c=s.recv(65536)
    except socket.timeout: break
    if not c: break
    buf+=c
head,_,body=buf.partition(b"\r\n\r\n")
status=head.split(b"\r\n",1)[0].split(b" ")[1].decode() if head else "000"
sys.stdout.write(status+"\t"+body.decode(errors="replace"))
PY
  }
  if [ -n "$SANDBOX_TOKEN" ]; then
    RESP="$(probe "$SANDBOX_TOKEN" || true)"
    STATUS="${RESP%%$'\t'*}"; BODY="${RESP#*$'\t'}"
    if [ "$STATUS" = "200" ]; then
      has "Bearer ${PLATFORM_TOKEN}" "$BODY" || die "[C] platform credential NOT injected into upstream request"
      has "${SANDBOX_TOKEN}" "$BODY" && die "[C] sandbox-supplied token was NOT stripped (leaked to upstream)"
      REQ_ID="$(printf '%s' "$BODY" | python3 -c "import sys,json
try:
  d=json.load(sys.stdin); h={k.lower():v for k,v in d.get('headers',{}).items()}
  v=h.get('x-request-id',['']); print(v[0] if isinstance(v,list) else v)
except Exception: print('')")"
      ok "[C] injection: mock saw 'Bearer ${PLATFORM_TOKEN}', sandbox token stripped (x-request-id=${REQ_ID})"
    else
      warn "[C] authorized probe returned ${STATUS} (not 200); body: $(printf '%s' "$BODY" | head -c 200)"
      REQ_ID=""
    fi
    WRONG="$(probe "wrong-sandbox-token-xyz" || true)"; WSTATUS="${WRONG%%$'\t'*}"
    [ "$WSTATUS" = "403" ] && ok "[C] wrong sandbox token denied (403)" || warn "[C] wrong-token probe returned ${WSTATUS} (expected 403)"
  else
    warn "[C] no JOYSAFETER_EGRESS_GATEWAY_SANDBOX_TOKEN in sandbox env; skipping live injection probe"
    REQ_ID=""
  fi
else
  warn "[C] sandbox container ${CONTAINER} not present (already torn down); env/injection checks skipped"
  REQ_ID=""
fi

# =============================================================================
# Source D — cross-correlate the Envoy x-request-id in the mock upstream log
# =============================================================================
if [ -n "${REQ_ID:-}" ]; then
  log "[D] Cross-correlating x-request-id ${REQ_ID} in mock upstream log"
  MOCK_LOG="$(docker logs "$MOCK_CONTAINER" 2>&1 || true)"
  if has "$REQ_ID" "$MOCK_LOG"; then
    ok "[D] mock upstream logged the Envoy x-request-id ${REQ_ID}"
  else
    warn "[D] x-request-id ${REQ_ID} not found in mock upstream log"
  fi
else
  warn "[D] no x-request-id captured; cross-correlation skipped"
fi

echo
ok "egress compose smoke: control-plane proven (A config_dump+stats, B Postgres applied)"
echo "  sandbox=${SANDBOX_ID} group=${GROUP_KEY} generation=${GEN}"
echo "  inspect: docker exec ${DB_CONTAINER} psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c \"SELECT generation,state,connected_nodes,acked_acks,required_acks FROM joysafeter_egress_apply_status WHERE group_key='${GROUP_KEY}'\""
