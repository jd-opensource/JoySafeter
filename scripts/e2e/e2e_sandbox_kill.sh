#!/bin/bash
#
# E2E Sandbox Kill & Session Recovery Test
#
# Verifies that destroying a sandbox container mid-session does NOT
# lose conversation context.  The session's history lives in PostgreSQL,
# so a new sandbox should be provisioned automatically on the next turn
# and the agent should recall everything from earlier turns.
#
# Steps:
#   0. Health check
#   1. Create environment + agent
#   2. Create session
#   3. Turn 1: Introduce name + secret code → verify acknowledgement
#   4. Find & kill the sandbox container (docker kill)
#   5. Turn 2: Recall name + secret code → verify context survived
#   6. Turn 3: Run bash in new sandbox → verify sandbox works
#   7. Summary: event timeline + token usage
#   8. Cleanup
#
# Usage:
#   ./scripts/e2e_sandbox_kill.sh [BASE_URL] [SECRET_REF] [ENV_REF]
#
# Examples:
#   ./scripts/e2e_sandbox_kill.sh
#   ./scripts/e2e_sandbox_kill.sh http://localhost:8080 deepseekv4-pro-secret unrestricted_env
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/e2e_helpers.sh"

BASE_URL="${1:-${JOYSAFETER_URL:-http://localhost:8080}}"
SECRET_REF="${2:-$(engine_default_secret)}"
ENV_REF="${3:-unrestricted_env}"

API="${BASE_URL}/v1"
MODEL_ID=$(engine_model)

AGENT_ID=""
SESSION_ID=""
ENV_ID=""

cleanup() {
    echo ""
    echo "=== Cleanup ==="
    [ -n "$SESSION_ID" ] && delete_resource sessions "$SESSION_ID"
    [ -n "$AGENT_ID" ]   && delete_resource agents "$AGENT_ID" "?force=true"
    [ -n "$ENV_ID" ]     && delete_resource environments "$ENV_ID"
    echo "Done."
}
trap cleanup EXIT

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  E2E Sandbox Kill & Session Recovery Test                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  API:         $API"
echo "  Engine:      $ENGINE_KIND"
echo "  Model:       $MODEL_ID"
echo "  Secret:      $SECRET_REF"
echo "  Environment: $ENV_REF"
echo ""

# Helper: send a message and wait for completion.
# Sets $_TURN_REPLY to the agent's text reply.
send_turn() {
    local msg="$1"
    local label="$2"
    local max_wait="${3:-30}"

    local escaped
    escaped=$(printf '%s' "$msg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

    call_api POST "$API/sessions/$SESSION_ID/events" \
        "{\"events\":[{\"type\":\"user.message\",\"content\":[{\"type\":\"text\",\"text\":${escaped}}]}]}"

    if [ "$LAST_CODE" != "201" ]; then
        fail "$label: send message HTTP $LAST_CODE"
        _TURN_REPLY=""
        return 1
    fi

    wait_for_idle "$SESSION_ID" "end_turn" "$max_wait" 5
    local status="$_WAIT_STATUS"

    if [ "$status" = "requires_action" ]; then
        info "$label: requires_action — auto-approving"
        auto_approve_until_done "$SESSION_ID" 20 5
    elif [ "$status" != "end_turn" ]; then
        fail "$label: unexpected status '$status'"
        _TURN_REPLY=""
        return 1
    fi

    _TURN_REPLY=$(get_last_agent_reply "$SESSION_ID" 8 3)
}

# ══════════════════════════════════════════════════════════════
# STEP 0: Health Check
# ══════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 0: Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

HTTP_CODE=$(curl -sf -o /dev/null -w '%{http_code}' "$API/health/live" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    pass "JoySafeter reachable (HTTP $HTTP_CODE)"
else
    fail "Cannot reach $API/health/live (HTTP $HTTP_CODE)"
    exit 1
fi

# ══════════════════════════════════════════════════════════════
# STEP 1: Create Environment + Agent
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 1: Create Environment + Agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ENV_NAME="e2e-sbkill-env-$(date +%s)"
call_api POST "$API/environments" "{
    \"name\": \"$ENV_NAME\",
    \"config\": {
        \"type\": \"cloud\",
        \"networking\": {\"type\": \"unrestricted\"}
    }
}"
if [ "$LAST_CODE" = "201" ]; then
    ENV_ID=$(echo "$LAST_BODY" | json_get "['id']")
    pass "Environment created: $ENV_NAME"
