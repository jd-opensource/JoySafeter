#!/bin/bash
#
# E2E Session Multi-Turn Test
#
# Tests that multiple tasks within a single session preserve
# conversation context across turns (harness session continuity).
#
# Steps:
#   0. Health check
#   1. Create agent (always_allow)
#   2. Create session
#   3. Turn 1: Introduce name → verify acknowledgement
#   4. Turn 2: Math question → verify answer
#   5. Turn 3: Recall name → verify context retention (KEY TEST)
#   6. Turn 4: Count messages → verify conversation awareness
#   7. Turn 5: Code generation → verify sandbox still works
#   8. Summary: event timeline + token usage
#   9. Cleanup
#
# Usage:
#   ./scripts/e2e_session_multiturn.sh [BASE_URL] [SECRET_REF] [ENV_REF]
#
# Examples:
#   ./scripts/e2e_session_multiturn.sh
#   ./scripts/e2e_session_multiturn.sh http://jagents.jd.com deepseekv4pro_secret unrestricted
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/e2e_helpers.sh"

BASE_URL="${1:-${JOYSAFETER_URL:-http://localhost:8080}}"
SECRET_REF="${2:-$(engine_default_secret)}"
ENV_REF="${3:-unrestricted_env}"

API="${BASE_URL}/v1"
MODEL_ID=$(engine_model)
MODEL_JSON=''
if [ -n "$MODEL_ID" ]; then
    MODEL_JSON=",\n    \"model\": {\"id\": \"$MODEL_ID\"}"
fi

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
echo "║  E2E Session Multi-Turn Test                             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  API:         $API"
echo "  Engine:      $ENGINE_KIND"
echo "  Model:       $MODEL_ID"
echo "  Secret:      $SECRET_REF"
echo "  Environment: $ENV_REF"
echo ""

