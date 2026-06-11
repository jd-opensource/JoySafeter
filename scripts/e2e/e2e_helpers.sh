#!/bin/bash
#
# Shared helpers for E2E test scripts
#
# Usage: source scripts/e2e_helpers.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

PASSED=0
FAILED=0
WARNINGS=0

API="${JOYSAFETER_URL:-http://localhost:8080}/v1"

# Engine-kind support: set ENGINE_KIND=codex to test with codex engine
ENGINE_KIND="${ENGINE_KIND:-claude}"

engine_model() {
    case "$ENGINE_KIND" in
        codex) echo "gpt-5.3-codex" ;;
        *)     echo "Claude-Opus-4.6" ;;
    esac
}

engine_default_secret() {
    case "$ENGINE_KIND" in
        codex) echo "codex-secret" ;;
        *)     echo "opus4.6_secret" ;;
    esac
}

pass() {
    echo -e "  ${GREEN}✓ PASS${NC}: $1"
    PASSED=$((PASSED + 1))
}

fail() {
    echo -e "  ${RED}✗ FAIL${NC}: $1"
    FAILED=$((FAILED + 1))
}

warn() {
    echo -e "  ${YELLOW}⚠ WARN${NC}: $1"
    WARNINGS=$((WARNINGS + 1))
}

info() {
    echo -e "  ${CYAN}ℹ${NC} $1"
}

json_get() {
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d$1)" 2>/dev/null
}

