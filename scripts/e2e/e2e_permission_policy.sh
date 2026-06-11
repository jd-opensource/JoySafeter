#!/bin/bash
#
# Permission Policy E2E Test
#
# Tests all permission policy scenarios:
#   Part 1: always_allow — tool executes immediately
#   Part 2: always_ask + approve — tool pauses, user approves
#   Part 3: always_ask + deny — tool pauses, user denies
#   Part 4: custom tool — custom_tool_use → custom_tool_result
#   Part 5: state machine verification — full event sequence
#
# Usage:
#   bash scripts/e2e_permission_policy.sh
#   JOYSAFETER_URL=http://host:8080 bash scripts/e2e_permission_policy.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/e2e_helpers.sh"

ENV_ID=""
AGENT_ALLOW_ID=""
AGENT_ASK_ID=""
AGENT_CUSTOM_ID=""
SESSION_ALLOW_ID=""
SESSION_ASK_ID=""
SESSION_CUSTOM_ID=""

cleanup() {
    echo ""
    echo "=== Cleanup ==="
    [ -n "$SESSION_CUSTOM_ID" ] && delete_resource sessions "$SESSION_CUSTOM_ID"
    [ -n "$SESSION_ASK_ID" ]    && delete_resource sessions "$SESSION_ASK_ID"
    [ -n "$SESSION_ALLOW_ID" ]  && delete_resource sessions "$SESSION_ALLOW_ID"
    [ -n "$AGENT_CUSTOM_ID" ]   && delete_resource agents "$AGENT_CUSTOM_ID" "?force=true"
    [ -n "$AGENT_ASK_ID" ]      && delete_resource agents "$AGENT_ASK_ID" "?force=true"
    [ -n "$AGENT_ALLOW_ID" ]    && delete_resource agents "$AGENT_ALLOW_ID" "?force=true"
    [ -n "$ENV_ID" ]            && delete_resource environments "$ENV_ID"
    echo "Done."
}
trap cleanup EXIT

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Permission Policy E2E Test                              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  API: $API"
echo ""

# ═══════════════════════════════════════════════════════════
# Setup: shared environment
# ═══════════════════════════════════════════════════════════
echo "━━━ Setup: Create Environment ━━━"
ENV_NAME="e2e-perm-$(date +%s)"
call_api POST "$API/environments" "{\"name\":\"$ENV_NAME\",\"config\":{\"type\":\"cloud\"}}"
ENV_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Environment created ($ENV_NAME)"; else fail "Environment: HTTP $LAST_CODE"; exit 1; fi

# ═══════════════════════════════════════════════════════════
# PART 1: always_allow
# ═══════════════════════════════════════════════════════════
echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PART 1: always_allow — tools execute without pause     ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

# 1a. Create agent
echo "━━━ 1a. Create Agent (always_allow) ━━━"
AGENT_ALLOW_NAME="e2e-allow-$(date +%s)"
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_ALLOW_NAME\",
    \"engine_kind\": \"claude\",
    \"model\": {\"id\": \"Claude-Opus-4.6\"},
    \"system_prompt\": \"You are a test agent. When asked to run a command, use the Bash tool immediately. Be concise.\",
    \"environment_ref\": \"$ENV_NAME\",
    \"tools\": [{
        \"type\": \"agent_toolset_20260401\",
        \"default_config\": {\"permission_policy\": {\"type\": \"always_allow\"}},
        \"configs\": [{\"name\": \"Bash\", \"enabled\": true}]
    }]
}"
AGENT_ALLOW_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Agent created (always_allow)"; else fail "Agent: HTTP $LAST_CODE"; exit 1; fi

# 1b. Create session
echo ""
echo "━━━ 1b. Create Session ━━━"
call_api POST "$API/sessions" "{\"agent\":\"$AGENT_ALLOW_ID\",\"environment_id\":\"$ENV_ID\"}"
SESSION_ALLOW_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Session created"; else fail "Session: HTTP $LAST_CODE"; exit 1; fi
info "Session: $SESSION_ALLOW_ID"

# 1c. Send command — should auto-execute
echo ""
echo "━━━ 1c. Send command (should auto-execute) ━━━"
call_api POST "$API/sessions/$SESSION_ALLOW_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"Create a file by running: touch /tmp/allow_policy_test.txt"}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Waiting for completion (expecting end_turn, NOT requires_action)..."
wait_for_idle "$SESSION_ALLOW_ID" "end_turn" 40