else
    fail "Environment creation: HTTP $LAST_CODE"
    exit 1
fi

AGENT_NAME="e2e-sbkill-$(date +%s)"
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_NAME\",
    \"engine_kind\": \"$ENGINE_KIND\",
    \"model\": {\"id\": \"$MODEL_ID\"},
    \"system_prompt\": \"You are a helpful assistant. Be concise. When asked to recall information from earlier in the conversation, do so accurately. Do not use auto-memory. Do not write memory files or create notes about the conversation. Only use tools when the user explicitly asks you to run a command.\",
    \"environment_ref\": \"$ENV_NAME\",
    \"secret_ref\": \"$SECRET_REF\",
    \"tools\": [{
        \"type\": \"agent_toolset_20260401\",
        \"default_config\": {\"permission_policy\": {\"type\": \"always_allow\"}},
        \"configs\": [{\"name\": \"Bash\", \"enabled\": true}]
    }]
}"
if [ "$LAST_CODE" = "201" ]; then
    AGENT_ID=$(echo "$LAST_BODY" | json_get "['id']")
    pass "Agent created: $AGENT_NAME"
    info "Agent ID: $AGENT_ID"
else
    fail "Agent creation: HTTP $LAST_CODE"
    exit 1
fi

# ══════════════════════════════════════════════════════════════
# STEP 2: Create Session
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 2: Create Session"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

call_api POST "$API/sessions" "{\"agent\":\"$AGENT_ID\",\"environment_id\":\"$ENV_ID\"}"
if [ "$LAST_CODE" = "201" ]; then
    SESSION_ID=$(echo "$LAST_BODY" | json_get "['id']")
    SESSION_STATUS=$(echo "$LAST_BODY" | json_get "['status']")
    pass "Session created"
    info "Session ID: $SESSION_ID"
    if [ "$SESSION_STATUS" = "idle" ]; then
        pass "Initial status: idle"
    else
        warn "Initial status: $SESSION_STATUS"
    fi
else
    fail "Session creation: HTTP $LAST_CODE"
    exit 1
fi

# ══════════════════════════════════════════════════════════════
# STEP 3: Turn 1 — Introduce name + secret code
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 3: Turn 1 — Introduce name + secret code"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

send_turn "My name is Hector. The secret code is QUANTUM-42. Remember both. Reply with just: Got it, Hector." "Turn 1" 60
info "User:  My name is Hector. The secret code is QUANTUM-42."
info "Agent: $_TURN_REPLY"

if echo "$_TURN_REPLY" | grep -qi "got it\|hector"; then
    pass "Turn 1: Agent acknowledged name and secret code"
else
    warn "Turn 1: Expected 'Got it', got: ${_TURN_REPLY:0:100}"
fi

# ══════════════════════════════════════════════════════════════
# STEP 4: Find & kill sandbox container
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 4: Find & kill sandbox container"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Strategy: after Turn 1 completes, the sandbox container is still alive
# (JoySafeter keeps it for reuse).  We find and kill it while the session
# is idle — no in-flight task to confuse the event stream.
# Then Turn 2 forces JoySafeter to provision a NEW sandbox.

# First, find the sandbox that was used by Turn 1
info "Searching for sandbox container from Turn 1..."
SANDBOX_CID=""
for attempt in $(seq 1 10); do
    SANDBOX_CID=$(docker ps --filter "label=joysafeter=true" --format '{{.ID}}' 2>/dev/null | head -1)
    if [ -n "$SANDBOX_CID" ]; then
        break
    fi
    sleep 2
done

echo ""
SANDBOX_LIST=$(docker ps --filter "label=joysafeter=true" --format '    {{.ID}}  {{.Image}}  {{.Names}}  {{.Status}}' 2>/dev/null || echo "")
if [ -n "$SANDBOX_LIST" ]; then
    echo "  JoySafeter sandbox containers:"
    echo "$SANDBOX_LIST"
else
    echo "  (no joysafeter-labeled containers found)"
fi
echo ""

if [ -z "$SANDBOX_CID" ]; then
    warn "No sandbox container found — cannot test kill scenario"
    info "Full docker ps:"
    docker ps --format '    {{.ID}}  {{.Image}}  {{.Names}}  {{.Status}}' 2>/dev/null
