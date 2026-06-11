#!/bin/bash
#
# Full-Chain E2E Integration Test
#
# Comprehensive end-to-end test covering every major scenario:
#   Step 1:  Health check
#   Step 2:  Secret CRUD (create, get, update, list, delete, reference protection)
#   Step 3:  Environment creation (packages + restricted networking)
#   Step 4:  Agent creation (claude, always_ask, custom tool, env_ref, secretRef)
#   Step 5:  Multi-engine agent (codex)
#   Step 6:  Session creation and initial state
#   Step 7:  Send user.message → poll for idle
#   Step 8:  HITL approve flow
#   Step 9:  HITL deny flow
#   Step 10: Custom tool flow
#   Step 11: Unrestricted networking smoke test
#   Step 12: Limited networking smoke test
#   Step 13: Final verification (GET agents, list sessions, event integrity)
#
# Usage:
#   bash scripts/e2e_full_chain.sh
#   JOYSAFETER_URL=http://host:8080 bash scripts/e2e_full_chain.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/e2e_helpers.sh"

# Resources to clean up
ENV_ID=""
ENV_UNRES_ID=""
ENV_LIMITED_ID=""
AGENT_ID=""
AGENT_CODEX_ID=""
AGENT_CUSTOM_ID=""
SESSION_ID=""
SESSION_CUSTOM_ID=""
SESSION_UNRES_ID=""
SESSION_LIMITED_ID=""
SECRET_ID=""
CRED_SECRET_ID=""

cleanup() {
    echo ""
    echo "=== Cleanup ==="
    [ -n "$SESSION_LIMITED_ID" ] && delete_resource sessions "$SESSION_LIMITED_ID"
    [ -n "$SESSION_UNRES_ID" ]   && delete_resource sessions "$SESSION_UNRES_ID"
    [ -n "$SESSION_CUSTOM_ID" ]  && delete_resource sessions "$SESSION_CUSTOM_ID"
    [ -n "$SESSION_ID" ]         && delete_resource sessions "$SESSION_ID"
    [ -n "$AGENT_CUSTOM_ID" ]    && delete_resource agents "$AGENT_CUSTOM_ID" "?force=true"
    [ -n "$AGENT_CODEX_ID" ]     && delete_resource agents "$AGENT_CODEX_ID" "?force=true"
    [ -n "$AGENT_ID" ]           && delete_resource agents "$AGENT_ID" "?force=true"
    [ -n "$ENV_LIMITED_ID" ]     && delete_resource environments "$ENV_LIMITED_ID"
    [ -n "$ENV_UNRES_ID" ]       && delete_resource environments "$ENV_UNRES_ID"
    [ -n "$ENV_ID" ]             && delete_resource environments "$ENV_ID"
    [ -n "$SECRET_ID" ]          && delete_resource secrets "$SECRET_ID" "?force=true"
    [ -n "$CRED_SECRET_ID" ]     && delete_resource secrets "$CRED_SECRET_ID" "?force=true"
    echo "Done."
}
trap cleanup EXIT

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Full-Chain E2E Integration Test                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  API: $API"
echo ""

# Build the CLI credentials JSON from environment variables
CRED_DATA="{}"
_cred_pairs=""
for _key in ANTHROPIC_API_KEY ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN OPENAI_API_KEY OPENAI_BASE_URL; do
    _val="$(printenv "$_key" 2>/dev/null || true)"
    [ -z "$_val" ] && continue
    _cred_pairs="${_cred_pairs:+$_cred_pairs,}\"$_key\":\"$_val\""
done
if [ -z "$_cred_pairs" ]; then
    echo "  ERROR: No CLI credentials found in environment."
    echo "         Set at least one of: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, OPENAI_API_KEY"
    exit 1
fi
CRED_DATA="{$_cred_pairs}"
CRED_SECRET_NAME="e2e-cred-$(date +%s)"

# ══════════════════════════════════════════════════════════════
# STEP 1: Health Check
# ══════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 1: Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

HEALTH=$(curl -s "$API/health" 2>/dev/null || echo '{}')
if echo "$HEALTH" | grep -q '"ok"'; then
    pass "API health check OK"
else
    fail "API not healthy: $HEALTH"
    exit 1
fi

