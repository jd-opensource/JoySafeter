#!/bin/bash
#
# E2E Agent + Skill Injection Test
#
# Verifies:
#   1. A custom Skill can be created through the API.
#   2. An Agent referencing that Skill carries it into SetupSandbox/StartTask.
#   3. The runner unpacks the Skill under .claude/skills inside the sandbox work dir.
#   4. Claude Code (cc/claude engine) can see and follow the injected Skill instructions.
#
# Usage:
#   JOYSAFETER_URL=http://localhost:8080 ENGINE_KIND=claude \
#     bash scripts/e2e/e2e_agent_skill_injection.sh [API_BASE_OR_BASE_URL] [SECRET_REF] [ENV_REF]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/e2e_helpers.sh"

BASE_URL="${1:-${JOYSAFETER_URL:-http://localhost:8080}}"
SECRET_REF="${2:-$(engine_default_secret)}"
ENV_REF="${3:-unrestricted_env}"

if [[ "$BASE_URL" == */api/v1 || "$BASE_URL" == */api/v2 || "$BASE_URL" == */v1 || "$BASE_URL" == */v2 ]]; then
    API="$BASE_URL"
else
    API="${BASE_URL}/v1"
fi
MODEL_ID=$(engine_model)
API_KEY="${JOYSAFETER_API_KEY:-${API_KEY:-}}"
declare -a CURL_AUTH_ARGS=()
if [ -n "$API_KEY" ]; then
    CURL_AUTH_ARGS=(-H "X-Api-Key: $API_KEY")
fi

call_api() {
    local method="$1"
    local url="$2"
    local body="${3:-}"

    local resp
    if [ -n "$body" ]; then
        resp=$(curl -s -w "\n%{http_code}" -X "$method" "$url" \
            ${CURL_AUTH_ARGS[@]+"${CURL_AUTH_ARGS[@]}"} \
            -H "Content-Type: application/json" -d "$body" || true)
    else
        resp=$(curl -s -w "\n%{http_code}" -X "$method" "$url" \
            ${CURL_AUTH_ARGS[@]+"${CURL_AUTH_ARGS[@]}"} || true)
    fi
    LAST_CODE=$(echo "$resp" | tail -1)
    LAST_BODY=$(echo "$resp" | sed '$d')
}

delete_resource() {
    local TYPE="$1"
    local ID="$2"
    local EXTRA="${3:-}"
    curl -s -X DELETE ${CURL_AUTH_ARGS[@]+"${CURL_AUTH_ARGS[@]}"} "$API/${TYPE}/${ID}${EXTRA}" > /dev/null 2>&1 || true
}

fetch_session_events() {
    curl -sf ${CURL_AUTH_ARGS[@]+"${CURL_AUTH_ARGS[@]}"} "$API/sessions/$1/events?limit=${2:-200}" 2>/dev/null || echo '{}'
}

response_id() {
    python3 -c "
import sys, json
d=json.load(sys.stdin)
if isinstance(d, dict) and isinstance(d.get('data'), dict):
    d=d['data']
print(d.get('id','') if isinstance(d, dict) else '')
"
}

extract_events() {
    python3 -c "
import sys, json
try: r=json.load(sys.stdin)
except Exception: r={}
if isinstance(r, dict) and isinstance(r.get('data'), dict) and isinstance(r['data'].get('data'), list):
    evts=r['data']['data']
elif isinstance(r, dict) and isinstance(r.get('data'), list):
    evts=r['data']
elif isinstance(r, list):
    evts=r
else:
    evts=[]
print(json.dumps(evts))
"
}