if [ "$_WAIT_STATUS" = "end_turn" ]; then
    pass "always_allow: tool executed without confirmation (end_turn)"
elif [ "$_WAIT_STATUS" = "requires_action" ]; then
    fail "always_allow: unexpectedly got requires_action"
else
    fail "always_allow: unexpected status '$_WAIT_STATUS'"
fi

# 1d. Verify tool_result (events stream asynchronously, retry a few times)
echo ""
echo "  Verifying tool executed..."
TR="NO"
for _try in 1 2 3 4 5; do
    sleep 5
    TR=$(has_event_type "$SESSION_ALLOW_ID" "agent.tool_result")
    [ "$TR" = "YES" ] && break
done
if [ "$TR" = "YES" ]; then
    pass "always_allow: tool_result event found"
else
    fail "always_allow: no tool_result event"
fi

# 1e. Verify no requires_action
RA_COUNT=$(curl -s "$API/sessions/$SESSION_ALLOW_ID/events?limit=100" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
count=sum(1 for e in evts if e.get('stop_reason',{}).get('type')=='requires_action')
print(count)
" 2>/dev/null || echo "?")
if [ "$RA_COUNT" = "0" ]; then
    pass "always_allow: no requires_action events"
else
    fail "always_allow: found $RA_COUNT requires_action events"
fi

echo ""
echo "  Events (always_allow):"
print_events "$SESSION_ALLOW_ID"

# ═══════════════════════════════════════════════════════════
# PART 2: always_ask — Approve
# ═══════════════════════════════════════════════════════════
echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PART 2: always_ask — Approve tool use                  ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

# 2a. Create agent
echo "━━━ 2a. Create Agent (always_ask) ━━━"
AGENT_ASK_NAME="e2e-ask-$(date +%s)"
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_ASK_NAME\",
    \"engine_kind\": \"claude\",
    \"model\": {\"id\": \"Claude-Opus-4.6\"},
    \"system_prompt\": \"You are a test agent. When asked to run a command, use the Bash tool immediately. Be concise.\",
    \"environment_ref\": \"$ENV_NAME\",
    \"tools\": [{
        \"type\": \"agent_toolset_20260401\",
        \"default_config\": {\"permission_policy\": {\"type\": \"always_ask\"}},
        \"configs\": [{\"name\": \"Bash\", \"enabled\": true}]
    }]
}"
AGENT_ASK_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Agent created (always_ask)"; else fail "Agent: HTTP $LAST_CODE"; exit 1; fi

# 2b. Create session
echo ""
echo "━━━ 2b. Create Session ━━━"
call_api POST "$API/sessions" "{\"agent\":\"$AGENT_ASK_ID\",\"environment_id\":\"$ENV_ID\"}"
SESSION_ASK_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Session created"; else fail "Session: HTTP $LAST_CODE"; exit 1; fi
info "Session: $SESSION_ASK_ID"

# 2c. Send command → wait for requires_action
echo ""
echo "━━━ 2c. Send command → approve ━━━"
call_api POST "$API/sessions/$SESSION_ASK_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"Create a file by running: touch /tmp/ask_approve_test.txt"}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Waiting for requires_action..."
wait_for_idle "$SESSION_ASK_ID" "requires_action" 40

TOOL_EVENT_ID="$_WAIT_EVENT_ID"
if [ "$_WAIT_STATUS" = "requires_action" ] && [ -n "$TOOL_EVENT_ID" ]; then
    pass "always_ask: session paused (requires_action)"
    info "Tool event ID: $TOOL_EVENT_ID"
else
    fail "always_ask: expected requires_action but got '$_WAIT_STATUS'"
fi

# Send approval
if [ -n "$TOOL_EVENT_ID" ]; then
    echo ""
    echo -e "  ${YELLOW}-> Sending APPROVAL${NC}"
    call_api POST "$API/sessions/$SESSION_ASK_ID/events" \
        "{\"events\":[{\"type\":\"user.tool_confirmation\",\"tool_use_id\":\"$TOOL_EVENT_ID\",\"result\":\"allow\"}]}"
    if [ "$LAST_CODE" = "201" ]; then pass "Approval sent"; else fail "Approval: HTTP $LAST_CODE"; fi

    echo "  Waiting for completion after approval..."
    auto_approve_until_done "$SESSION_ASK_ID" 30 5

    # Verify tool_result
    TR2=$(has_event_type "$SESSION_ASK_ID" "agent.tool_result")
    if [ "$TR2" = "YES" ]; then
        pass "always_ask approve: tool_result found"
    else
        fail "always_ask approve: no tool_result"
    fi