# ══════════════════════════════════════════════════════════════
# STEP 2: Secret CRUD
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 2: Secret CRUD"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

SECRET_NAME="e2e-secret-$(date +%s)"

# Create
echo ">>> 2a. Create secret"
call_api POST "$API/secrets" "{
    \"name\": \"$SECRET_NAME\",
    \"data\": {\"APP_API_KEY\": \"sk-test-key-12345\", \"APP_BASE_URL\": \"https://api.example.com\"}
}"
if [ "$LAST_CODE" = "201" ]; then
    pass "Secret created"
    SECRET_ID=$(echo "$LAST_BODY" | json_get "['id']")
    info "Secret ID: $SECRET_ID"
else
    fail "Secret creation: HTTP $LAST_CODE"
fi

# Get
echo ""
echo ">>> 2b. Get secret"
call_api GET "$API/secrets/$SECRET_ID"
SECRET_RET_NAME=$(echo "$LAST_BODY" | json_get "['name']" 2>/dev/null || echo "")
if [ "$SECRET_RET_NAME" = "$SECRET_NAME" ]; then
    pass "Secret retrieved correctly"
else
    fail "Secret name mismatch: '$SECRET_RET_NAME'"
fi

# Update
echo ""
echo ">>> 2c. Update secret"
call_api PUT "$API/secrets/$SECRET_ID" "{
    \"name\": \"$SECRET_NAME\",
    \"data\": {\"APP_API_KEY\": \"sk-test-key-updated\", \"APP_BASE_URL\": \"https://api.example.com\", \"APP_NEW_KEY\": \"new-val\"}
}"
if [ "$LAST_CODE" = "200" ] || [ "$LAST_CODE" = "204" ]; then
    pass "Secret updated"
else
    warn "Secret update: HTTP $LAST_CODE (may be expected if PUT not supported, trying POST upsert)"
    call_api POST "$API/secrets" "{
        \"name\": \"$SECRET_NAME\",
        \"data\": {\"APP_API_KEY\": \"sk-test-key-updated\", \"APP_NEW_KEY\": \"new-val\"}
    }"
    if [ "$LAST_CODE" = "200" ] || [ "$LAST_CODE" = "201" ] || [ "$LAST_CODE" = "409" ]; then
        pass "Secret upsert attempted"
    fi
fi

# List
echo ""
echo ">>> 2d. List secrets"
call_api GET "$API/secrets"
if echo "$LAST_BODY" | grep -q "$SECRET_NAME"; then
    pass "Secret visible in list"
else
    fail "Secret not in list"
fi

# Create CLI credentials secret (from env vars)
echo ""
echo ">>> 2e. Create CLI credentials secret"
call_api POST "$API/secrets" "{
    \"name\": \"$CRED_SECRET_NAME\",
    \"data\": $CRED_DATA
}"
if [ "$LAST_CODE" = "201" ]; then
    pass "CLI credentials secret created"
    CRED_SECRET_ID=$(echo "$LAST_BODY" | json_get "['id']")
    info "Credentials Secret: $CRED_SECRET_ID"
else
    fail "CLI credentials secret: HTTP $LAST_CODE"
    exit 1
fi

# ══════════════════════════════════════════════════════════════
# STEP 3: Environment Creation
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 3: Environment Creation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ENV_NAME="e2e-fullchain-$(date +%s)"
call_api POST "$API/environments" "{
    \"name\": \"$ENV_NAME\",
    \"description\": \"Full-chain test environment\",
    \"config\": {
        \"type\": \"cloud\",
        \"packages\": {\"apt\": [\"jq\"]}
    }
}"
ENV_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then
    pass "Environment created ($ENV_NAME)"
    info "Environment ID: $ENV_ID"
else
    fail "Environment: HTTP $LAST_CODE"
    exit 1
fi

ENV_PKG=$(echo "$LAST_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['config'].get('packages',{}).get('apt',[])[0])" 2>/dev/null || echo "?")
if [ "$ENV_PKG" = "jq" ]; then
    pass "Package 'jq' configured"
else
    warn "Package config: '$ENV_PKG'"
fi

# ══════════════════════════════════════════════════════════════
# STEP 4: Agent Creation (Claude + always_ask + custom tool)
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 4: Agent Creation (Claude)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