wait_for_idle() {
    local SID="$1"
    local EXPECTED_STOP="$2"
    local MAX_WAIT="${3:-40}"
    local INTERVAL="${4:-5}"
    _WAIT_STATUS=""
    _WAIT_EVENT_ID=""

    for _i in $(seq 1 "$MAX_WAIT"); do
        sleep "$INTERVAL"
        local state
        state=$(curl -sf ${CURL_AUTH_ARGS[@]+"${CURL_AUTH_ARGS[@]}"} "$API/sessions/$SID" 2>/dev/null || echo '{}')
        local status stop
        status=$(echo "$state" | python3 -c "import sys,json; d=json.load(sys.stdin); d=d.get('data',d); print(d.get('status',''))" 2>/dev/null || true)
        stop=$(echo "$state" | python3 -c "import sys,json; d=json.load(sys.stdin); d=d.get('data',d); sr=d.get('stop_reason') or {}; print(sr.get('type','') if isinstance(sr,dict) else '')" 2>/dev/null || true)

        if [ "$status" = "idle" ]; then
            if [ "$stop" = "requires_action" ]; then
                _WAIT_STATUS="requires_action"
                _WAIT_EVENT_ID=$(echo "$state" | python3 -c "import sys,json; d=json.load(sys.stdin); d=d.get('data',d); print((d.get('stop_reason') or {}).get('event_ids',[''])[0])" 2>/dev/null || true)
                return 0
            fi
            if [ "$stop" = "$EXPECTED_STOP" ] || [ -z "$stop" ]; then
                local reply
                reply=$(last_reply)
                if [ -n "$reply" ]; then
                    _WAIT_STATUS="$EXPECTED_STOP"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

SKILL_ID=""
AGENT_ID=""
SESSION_ID=""

cleanup() {
    if [ "${KEEP_E2E_RESOURCES:-0}" = "1" ]; then
        echo ""
        echo "=== Cleanup skipped (KEEP_E2E_RESOURCES=1) ==="
        [ -n "$SKILL_ID" ] && echo "Skill:   $SKILL_ID"
        [ -n "$AGENT_ID" ] && echo "Agent:   $AGENT_ID"
        [ -n "$SESSION_ID" ] && echo "Session: $SESSION_ID"
        return
    fi

    echo ""
    echo "=== Cleanup ==="
    [ -n "$SESSION_ID" ] && delete_resource sessions "$SESSION_ID"
    [ -n "$AGENT_ID" ] && delete_resource agents "$AGENT_ID" "?force=true"
    [ -n "$SKILL_ID" ] && delete_resource skills "$SKILL_ID"
    echo "Done."
}
trap cleanup EXIT

send_turn() {
    local msg="$1"
    local max_wait="${2:-40}"
    local escaped
    local sent=false
    escaped=$(printf '%s' "$msg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

    for attempt in $(seq 1 10); do
        call_api POST "$API/sessions/$SESSION_ID/events" \
            "{\"events\":[{\"type\":\"user.message\",\"content\":[{\"type\":\"text\",\"text\":${escaped}}]}]}"
        if [ "$LAST_CODE" = "201" ]; then
            sent=true
            break
        fi
        if [ "$LAST_CODE" = "409" ]; then
            info "Session busy, retrying send in 5s (attempt $attempt)"
            sleep 5
            continue
        fi
        fail "Send message failed: HTTP $LAST_CODE"
        return 1
    done

    if [ "$sent" != "true" ]; then
        fail "Send message failed after retries; last HTTP $LAST_CODE"
        return 1
    fi

    if ! wait_for_idle "$SESSION_ID" "end_turn" "$max_wait" 5; then
        fail "Timed out waiting for session to complete"
        return 1
    fi
    if [ "$_WAIT_STATUS" = "requires_action" ]; then
        auto_approve_until_done "$SESSION_ID" 20 5
    elif [ "$_WAIT_STATUS" != "end_turn" ]; then
        fail "Unexpected wait status: $_WAIT_STATUS"
        return 1
    fi
}

last_reply() {
    local reply=""
    for _r in $(seq 1 8); do
        reply=$(fetch_session_events "$SESSION_ID" 200 | extract_events | python3 -c "
import sys, json
try: evts=json.load(sys.stdin)
except Exception: evts=[]
last_user=-1
for i,e in enumerate(evts):
    if e.get('type')=='user.message': last_user=i
reply=''
if last_user>=0:
    for e in reversed(evts[last_user+1:]):
        if e.get('type')=='agent.message':
            c=e.get('content', [])
            reply = c[0].get('text','') if isinstance(c,list) and c else (c if isinstance(c,str) else '')
            break
print(reply)
" 2>/dev/null || true)
        if [ -n "$reply" ]; then
            echo "$reply"
            return 0
        fi
        sleep 3
    done
    echo "$reply"
}

events_json() {
    fetch_session_events "$SESSION_ID" 200
}

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  E2E Agent + Skill Injection Test                       ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  API:    $API"
echo "  Engine: $ENGINE_KIND"
echo "  Model:  $MODEL_ID"
echo "  Secret: $SECRET_REF"
echo "  Env:    $ENV_REF"
if [ -n "$API_KEY" ]; then
    echo "  Auth:   X-Api-Key (${API_KEY:0:10}...)"
else
    echo "  Auth:   none (set JOYSAFETER_API_KEY or API_KEY if required)"
fi
echo ""

HTTP_CODE=$(curl -sf -o /dev/null -w '%{http_code}' ${CURL_AUTH_ARGS[@]+"${CURL_AUTH_ARGS[@]}"} "$API/health/live" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    pass "JoySafeter reachable"
else
    fail "Cannot reach $API/health/live (HTTP $HTTP_CODE)"
    exit 1
fi

STAMP=$(date +%s)
SKILL_NAME="e2e-skill-injection-$STAMP"
AGENT_NAME="e2e-skill-agent-$STAMP"
MARKER="JOYSAFETER_SKILL_MARKER_$STAMP"

SKILL_MD=$(cat <<EOF
---
name: $SKILL_NAME
description: E2E skill injection verification. When asked for the skill marker, reply with $MARKER exactly.
---

# $SKILL_NAME

If the user asks you to verify skill injection or asks for the skill marker, reply with exactly:

$MARKER

Do not add extra text around the marker.
EOF
)

SKILL_JSON=$(SKILL_NAME="$SKILL_NAME" SKILL_MD="$SKILL_MD" python3 - <<PY
import json, os
skill_name = os.environ["SKILL_NAME"]
skill_md = os.environ["SKILL_MD"]
print(json.dumps({
    "name": skill_name,
    "description": "E2E skill injection verification",
    "content": skill_md,
    "tags": ["e2e", "skill-injection"],
    "files": [{
        "path": "SKILL.md",
        "file_name": "SKILL.md",
        "file_type": "markdown",
        "content": skill_md,
    }],
}))
PY
)

info "Creating skill $SKILL_NAME"
call_api POST "$API/skills" "$SKILL_JSON"
if [ "$LAST_CODE" = "201" ]; then
    SKILL_ID=$(echo "$LAST_BODY" | response_id)
    pass "Skill created: $SKILL_ID"
else
    fail "Skill creation HTTP $LAST_CODE: $LAST_BODY"
    exit 1
fi

info "Creating agent $AGENT_NAME with skill $SKILL_ID"
AGENT_BODY=$(AGENT_NAME="$AGENT_NAME" ENGINE_KIND="$ENGINE_KIND" MODEL_ID="$MODEL_ID" ENV_REF="$ENV_REF" SECRET_REF="$SECRET_REF" SKILL_ID="$SKILL_ID" python3 - <<PY
import json, os
body = {
    "name": os.environ["AGENT_NAME"],
    "engine_kind": os.environ["ENGINE_KIND"],
    "system_prompt": "You are a concise verification agent. Use Bash when asked to inspect the sandbox filesystem. If a loaded skill tells you to emit a marker, follow it exactly.",
    "environment_ref": os.environ["ENV_REF"],
    "secret_ref": os.environ["SECRET_REF"],
    "skills": [{"type": "custom", "skill_id": os.environ["SKILL_ID"], "version": "latest"}],
    "tools": [{
        "type": "agent_toolset_20260401",
        "default_config": {"permission_policy": {"type": "always_allow"}},
        "configs": [{"name": "Bash", "enabled": True}]
    }]
}
model_id = os.environ.get("MODEL_ID", "").strip()
if model_id:
    body["model"] = {"id": model_id}
print(json.dumps(body))
PY
)
call_api POST "$API/agents" "$AGENT_BODY"
if [ "$LAST_CODE" = "201" ]; then
    AGENT_ID=$(echo "$LAST_BODY" | response_id)
    pass "Agent created: $AGENT_ID"
else
    fail "Agent creation HTTP $LAST_CODE: $LAST_BODY"
    exit 1
fi

info "Creating session"
call_api POST "$API/sessions" "{\"agent\":\"$AGENT_ID\",\"environment_id\":\"$ENV_REF\"}"
if [ "$LAST_CODE" = "201" ]; then
    SESSION_ID=$(echo "$LAST_BODY" | response_id)
    pass "Session created: $SESSION_ID"
else
    fail "Session creation HTTP $LAST_CODE: $LAST_BODY"
    exit 1
fi

echo ""
info "Turn 1: verify skill files exist in sandbox"
send_turn "Use Bash to inspect the current working directory. Verify that the file .claude/skills/$SKILL_NAME/SKILL.md exists and contains $MARKER. Reply exactly: SKILL_FILE_OK if it exists and contains the marker; otherwise reply SKILL_FILE_MISSING." 80
REPLY=$(last_reply)
echo "  Agent: $REPLY"
if echo "$REPLY" | grep -q "SKILL_FILE_OK"; then
    pass "Skill archive unpacked into sandbox"
else
    fail "Skill file verification failed"
fi

if events_json | grep -q '"type":"agent.tool_use"\|"type":"agent.mcp_tool_use"\|"type":"agent.custom_tool_use"'; then
    pass "Agent used a tool during sandbox inspection"
else
    warn "No tool_use event detected; the model may have answered without Bash"
fi

echo ""
info "Turn 2: verify Claude Code can follow injected skill instructions"
send_turn "Use the injected skill named $SKILL_NAME. What is the skill marker? Reply with the marker only." 80
REPLY=$(last_reply)
echo "  Agent: $REPLY"
if [ "$REPLY" = "$MARKER" ]; then
    pass "Claude Code followed injected skill instructions"
else
    fail "Expected marker $MARKER, got: $REPLY"
fi

echo ""
print_summary