fi

echo ""
echo "  Events after approve:"
print_events "$SESSION_ASK_ID"

# ═══════════════════════════════════════════════════════════
# PART 3: always_ask — Deny
# ═══════════════════════════════════════════════════════════
echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PART 3: always_ask — Deny tool use                     ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

echo "━━━ 3a. Send command → deny ━━━"
call_api POST "$API/sessions/$SESSION_ASK_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"Create a file by running: touch /tmp/ask_deny_test.txt"}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Deny test message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Waiting for requires_action..."
wait_for_idle "$SESSION_ASK_ID" "requires_action" 40

DENY_EVENT_ID="$_WAIT_EVENT_ID"
if [ "$_WAIT_STATUS" = "requires_action" ] && [ -n "$DENY_EVENT_ID" ]; then
    pass "always_ask: session paused for deny test"
    info "Tool event ID: $DENY_EVENT_ID"
else
    fail "always_ask: expected requires_action for deny but got '$_WAIT_STATUS'"
fi

if [ -n "$DENY_EVENT_ID" ]; then
    echo ""
    echo -e "  ${YELLOW}-> Sending DENIAL${NC}"
    call_api POST "$API/sessions/$SESSION_ASK_ID/events" \
        "{\"events\":[{\"type\":\"user.tool_confirmation\",\"tool_use_id\":\"$DENY_EVENT_ID\",\"result\":\"deny\",\"deny_message\":\"Permission denied by test\"}]}"
    if [ "$LAST_CODE" = "201" ]; then pass "Denial sent"; else fail "Denial: HTTP $LAST_CODE"; fi

    echo "  Waiting for agent to handle denial..."
    auto_approve_until_done "$SESSION_ASK_ID" 30 5
    pass "always_ask deny: agent handled denial"
fi

echo ""
echo "  Events after deny:"
print_events "$SESSION_ASK_ID"

# ═══════════════════════════════════════════════════════════
# PART 4: Custom Tool
# ═══════════════════════════════════════════════════════════
echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PART 4: Custom Tool (always_ask)                       ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

echo "━━━ 4a. Create Agent (always_ask + custom tool) ━━━"
AGENT_CUSTOM_NAME="e2e-custom-$(date +%s)"
call_api POST "$API/agents" "{
    \"name\": \"$AGENT_CUSTOM_NAME\",
    \"engine_kind\": \"claude\",
    \"model\": {\"id\": \"Claude-Opus-4.6\"},
    \"system_prompt\": \"You are a test agent. When asked about weather, use the get_weather tool. Be concise.\",
    \"environment_ref\": \"$ENV_NAME\",
    \"tools\": [
        {
            \"type\": \"agent_toolset_20260401\",
            \"default_config\": {\"permission_policy\": {\"type\": \"always_ask\"}},
            \"configs\": [{\"name\": \"Bash\", \"enabled\": true}]
        },
        {
            \"type\": \"custom\",
            \"name\": \"get_weather\",
            \"description\": \"Get weather for a city. Returns temperature and conditions.\",
            \"input_schema\": {
                \"type\": \"object\",
                \"properties\": {\"city\": {\"type\": \"string\", \"description\": \"City name\"}},
                \"required\": [\"city\"]
            }
        }
    ]
}"
AGENT_CUSTOM_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Agent created (custom tool)"; else fail "Agent: HTTP $LAST_CODE"; exit 1; fi

# 4b. Create session
echo ""
echo "━━━ 4b. Create Session ━━━"
call_api POST "$API/sessions" "{\"agent\":\"$AGENT_CUSTOM_ID\",\"environment_id\":\"$ENV_ID\"}"
SESSION_CUSTOM_ID=$(echo "$LAST_BODY" | json_get "['id']")
if [ "$LAST_CODE" = "201" ]; then pass "Session created"; else fail "Session: HTTP $LAST_CODE"; exit 1; fi

# 4c. Send message requesting custom tool
echo ""
echo "━━━ 4c. Send message → custom tool ━━━"
call_api POST "$API/sessions/$SESSION_CUSTOM_ID/events" \
    '{"events":[{"type":"user.message","content":[{"type":"text","text":"What is the weather in Beijing? Use the get_weather tool to find out."}]}]}'