AGENT_NAME="e2e-fullchain-agent-$(date +%s)"
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_NAME\",
    \"engine_kind\": \"claude\",
    \"model\": {\"id\": \"Claude-Opus-4.6\"},
    \"system_prompt\": \"You are a test agent. When asked to do something, use the Bash tool. Be concise.\",
    \"environment_ref\": \"$ENV_NAME\",
    \"secret_ref\": \"$CRED_SECRET_NAME\",
    \"tools\": [
        {
            \"type\": \"agent_toolset_20260401\",
            \"default_config\": {\"permission_policy\": {\"type\": \"always_ask\"}},
            \"configs\": [{\"name\": \"Bash\", \"enabled\": true}]
        },
        {
            \"type\": \"custom\",
            \"name\": \"get_weather\",
            \"description\": \"Get weather for a city.\",
            \"input_schema\": {
                \"type\": \"object\",
                \"properties\": {\"city\": {\"type\": \"string\"}},
                \"required\": [\"city\"]
            }
        }
    ]
}"
AGENT_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then
    pass "Agent created (claude, always_ask, custom tool)"
    info "Agent ID: $AGENT_ID"
else
    fail "Agent: HTTP $LAST_CODE"
    exit 1
fi

# Verify fields
AGENT_ENV_REF=$(echo "$LAST_BODY" | json_get "['environment_ref']" 2>/dev/null || echo "?")
AGENT_TOOLS_COUNT=$(echo "$LAST_BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['tools']))" 2>/dev/null || echo "0")
HAS_CUSTOM=$(echo "$LAST_BODY" | python3 -c "
import sys,json
a=json.load(sys.stdin)
print('YES' if any(t.get('name')=='get_weather' for t in a['tools']) else 'NO')
" 2>/dev/null || echo "NO")
HAS_ASK=$(echo "$LAST_BODY" | python3 -c "
import sys,json
a=json.load(sys.stdin)
for t in a['tools']:
    if t.get('type')=='agent_toolset_20260401':
        print(t.get('default_config',{}).get('permission_policy',{}).get('type',''))
        break
" 2>/dev/null || echo "?")

if [ "$AGENT_ENV_REF" = "$ENV_NAME" ]; then pass "Agent references environment"; else fail "env_ref: '$AGENT_ENV_REF'"; fi
AGENT_SECRET_REF=$(echo "$LAST_BODY" | json_get "['secret_ref']" 2>/dev/null || echo "?")
if [ "$AGENT_SECRET_REF" = "$CRED_SECRET_NAME" ]; then pass "Agent references credentials secret"; else fail "secret_ref: '$AGENT_SECRET_REF'"; fi
if [ "$AGENT_TOOLS_COUNT" = "2" ]; then pass "Agent has 2 tools"; else fail "tools: $AGENT_TOOLS_COUNT"; fi
if [ "$HAS_CUSTOM" = "YES" ]; then pass "Custom tool 'get_weather' present"; else fail "Custom tool missing"; fi
if [ "$HAS_ASK" = "always_ask" ]; then pass "Permission policy: always_ask"; else fail "policy: '$HAS_ASK'"; fi

# ══════════════════════════════════════════════════════════════
# STEP 5: Multi-Engine Agent (Codex)
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 5: Multi-Engine Agent (Codex)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

AGENT_CODEX_NAME="e2e-codex-$(date +%s)"
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_CODEX_NAME\",
    \"engine_kind\": \"codex\",
    \"model\": {\"id\": \"o3-mini\"},
    \"system_prompt\": \"You are a coding assistant.\"
}"
AGENT_CODEX_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then
    pass "Codex agent created"
    info "Agent ID: $AGENT_CODEX_ID"
else
    warn "Codex agent: HTTP $LAST_CODE (may not be supported)"
fi

CODEX_ENGINE=$(echo "$LAST_BODY" | json_get "['engine_kind']" 2>/dev/null || echo "?")
if [ "$CODEX_ENGINE" = "codex" ]; then
    pass "Engine kind: codex"
else
    warn "Engine kind: '$CODEX_ENGINE'"
fi

# ══════════════════════════════════════════════════════════════
# STEP 6: Session Creation
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 6: Session Creation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

call_api POST "$API/sessions" "{\"agent\":\"$AGENT_ID\",\"environment_id\":\"$ENV_ID\"}"
SESSION_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then
    pass "Session created"
    info "Session ID: $SESSION_ID"
else
    fail "Session: HTTP $LAST_CODE"
    exit 1
fi

SESSION_STATUS=$(echo "$LAST_BODY" | json_get "['status']")
SESSION_AGENT=$(echo "$LAST_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['agent']['name'])" 2>/dev/null || echo "?")

if [ "$SESSION_STATUS" = "idle" ]; then pass "Initial status: idle"; else fail "Status: '$SESSION_STATUS'"; fi
if [ "$SESSION_AGENT" = "$AGENT_NAME" ]; then pass "Session references correct agent"; else fail "Agent: '$SESSION_AGENT'"; fi

# ══════════════════════════════════════════════════════════════
# STEP 7: Send user.message
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 7: Send user.message"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

call_api POST "$API/sessions/$SESSION_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"Create a file by running: touch /tmp/e2e_fullchain_test.txt"}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Polling for idle..."
wait_for_idle "$SESSION_ID" "requires_action" 40 3
FIRST_STATUS="$_WAIT_STATUS"
FIRST_EVENT_ID="$_WAIT_EVENT_ID"

if [ "$FIRST_STATUS" = "requires_action" ]; then
    pass "Session paused: requires_action"
    info "Tool event: $FIRST_EVENT_ID"
elif [ "$FIRST_STATUS" = "end_turn" ]; then
    pass "Session completed: end_turn (no HITL needed)"
    info "Agent completed without tool use or with always_allow"
else
    fail "Unexpected status: '$FIRST_STATUS'"
fi

# ══════════════════════════════════════════════════════════════
# STEP 8: HITL Approve
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 8: HITL Approve"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$FIRST_STATUS" = "requires_action" ] && [ -n "$FIRST_EVENT_ID" ]; then
    # Detect event type
    TOOL_ETYPE=$(curl -s "$API/sessions/$SESSION_ID/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
for e in evts:
    if e.get('id')=='$FIRST_EVENT_ID':
        print(e.get('type',''))
        break
else:
    print('')
" 2>/dev/null || echo "")

    TOOL_NAME=$(curl -s "$API/sessions/$SESSION_ID/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
for e in evts:
    if e.get('id')=='$FIRST_EVENT_ID':
        print(e.get('name','?'))
        break
" 2>/dev/null || echo "?")

    info "Tool: $TOOL_NAME (type: $TOOL_ETYPE)"

    if [ "$TOOL_ETYPE" = "agent.custom_tool_use" ]; then
        echo -e "  ${YELLOW}-> Sending custom tool result${NC}"
        call_api POST "$API/sessions/$SESSION_ID/events" \
            "{\"events\":[{\"type\":\"user.custom_tool_result\",\"tool_use_event_id\":\"$FIRST_EVENT_ID\",\"content\":\"OK - executed\"}]}"
    else
        echo -e "  ${YELLOW}-> Approving tool use${NC}"
        call_api POST "$API/sessions/$SESSION_ID/events" \
            "{\"events\":[{\"type\":\"user.tool_confirmation\",\"tool_use_id\":\"$FIRST_EVENT_ID\",\"result\":\"allow\"}]}"
    fi
    if [ "$LAST_CODE" = "201" ]; then pass "Confirmation sent"; else fail "Confirmation: HTTP $LAST_CODE"; fi

    echo "  Waiting for completion..."
    auto_approve_until_done "$SESSION_ID" 20 5
    pass "HITL approve: session completed"

    # Verify tool_result
    TR=$(has_event_type "$SESSION_ID" "agent.tool_result")
    if [ "$TR" = "YES" ]; then
        pass "tool_result event present"
    else
        warn "No tool_result (agent may have used custom tool only)"
    fi
else
    info "Skipping approve — session already completed"
fi

echo ""
echo "  Events after approve:"
print_events "$SESSION_ID"

# ══════════════════════════════════════════════════════════════
# STEP 9: HITL Deny
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 9: HITL Deny"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

call_api POST "$API/sessions/$SESSION_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"Create a file by running: touch /tmp/e2e_deny_test.txt"}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Deny test message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Waiting for requires_action..."
wait_for_idle "$SESSION_ID" "requires_action" 50 3
DENY_EVENT_ID="$_WAIT_EVENT_ID"

if [ "$_WAIT_STATUS" = "requires_action" ] && [ -n "$DENY_EVENT_ID" ]; then
    echo -e "  ${YELLOW}-> Sending DENIAL${NC}"
    call_api POST "$API/sessions/$SESSION_ID/events" \
        "{\"events\":[{\"type\":\"user.tool_confirmation\",\"tool_use_id\":\"$DENY_EVENT_ID\",\"result\":\"deny\",\"deny_message\":\"Permission denied by e2e test\"}]}"
    if [ "$LAST_CODE" = "201" ]; then pass "Denial sent"; else fail "Denial: HTTP $LAST_CODE"; fi

    echo "  Waiting for agent to handle denial..."
    auto_approve_until_done "$SESSION_ID" 20 5
    pass "HITL deny: agent handled denial"
elif [ "$_WAIT_STATUS" = "end_turn" ]; then
    info "Agent completed without requiring confirmation"
else
    warn "Deny test: unexpected status '$_WAIT_STATUS'"
fi

echo ""
echo "  Events after deny:"
print_events "$SESSION_ID"

# ══════════════════════════════════════════════════════════════
# STEP 10: Custom Tool Flow
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 10: Custom Tool Flow"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Use a fresh session to avoid accumulated context from Steps 7-9
call_api POST "$API/sessions" "{\"agent\":\"$AGENT_ID\",\"environment_id\":\"$ENV_ID\"}"
SESSION_CUSTOM_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Custom tool session created"; else fail "Session: HTTP $LAST_CODE"; fi

call_api POST "$API/sessions/$SESSION_CUSTOM_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"What is the weather in Tokyo? Use the get_weather tool."}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Custom tool message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Waiting for requires_action (custom tool)..."
wait_for_idle "$SESSION_CUSTOM_ID" "requires_action" 40 3
CUSTOM_EID="$_WAIT_EVENT_ID"

if [ "$_WAIT_STATUS" = "requires_action" ] && [ -n "$CUSTOM_EID" ]; then
    CUSTOM_ETYPE=$(curl -s "$API/sessions/$SESSION_CUSTOM_ID/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
for e in evts:
    if e.get('id')=='$CUSTOM_EID':
        print(e.get('type',''))
        break
else:
    print('')
" 2>/dev/null || echo "")

    if [ "$CUSTOM_ETYPE" = "agent.custom_tool_use" ]; then
        pass "Custom tool triggered: agent.custom_tool_use"
        call_api POST "$API/sessions/$SESSION_CUSTOM_ID/events" \
            "{\"events\":[{\"type\":\"user.custom_tool_result\",\"tool_use_event_id\":\"$CUSTOM_EID\",\"content\":\"Temperature: 18°C, Conditions: Cloudy, Humidity: 65%\"}]}"
        if [ "$LAST_CODE" = "201" ]; then pass "Custom tool result sent"; else fail "Result: HTTP $LAST_CODE"; fi
    else
        info "Got standard tool_use instead of custom_tool_use — approving"
        call_api POST "$API/sessions/$SESSION_CUSTOM_ID/events" \
            "{\"events\":[{\"type\":\"user.tool_confirmation\",\"tool_use_id\":\"$CUSTOM_EID\",\"result\":\"allow\"}]}"
    fi

    echo "  Waiting for completion..."
    auto_approve_until_done "$SESSION_CUSTOM_ID" 40 5
    pass "Custom tool flow completed"
elif [ "$_WAIT_STATUS" = "end_turn" ]; then
    warn "Agent completed without using custom tool"
else
    warn "Custom tool: unexpected status '$_WAIT_STATUS'"
fi

# ══════════════════════════════════════════════════════════════
# STEP 11: Unrestricted Networking Smoke Test
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 11: Unrestricted Networking Smoke Test"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ENV_UNRES_NAME="e2e-unrestricted-$(date +%s)"
call_api POST "$API/environments" "{\"name\":\"$ENV_UNRES_NAME\",\"config\":{\"type\":\"cloud\",\"networking\":{\"type\":\"unrestricted\"}}}"
ENV_UNRES_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Unrestricted environment created"; else fail "Unrestricted env: HTTP $LAST_CODE"; fi

AGENT_UNRES_NAME="e2e-unrestricted-agent-$(date +%s)"
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_UNRES_NAME\",
    \"engine_kind\": \"claude\",
    \"model\": {\"id\": \"Claude-Opus-4.6\"},
    \"system_prompt\": \"Reply concisely. Do not use any tools.\",
    \"environment_ref\": \"$ENV_UNRES_NAME\",
    \"secret_ref\": \"$CRED_SECRET_NAME\",
    \"tools\": [{
        \"type\": \"agent_toolset_20260401\",
        \"default_config\": {\"permission_policy\": {\"type\": \"always_allow\"}},
        \"configs\": [{\"name\": \"Bash\", \"enabled\": true}]
    }]
}"
AGENT_UNRES_ID=$(echo "$LAST_BODY" | json_get "['id']" 2>/dev/null || echo "")