else
    SANDBOX_IMAGE=$(docker inspect "$SANDBOX_CID" --format '{{.Config.Image}}' 2>/dev/null || echo "?")
    SANDBOX_CNAME=$(docker inspect "$SANDBOX_CID" --format '{{.Name}}' 2>/dev/null || echo "?")
    info "Found sandbox container:"
    info "  ID:    $SANDBOX_CID"
    info "  Image: $SANDBOX_IMAGE"
    info "  Name:  $SANDBOX_CNAME"
    echo ""

    echo -e "  ${RED}>>> docker kill $SANDBOX_CID <<<${NC}"
    docker kill "$SANDBOX_CID" 2>&1 | sed 's/^/    /'
    pass "Sandbox container killed"
    echo ""

    # Verify container is gone
    if docker ps --format '{{.ID}}' 2>/dev/null | grep -q "$SANDBOX_CID"; then
        warn "Container still running after kill"
    else
        info "Container confirmed dead"
    fi
fi

# Give JoySafeter time to detect sandbox death and settle the session
info "Waiting for JoySafeter to detect sandbox death..."
sleep 5

# Wait until session is idle before sending next turn
for _i in $(seq 1 20); do
    SESS_STATE=$(curl -s "$API/sessions/$SESSION_ID" 2>/dev/null || echo '{}')
    SESS_STATUS=$(echo "$SESS_STATE" | json_get "['status']" 2>/dev/null || echo "?")
    if [ "$SESS_STATUS" = "idle" ]; then
        break
    fi
    sleep 3
done
info "Session status after sandbox kill: $SESS_STATUS"

# ══════════════════════════════════════════════════════════════
# STEP 5: Turn 2 — Context recovery (KEY TEST)
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 5: Turn 2 — Context recovery (KEY TEST)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

send_turn "What is my name and what is the secret code I told you earlier? Reply in format: Name: X, Code: Y" "Turn 2 (context recall)" 60
info "User:  What is my name and secret code?"
info "Agent: $_TURN_REPLY"

HAS_NAME=0
HAS_CODE=0
echo "$_TURN_REPLY" | grep -qi "hector" && HAS_NAME=1
echo "$_TURN_REPLY" | grep -q "QUANTUM-42" && HAS_CODE=1

if [ $HAS_NAME -eq 1 ] && [ $HAS_CODE -eq 1 ]; then
    pass "Turn 2: Context SURVIVED sandbox kill — name (Hector) + code (QUANTUM-42)"
elif [ $HAS_NAME -eq 1 ] || [ $HAS_CODE -eq 1 ]; then
    warn "Turn 2: Partial context — name=$HAS_NAME code=$HAS_CODE"
else
    fail "Turn 2: Context LOST after sandbox kill"
fi

# ══════════════════════════════════════════════════════════════
# STEP 6: Turn 3 — Verify new sandbox works
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 6: Turn 3 — Verify new sandbox works"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

send_turn "Run: echo NEW_SANDBOX_OK && hostname && pwd" "Turn 3 (new sandbox)" 60
info "User:  Run echo NEW_SANDBOX_OK && hostname && pwd"
info "Agent: ${_TURN_REPLY:0:300}"

if echo "$_TURN_REPLY" | grep -q "NEW_SANDBOX_OK\|sandbox.*working\|hostname"; then
    pass "Turn 3: New sandbox provisioned and working"
else
    warn "Turn 3: Sandbox command may not have executed"
fi

# ══════════════════════════════════════════════════════════════
# STEP 7: Summary
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 7: Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "  Event timeline:"
print_events "$SESSION_ID"

echo ""

USER_MSGS=$(count_events "$SESSION_ID" "user.message")
AGENT_MSGS=$(count_events "$SESSION_ID" "agent.message")
echo "  Event counts:"
echo "    user.message:  $USER_MSGS"
echo "    agent.message: $AGENT_MSGS"

echo ""
FINAL_SESSION=$(curl -s "$API/sessions/$SESSION_ID" 2>/dev/null)
USAGE=$(echo "$FINAL_SESSION" | python3 -c "
import sys, json
s = json.load(sys.stdin)
u = s.get('usage', {})
print(f\"input={u.get('input_tokens',0)} output={u.get('output_tokens',0)}\")
" 2>/dev/null || echo "unknown")
info "Session usage: $USAGE"

# ══════════════════════════════════════════════════════════════
# Final result
# ══════════════════════════════════════════════════════════════
print_summary

exit $FAILED