# Get the last agent reply for a session, with retry if empty.
# Usage: get_last_agent_reply SESSION_ID [MAX_RETRIES] [INTERVAL]
get_last_agent_reply() {
    local sid="$1" retries="${2:-5}" interval="${3:-2}"
    local reply=""
    for _r in $(seq 1 "$retries"); do
        reply=$(curl -sf "${API}/sessions/${sid}/events?limit=200" 2>/dev/null | python3 -c "
import sys, json
try:
    r = json.load(sys.stdin)
except: r = []
evts = r if isinstance(r, list) else r.get('events', r.get('data', []))
last_user_idx = -1
for i, e in enumerate(evts):
    if e.get('type') == 'user.message':
        last_user_idx = i
reply = ''
if last_user_idx >= 0:
    for e in reversed(evts[last_user_idx+1:]):
        if e.get('type') == 'agent.message':
            c = e.get('content', [])
            if isinstance(c, list) and c:
                reply = c[0].get('text', '')
            elif isinstance(c, str):
                reply = c
            break
print(reply)
" 2>/dev/null) || true
        if [ -n "$reply" ]; then
            echo "$reply"
            return 0
        fi
        sleep "$interval"
    done
    echo "$reply"
}

json_get_raw() {
    python3 -c "import sys,json; d=json.load(sys.stdin); v=d$1; print(json.dumps(v) if isinstance(v,(dict,list)) else str(v))" 2>/dev/null
}

# HTTP helper: call_api METHOD URL [BODY]
# Sets globals: LAST_CODE, LAST_BODY
call_api() {
    local method="$1"
    local url="$2"
    local body="${3:-}"

    local resp
    if [ -n "$body" ]; then
        resp=$(curl -s -w "\n%{http_code}" -X "$method" "$url" \
            -H "Content-Type: application/json" -d "$body")
    else
        resp=$(curl -s -w "\n%{http_code}" -X "$method" "$url")
    fi
    LAST_CODE=$(echo "$resp" | tail -1)
    LAST_BODY=$(echo "$resp" | sed '$d')
}

# Poll session until idle with expected stop_reason
# wait_for_idle SESSION_ID EXPECTED_STOP [MAX_POLLS=40] [INTERVAL=5]
# Sets globals: _WAIT_STATUS, _WAIT_EVENT_ID
wait_for_idle() {
    local SID="$1"
    local EXPECTED_STOP="$2"
    local MAX_WAIT="${3:-40}"
    local INTERVAL="${4:-5}"
    _WAIT_STATUS=""
    _WAIT_EVENT_ID=""

    for i in $(seq 1 "$MAX_WAIT"); do
        sleep "$INTERVAL"
        local STATE
        STATE=$(curl -s "$API/sessions/$SID" 2>/dev/null)
        local STATUS
        STATUS=$(echo "$STATE" | json_get "['status']" 2>/dev/null || echo "?")

        if [ "$STATUS" = "idle" ]; then
            local SR
            SR=$(echo "$STATE" | python3 -c "
import sys,json; s=json.load(sys.stdin); sr=s.get('stop_reason',{}); print(sr.get('type',''))" 2>/dev/null || echo "")
            if [ "$SR" = "$EXPECTED_STOP" ]; then
                if [ "$SR" = "requires_action" ]; then
                    _WAIT_STATUS="$SR"
                    _WAIT_EVENT_ID=$(echo "$STATE" | python3 -c "
import sys,json; s=json.load(sys.stdin); print(s.get('stop_reason',{}).get('event_ids',[''])[0])" 2>/dev/null || echo "")
                    return 0
                fi
                # For end_turn: verify agent actually replied after the last user message
                local HAS_REPLY
                HAS_REPLY=$(curl -s "$API/sessions/$SID/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
last_user=-1
for i,e in enumerate(evts):
    if e.get('type')=='user.message': last_user=i
has_reply=any(e.get('type')=='agent.message' for e in evts[last_user+1:]) if last_user>=0 else False
print('YES' if has_reply else 'NO')
" 2>/dev/null || echo "NO")
                if [ "$HAS_REPLY" = "YES" ]; then
                    # Stabilization: agent may start tool calls after replying.
                    # Wait briefly and re-check that session is still idle.
                    sleep 3
                    local RECHECK_STATUS
                    RECHECK_STATUS=$(curl -s "$API/sessions/$SID" 2>/dev/null | json_get "['status']" 2>/dev/null || echo "?")
                    if [ "$RECHECK_STATUS" = "idle" ]; then
                        _WAIT_STATUS="$SR"
                        return 0
                    fi
                    echo -e "${CYAN}    [${i}x${INTERVAL}s] agent replied but session went back to $RECHECK_STATUS, continuing...${NC}"
                    continue
                fi
                # After enough polls, accept the idle state — the turn
                # may have completed between our send and first poll,
                # or events may not be visible in the current page.
                if [ "$i" -ge 6 ]; then
                    _WAIT_STATUS="$SR"
                    return 0
                fi
                echo -e "${CYAN}    [${i}x${INTERVAL}s] idle(end_turn) but no agent reply yet, continuing...${NC}"
                continue
            elif [ -n "$SR" ] && [ "$SR" != "$EXPECTED_STOP" ]; then
                # When expecting requires_action but got end_turn, the sandbox
                # may still be starting up. The session bounces through a
                # transient idle(end_turn) before the agent actually processes.
                # Check events to see if requires_action already exists.
                if [ "$EXPECTED_STOP" = "requires_action" ] && [ "$SR" = "end_turn" ]; then
                    local RA_IN_EVENTS
                    RA_IN_EVENTS=$(curl -s "$API/sessions/$SID/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
for e in reversed(evts):
    if e.get('type')=='session.status_idle':
        sr=e.get('stop_reason',{})
        if sr.get('type')=='requires_action':
            ids=sr.get('event_ids',[])
            print(ids[0] if ids else 'FOUND')
            break
else:
    print('')
" 2>/dev/null || echo "")
                    if [ -n "$RA_IN_EVENTS" ]; then
                        _WAIT_STATUS="requires_action"
                        _WAIT_EVENT_ID="$RA_IN_EVENTS"
                        return 0
                    fi
                    # Check if agent has actually processed the LATEST message.
                    # Look for agent.message or agent.tool_result AFTER the last user.message.
                    if [ "$i" -ge 4 ]; then
                        local AGENT_DONE
                        AGENT_DONE=$(curl -s "$API/sessions/$SID/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
last_user_idx=-1
for i,e in enumerate(evts):
    if e.get('type')=='user.message':
        last_user_idx=i
has_response=any(e.get('type') in ('agent.message','agent.tool_result') for e in evts[last_user_idx+1:]) if last_user_idx>=0 else False
print('YES' if has_response else 'NO')
" 2>/dev/null || echo "NO")
                        if [ "$AGENT_DONE" = "YES" ]; then
                            _WAIT_STATUS="$SR"
                            return 0
                        fi
                    fi
                    echo -e "${CYAN}    [${i}x${INTERVAL}s] end_turn but expecting requires_action, continuing...${NC}"
                    continue
                fi
                _WAIT_STATUS="$SR"
                return 0
            fi
        fi

        # Fallback: check events every 3 polls
        if [ $((i % 3)) -eq 0 ]; then
            local EVENTS
            EVENTS=$(curl -s "$API/sessions/$SID/events?limit=20" 2>/dev/null)
            local IDLE_INFO
            IDLE_INFO=$(echo "$EVENTS" | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
# Find the LAST idle event, but prefer requires_action over end_turn
best=None
for e in evts:
    if e.get('type')=='session.status_idle':
        sr=e.get('stop_reason',{})
        best=(sr.get('type','?'), sr.get('event_ids',[]))
if best:
    print(f'{best[0]}|{best[1][0] if best[1] else \"\"}')
else:
    print('')
" 2>/dev/null || echo "")
            if [ -n "$IDLE_INFO" ]; then
                local IT IE
                IT=$(echo "$IDLE_INFO" | cut -d'|' -f1)
                IE=$(echo "$IDLE_INFO" | cut -d'|' -f2)
                if [ "$IT" = "$EXPECTED_STOP" ]; then
                    _WAIT_STATUS="$IT"
                    _WAIT_EVENT_ID="$IE"
                    return 0
                elif [ -n "$IT" ] && [ "$IT" != "?" ]; then
                    # Don't return end_turn when expecting requires_action —
                    # the session may still be in transient startup
                    if [ "$EXPECTED_STOP" = "requires_action" ] && [ "$IT" = "end_turn" ]; then
                        echo -e "${CYAN}    [fallback ${i}x${INTERVAL}s] end_turn but expecting requires_action, continuing...${NC}"
                    else
                        _WAIT_STATUS="$IT"
                        return 0
                    fi
                fi
            fi
        fi
        echo -e "${CYAN}    [${i}x${INTERVAL}s] status=$STATUS${NC}"
    done
    return 1
}

# Auto-approve loop: keep approving requires_action until end_turn
# auto_approve_until_done SESSION_ID [MAX_ROUNDS=10] [INTERVAL=5]
auto_approve_until_done() {
    local SID="$1"
    local MAX_ROUNDS="${2:-10}"
    local INTERVAL="${3:-5}"

    for round in $(seq 1 "$MAX_ROUNDS"); do
        sleep "$INTERVAL"
        local STATE
        STATE=$(curl -s "$API/sessions/$SID" 2>/dev/null)
        local STATUS
        STATUS=$(echo "$STATE" | json_get "['status']" 2>/dev/null || echo "?")

        if [ "$STATUS" = "idle" ]; then
            local SR
            SR=$(echo "$STATE" | python3 -c "
import sys,json; s=json.load(sys.stdin); sr=s.get('stop_reason',{}); print(sr.get('type','end_turn'))" 2>/dev/null || echo "")
            if [ "$SR" = "end_turn" ]; then
                return 0
            elif [ "$SR" = "requires_action" ]; then
                local EID
                EID=$(echo "$STATE" | python3 -c "
import sys,json; s=json.load(sys.stdin); print(s.get('stop_reason',{}).get('event_ids',[''])[0])" 2>/dev/null || echo "")
                if [ -n "$EID" ]; then
                    # Check if custom tool or standard tool
                    local ETYPE
                    ETYPE=$(curl -s "$API/sessions/$SID/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
for e in evts:
    if e.get('id')=='$EID':
        print(e.get('type',''))
        break
else:
    print('')
" 2>/dev/null || echo "")
                    if [ "$ETYPE" = "agent.custom_tool_use" ]; then
                        info "Auto-responding custom tool: $EID"
                        curl -s -X POST "$API/sessions/$SID/events" \
                            -H "Content-Type: application/json" \
                            -d "{\"events\":[{\"type\":\"user.custom_tool_result\",\"tool_use_event_id\":\"$EID\",\"content\":\"OK\"}]}" > /dev/null 2>&1
                    else
                        info "Auto-approving tool: $EID"
                        curl -s -X POST "$API/sessions/$SID/events" \
                            -H "Content-Type: application/json" \
                            -d "{\"events\":[{\"type\":\"user.tool_confirmation\",\"tool_use_id\":\"$EID\",\"result\":\"allow\"}]}" > /dev/null 2>&1
                    fi
                fi
            fi
        fi
        echo -e "${CYAN}    [approve round $round] status=$STATUS${NC}"
    done
    return 1
}

# Print event timeline for a session
print_events() {
    local SID="$1"
    curl -s "$API/sessions/$SID/events?limit=100" 2>/dev/null | python3 -c "
import sys, json
resp = json.load(sys.stdin)
events = resp if isinstance(resp, list) else resp.get('events', resp.get('data', []))
for i, e in enumerate(events):
    t = e.get('type', '?')
    snippet = ''
    if t in ('user.message', 'agent.message'):
        c = e.get('content', '')
        if isinstance(c, list): snippet = c[0].get('text', '')[:80] if c else ''
        elif isinstance(c, str): snippet = c[:80]
    elif 'tool_use' in t:
        snippet = f\"-> {e.get('name','?')}({str(e.get('input',''))[:50]})\"
    elif 'tool_result' in t:
        c = e.get('content', '')
        if isinstance(c, list) and c: snippet = f\"<- {str(c[0].get('text',''))[:50]}\"
        elif isinstance(c, str): snippet = f'<- {c[:50]}'
    elif 'status' in t:
        sr = e.get('stop_reason', {})
        snippet = f\"[{sr.get('type', '')}]\" if sr else ''
    elif t == 'user.tool_confirmation':
        snippet = f\"result={e.get('result', e.get('approved', '?'))}\"
    elif t == 'user.custom_tool_result':
        c = e.get('content', '')
        snippet = f'<- {str(c)[:50]}'
    print(f'    {i+1:2d}. {t:30s} {snippet}')
" 2>/dev/null || echo "    (parse error)"
}

# Count event types in a session
# count_events SESSION_ID EVENT_TYPE → prints count
count_events() {
    local SID="$1"
    local ETYPE="$2"
    curl -s "$API/sessions/$SID/events?limit=100" 2>/dev/null | python3 -c "
import sys, json
r = json.load(sys.stdin)
evts = r if isinstance(r, list) else r.get('events', r.get('data', []))
print(sum(1 for e in evts if e.get('type') == '$ETYPE'))
" 2>/dev/null || echo "0"
}

# Check if events contain a specific type → prints YES or NO
has_event_type() {
    local SID="$1"
    local ETYPE="$2"
    local COUNT
    COUNT=$(count_events "$SID" "$ETYPE")
    if [ "$COUNT" -gt 0 ] 2>/dev/null; then echo "YES"; else echo "NO"; fi
}

# Delete a resource silently
delete_resource() {
    local TYPE="$1"  # sessions, agents, environments, secrets
    local ID="$2"
    local EXTRA="${3:-}"  # e.g. "?force=true"
    curl -s -X DELETE "$API/${TYPE}/${ID}${EXTRA}" > /dev/null 2>&1 || true
}

# Print test summary
print_summary() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  SUMMARY"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo -e "  ${GREEN}$PASSED passed${NC}, ${RED}$FAILED failed${NC}, ${YELLOW}$WARNINGS warnings${NC}"
    echo ""
    if [ "$FAILED" -gt 0 ]; then
        return 1
    fi
    return 0
}