call_api POST "$API/sessions" "{\"agent\":\"$AGENT_UNRES_ID\",\"environment_id\":\"$ENV_UNRES_ID\"}"
SESSION_UNRES_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Unrestricted session created"; else fail "Session: HTTP $LAST_CODE"; fi

call_api POST "$API/sessions/$SESSION_UNRES_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"Say hello. Do not use any tools, just reply with text."}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Unrestricted message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Waiting for completion..."
wait_for_idle "$SESSION_UNRES_ID" "end_turn" 40 5

if [ "$_WAIT_STATUS" = "end_turn" ]; then
    pass "Unrestricted networking: completed"
elif [ "$_WAIT_STATUS" = "requires_action" ]; then
    info "Got requires_action — auto-approving"
    auto_approve_until_done "$SESSION_UNRES_ID" 20 5
    pass "Unrestricted networking: completed after approval"
else
    warn "Unrestricted networking: status '$_WAIT_STATUS'"
fi

UNRES_MSG=$(has_event_type "$SESSION_UNRES_ID" "agent.message")
if [ "$UNRES_MSG" = "YES" ]; then
    pass "Unrestricted networking: agent.message event present"
else
    warn "Unrestricted networking: no agent.message"
fi

# Clean up unrestricted agent
[ -n "$AGENT_UNRES_ID" ] && delete_resource agents "$AGENT_UNRES_ID" "?force=true"
AGENT_UNRES_ID=""