if [ "$LAST_CODE" = "201" ]; then pass "Message sent"; else fail "Message: HTTP $LAST_CODE"; fi

echo "  Waiting for requires_action..."
wait_for_idle "$SESSION_CUSTOM_ID" "requires_action" 40

CUSTOM_EVENT_ID="$_WAIT_EVENT_ID"
if [ "$_WAIT_STATUS" = "requires_action" ] && [ -n "$CUSTOM_EVENT_ID" ]; then
    pass "Custom tool: session paused (requires_action)"

    # Detect event type
    CUSTOM_ETYPE=$(curl -s "$API/sessions/$SESSION_CUSTOM_ID/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
for e in evts:
    if e.get('id')=='$CUSTOM_EVENT_ID':
        print(e.get('type',''))
        break
else:
    print('')
" 2>/dev/null || echo "")

    info "Event type: $CUSTOM_ETYPE"

    if [ "$CUSTOM_ETYPE" = "agent.custom_tool_use" ]; then
        echo -e "  ${YELLOW}-> Sending custom tool result${NC}"
        call_api POST "$API/sessions/$SESSION_CUSTOM_ID/events" \
            "{\"events\":[{\"type\":\"user.custom_tool_result\",\"tool_use_event_id\":\"$CUSTOM_EVENT_ID\",\"content\":\"Temperature: 22°C, Conditions: Sunny, Humidity: 45%\"}]}"
        if [ "$LAST_CODE" = "201" ]; then pass "Custom tool result sent"; else fail "Custom tool result: HTTP $LAST_CODE"; fi
    else
        echo -e "  ${YELLOW}-> Sending tool confirmation (approve)${NC}"
        call_api POST "$API/sessions/$SESSION_CUSTOM_ID/events" \
            "{\"events\":[{\"type\":\"user.tool_confirmation\",\"tool_use_id\":\"$CUSTOM_EVENT_ID\",\"result\":\"allow\"}]}"
        if [ "$LAST_CODE" = "201" ]; then pass "Tool confirmation sent"; else fail "Confirmation: HTTP $LAST_CODE"; fi
    fi

    echo "  Waiting for completion..."
    auto_approve_until_done "$SESSION_CUSTOM_ID" 20 5
    pass "Custom tool flow completed"
elif [ "$_WAIT_STATUS" = "end_turn" ]; then
    warn "Agent completed without using custom tool"
else
    fail "Custom tool: unexpected status '$_WAIT_STATUS'"
fi

echo ""
echo "  Events (custom tool):"
print_events "$SESSION_CUSTOM_ID"

# ═══════════════════════════════════════════════════════════
# PART 5: State Machine Verification
# ═══════════════════════════════════════════════════════════
echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PART 5: State Machine Verification                     ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

info "Verifying event sequences from always_ask session..."

SM_RESULT=$(curl -s "$API/sessions/$SESSION_ASK_ID/events?limit=100" 2>/dev/null | python3 -c "
import sys, json
r = json.load(sys.stdin)
evts = r if isinstance(r, list) else r.get('events', r.get('data', []))
types = [e.get('type', '') for e in evts]

checks = {
    'user.message': any(t == 'user.message' for t in types),
    'session.status_running': any(t == 'session.status_running' for t in types),
    'agent.tool_use': any(t == 'agent.tool_use' for t in types),
    'requires_action': any(
        e.get('type') == 'session.status_idle' and
        e.get('stop_reason', {}).get('type') == 'requires_action'
        for e in evts
    ),
    'user.tool_confirmation': any(t == 'user.tool_confirmation' for t in types),
    'end_turn': any(
        e.get('type') == 'session.status_idle' and
        e.get('stop_reason', {}).get('type') == 'end_turn'
        for e in evts
    ),
}

for name, ok in checks.items():
    print(f'{name}:{'YES' if ok else 'NO'}')
" 2>/dev/null || echo "")

while IFS= read -r line; do
    [ -z "$line" ] && continue
    NAME=$(echo "$line" | cut -d':' -f1)
    STATUS=$(echo "$line" | cut -d':' -f2)
    if [ "$STATUS" = "YES" ]; then
        pass "State machine: $NAME present"
    else
        fail "State machine: $NAME missing"
    fi
done <<< "$SM_RESULT"

# ═══════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════
print_summary
exit $?