# Helper: send a message to the session and wait for completion.
# Returns the agent's text reply in $_TURN_REPLY.
send_turn() {
    local msg="$1"
    local label="$2"
    local max_wait="${3:-40}"

    local escaped
    escaped=$(printf '%s' "$msg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

    # Retry loop for 409 (session temporarily running from post-reply tool calls)
    local send_ok=false
    for attempt in $(seq 1 10); do
        call_api POST "$API/sessions/$SESSION_ID/events" \
            "{\"events\":[{\"type\":\"user.message\",\"content\":[{\"type\":\"text\",\"text\":${escaped}}]}]}"

        if [ "$LAST_CODE" = "201" ]; then
            send_ok=true
            break
        elif [ "$LAST_CODE" = "409" ]; then
            echo -e "${CYAN}    [attempt $attempt] 409 — session busy, retrying in 5s...${NC}"
            sleep 5
        else
            fail "$label: send message HTTP $LAST_CODE"
            _TURN_REPLY=""
            return 1
        fi
    done

    if [ "$send_ok" != "true" ]; then
        fail "$label: send message failed after 10 retries (409)"
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
# STEP 1: Create Agent
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 1: Create Agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

AGENT_NAME="e2e-multiturn-$(date +%s)"

# Create environment
ENV_NAME="e2e-multiturn-env-$(date +%s)"
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

# Create agent with always_allow so it can work without HITL
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_NAME\",
    \"engine_kind\": \"$ENGINE_KIND\"${MODEL_JSON},
    \"system_prompt\": \"You are a helpful assistant. Follow instructions precisely. Be concise. When asked to recall information from earlier in the conversation, do so accurately. Do not use auto-memory. Do not write memory files or create notes about the conversation. Only use tools when the user explicitly asks you to run a command.\",
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
# STEP 3: Turn 1 — Introduce name
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 3: Turn 1 — Introduce name"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

send_turn "My name is Alice. Remember it. Reply with just: Got it." "Turn 1" 60
info "User:  My name is Alice. Remember it."
info "Agent: $_TURN_REPLY"

if echo "$_TURN_REPLY" | grep -qi "got it"; then
    pass "Turn 1: Agent acknowledged name"
else
    warn "Turn 1: Expected 'Got it', got: ${_TURN_REPLY:0:100}"
fi

# ══════════════════════════════════════════════════════════════
# STEP 4: Turn 2 — Math question
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 4: Turn 2 — Math question"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

send_turn "What is 15 * 7? Reply with just the number, nothing else." "Turn 2"
info "User:  What is 15 * 7?"
info "Agent: $_TURN_REPLY"

if echo "$_TURN_REPLY" | grep -q "105"; then
    pass "Turn 2: Correct answer (105)"
else
    warn "Turn 2: Expected '105', got: ${_TURN_REPLY:0:100}"
fi

# ══════════════════════════════════════════════════════════════
# STEP 5: Turn 3 — Recall name (KEY CONTEXT TEST)
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 5: Turn 3 — Recall name (CONTEXT RETENTION)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

send_turn "What is my name? Reply with just the name, nothing else." "Turn 3"
info "User:  What is my name?"
info "Agent: $_TURN_REPLY"

if echo "$_TURN_REPLY" | grep -qi "alice"; then
    pass "Turn 3: Context retained — agent remembers 'Alice'"
else
    fail "Turn 3: Context LOST — expected 'Alice', got: ${_TURN_REPLY:0:100}"
fi

# ══════════════════════════════════════════════════════════════
# STEP 6: Turn 4 — Conversation awareness
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 6: Turn 4 — Conversation awareness"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

send_turn "How many messages have I sent you so far in this conversation? Count all my messages including this one. Reply with just the number." "Turn 4"
info "User:  How many messages have I sent?"
info "Agent: $_TURN_REPLY"

if echo "$_TURN_REPLY" | grep -qE "[3-5]"; then
    pass "Turn 4: Agent is aware of conversation history"
else
    warn "Turn 4: Expected 3-5, got: ${_TURN_REPLY:0:100}"
fi

# ══════════════════════════════════════════════════════════════
# STEP 7: Turn 5 — Code generation
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 7: Turn 5 — Code generation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

send_turn "Write a Python function called greet that takes a name parameter and returns 'Hello, {name}!'. Show only the code, no explanation." "Turn 5"
info "User:  Write a greet function"
info "Agent: ${_TURN_REPLY:0:200}"

if echo "$_TURN_REPLY" | grep -q "def greet"; then
    pass "Turn 5: Code generation works"
else
    warn "Turn 5: Expected 'def greet', got: ${_TURN_REPLY:0:200}"
fi

if echo "$_TURN_REPLY" | grep -qi "alice"; then
    info "Turn 5: Agent referenced Alice in code context (bonus)"
fi

# ══════════════════════════════════════════════════════════════
# STEP 8: Summary
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 8: Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "  Event timeline:"
print_events "$SESSION_ID"

echo ""

# Count events
USER_MSGS=$(count_events "$SESSION_ID" "user.message")
AGENT_MSGS=$(count_events "$SESSION_ID" "agent.message")
RUNNING_EVTS=$(count_events "$SESSION_ID" "session.status_running")
IDLE_EVTS=$(count_events "$SESSION_ID" "session.status_idle")

echo "  Event counts:"
echo "    user.message:          $USER_MSGS"
echo "    agent.message:         $AGENT_MSGS"
echo "    session.status_running: $RUNNING_EVTS"
echo "    session.status_idle:    $IDLE_EVTS"
echo ""

if [ "$USER_MSGS" -ge 5 ]; then
    pass "All 5 user messages recorded"
else
    fail "Expected 5 user.message events, got $USER_MSGS"
fi

if [ "$AGENT_MSGS" -ge 5 ]; then
    pass "All 5 agent replies recorded"
else
    warn "Expected 5 agent.message events, got $AGENT_MSGS"
fi

# Token usage
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