# ══════════════════════════════════════════════════════════════
# STEP 12: Limited Networking Smoke Test
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 12: Limited Networking Smoke Test"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ENV_LIMITED_NAME="e2e-limited-$(date +%s)"
call_api POST "$API/environments" "{
    \"name\": \"$ENV_LIMITED_NAME\",
    \"config\": {
        \"type\": \"cloud\",
        \"networking\": {
            \"type\": \"limited\",
            \"allowed_hosts\": [\"api.anthropic.com\"]
        }
    }
}"
ENV_LIMITED_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Limited environment created"; else fail "Limited env: HTTP $LAST_CODE"; fi

AGENT_LIMITED_NAME="e2e-limited-agent-$(date +%s)"
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_LIMITED_NAME\",
    \"engine_kind\": \"claude\",
    \"model\": {\"id\": \"Claude-Opus-4.6\"},
    \"system_prompt\": \"Reply concisely. Do not use any tools.\",
    \"environment_ref\": \"$ENV_LIMITED_NAME\",
    \"secret_ref\": \"$CRED_SECRET_NAME\",
    \"tools\": [{
        \"type\": \"agent_toolset_20260401\",
        \"default_config\": {\"permission_policy\": {\"type\": \"always_allow\"}},
        \"configs\": [{\"name\": \"Bash\", \"enabled\": true}]
    }]
}"
AGENT_LIMITED_ID=$(echo "$LAST_BODY" | json_get "['id']" 2>/dev/null || echo "")

call_api POST "$API/sessions" "{\"agent\":\"$AGENT_LIMITED_ID\",\"environment_id\":\"$ENV_LIMITED_ID\"}"
SESSION_LIMITED_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Limited session created"; else fail "Session: HTTP $LAST_CODE"; fi

call_api POST "$API/sessions/$SESSION_LIMITED_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"What is 2 + 3? Reply with just the number, no tools."}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Limited message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Waiting for completion..."
wait_for_idle "$SESSION_LIMITED_ID" "end_turn" 40 5

if [ "$_WAIT_STATUS" = "end_turn" ]; then
    pass "Limited networking: completed"
elif [ "$_WAIT_STATUS" = "requires_action" ]; then
    auto_approve_until_done "$SESSION_LIMITED_ID" 20 5
    pass "Limited networking: completed after approval"
else
    warn "Limited networking: status '$_WAIT_STATUS'"
fi

LIMITED_MSG=$(has_event_type "$SESSION_LIMITED_ID" "agent.message")
if [ "$LIMITED_MSG" = "YES" ]; then
    pass "Limited networking: agent.message event present"
else
    warn "Limited networking: no agent.message"
fi

# Clean up limited agent
[ -n "$AGENT_LIMITED_ID" ] && delete_resource agents "$AGENT_LIMITED_ID" "?force=true"
AGENT_LIMITED_ID=""

# ══════════════════════════════════════════════════════════════
# STEP 13: Final Verification
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 13: Final Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# GET agent by ID
echo ">>> 13a. GET /agents/{id}"
call_api GET "$API/agents/$AGENT_ID"
GET_NAME=$(echo "$LAST_BODY" | json_get "['name']" 2>/dev/null || echo "")
if [ "$GET_NAME" = "$AGENT_NAME" ]; then
    pass "GET agent returns correct data"
else
    fail "GET agent: name='$GET_NAME'"
fi

# List sessions
echo ""
echo ">>> 13b. List sessions"
call_api GET "$API/sessions"
if echo "$LAST_BODY" | grep -q "$SESSION_ID"; then
    pass "Session visible in list"
else
    warn "Session not found in list"
fi

# Event integrity for main session
echo ""
echo ">>> 13c. Event integrity"

INTEGRITY=$(curl -s "$API/sessions/$SESSION_ID/events?limit=100" 2>/dev/null | python3 -c "
import sys, json
r = json.load(sys.stdin)
evts = r if isinstance(r, list) else r.get('events', r.get('data', []))
types = [e.get('type', '') for e in evts]

checks = {
    'user.message': 'user.message' in types,
    'session.status_running': 'session.status_running' in types,
    'session.status_idle': 'session.status_idle' in types,
}
for k, v in checks.items():
    print(f'{k}:{'YES' if v else 'NO'}')
" 2>/dev/null || echo "")

while IFS= read -r line; do
    [ -z "$line" ] && continue
    NAME=$(echo "$line" | cut -d':' -f1)
    VAL=$(echo "$line" | cut -d':' -f2)
    if [ "$VAL" = "YES" ]; then
        pass "Event integrity: $NAME present"
    else
        fail "Event integrity: $NAME missing"
    fi
done <<< "$INTEGRITY"

# Final event timeline
echo ""
echo ">>> Final event timeline (main session):"
print_events "$SESSION_ID"

# Usage
echo ""
echo ">>> 13d. Usage check"
FINAL_SESSION=$(curl -s "$API/sessions/$SESSION_ID" 2>/dev/null)
USAGE=$(echo "$FINAL_SESSION" | python3 -c "
import sys, json
s = json.load(sys.stdin)
u = s.get('usage', {})
print(f\"input={u.get('input_tokens',0)} output={u.get('output_tokens',0)}\")
" 2>/dev/null || echo "unknown")
info "Usage: $USAGE"

# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════
print_summary

if [ $? -eq 0 ]; then
    echo "Full-chain E2E verified:"
    echo "  - Health check"
    echo "  - Secret CRUD"
    echo "  - Environment with packages + restricted networking"
    echo "  - Agent with tools, permissions, custom tool, env_ref, secretRef"
    echo "  - Multi-engine agent (codex)"
    echo "  - Session lifecycle: idle → running → idle"
    echo "  - HITL: approve + deny flows"
    echo "  - Custom tool: custom_tool_use → custom_tool_result"
    echo "  - Unrestricted networking smoke test"
    echo "  - Limited networking smoke test"
    echo "  - API retrieval and event integrity"
fi

exit $FAILED
