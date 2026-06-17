#!/bin/bash
#
# E2E Parallel Session Multi-Turn Test
#
# Runs N sessions concurrently, each with multiple conversation turns,
# verifying context retention and session isolation under parallel load.
#
# Each session uses a unique name (Alice-1, Alice-2, ...) so we can
# verify that session contexts don't leak between each other.
#
# Usage:
#   ./scripts/e2e_session_parallel.sh [NUM_SESSIONS] [BASE_URL] [SECRET_REF] [ENV_REF]
#
# Examples:
#   ./scripts/e2e_session_parallel.sh 10
#   ./scripts/e2e_session_parallel.sh 10 http://jagents.jd.com deepseekv4pro_secret unrestricted
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NUM_SESSIONS="${1:-3}"
BASE_URL="${2:-${JOYSAFETER_URL:-http://localhost:8080}}"
BASE_URL="${BASE_URL%/}"
SECRET_REF="${3:-}"
ENV_REF="${4:-unrestricted_env}"
API_KEY="${JOYSAFETER_API_KEY:-${API_KEY:-}}"
CURL_AUTH_ARGS=()
if [ -n "$API_KEY" ]; then
    CURL_AUTH_ARGS=(-H "X-Api-Key: $API_KEY")
fi

if [ -n "${JOYSAFETER_API_BASE:-}" ]; then
    API="${JOYSAFETER_API_BASE%/}"
elif [[ "$BASE_URL" == */api/v1 || "$BASE_URL" == */api/v2 || "$BASE_URL" == */v1 || "$BASE_URL" == */v2 ]]; then
    API="$BASE_URL"
else
    API="${BASE_URL}/api/v2"
fi

ENGINE_KIND="${ENGINE_KIND:-claude}"

# Engine-kind defaults
case "$ENGINE_KIND" in
    codex) _DEFAULT_SECRET="codex-secret"; _DEFAULT_MODEL="" ;;
    *)     _DEFAULT_SECRET="opus4.6_secret"; _DEFAULT_MODEL="Claude-Opus-4.6" ;;
esac
SECRET_REF="${SECRET_REF:-$_DEFAULT_SECRET}"
MODEL_ID="${MODEL_ID:-$_DEFAULT_MODEL}"
MODEL_JSON=''
if [ -n "$MODEL_ID" ]; then
    MODEL_JSON=",\n        \"model\": \"$MODEL_ID\""
fi

TMPDIR_TEST=$(mktemp -d)
trap "rm -rf ${TMPDIR_TEST}" EXIT

BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  E2E Parallel Session Multi-Turn Test                    ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Sessions:    $NUM_SESSIONS"
echo "  API:         $API"
echo "  Engine:      $ENGINE_KIND"
echo "  Model:       $MODEL_ID"
echo "  Secret:      $SECRET_REF"
echo "  Environment: $ENV_REF"
if [ -n "$API_KEY" ]; then
    echo "  Auth:        X-Api-Key (${API_KEY:0:10}...)"
else
    echo "  Auth:        none (set JOYSAFETER_API_KEY or API_KEY if required)"
fi
echo ""

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
json_get() {
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d$1)" 2>/dev/null
}

send_event() {
    local sid="$1" msg="$2" label="${3:-}"
    local escaped
    escaped=$(printf '%s' "$msg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    local code body
    for attempt in $(seq 1 20); do
        body=$(curl -s -w "\n%{http_code}" -X POST "${API}/sessions/${sid}/events" \
            "${CURL_AUTH_ARGS[@]}" \
            -H "Content-Type: application/json" \
            -d "{\"events\":[{\"type\":\"user.message\",\"content\":[{\"type\":\"text\",\"text\":${escaped}}]}]}")
        code=$(echo "$body" | tail -1)
        body=$(echo "$body" | sed '$d')
        if [ "$code" = "201" ] || [ "$code" = "200" ]; then
            return 0
        elif [ "$code" = "409" ]; then
            echo -e "${CYAN}    [send_event ${label} attempt $attempt] 409 — session busy, retrying in 5s...${NC}" >&2
            sleep 5
        else
            echo -e "${RED}    [send_event ${label}] HTTP $code: $body${NC}" >&2
            return 1
        fi
    done
    echo -e "${RED}    [send_event ${label}] exhausted retries (last=$code)${NC}" >&2
    return 1
}

wait_session_idle() {
    local sid="$1" max_wait="${2:-60}" interval="${3:-4}"
    for _i in $(seq 1 "$max_wait"); do
        sleep "$interval"
        local state
        state=$(curl -sf "${CURL_AUTH_ARGS[@]}" "${API}/sessions/${sid}" 2>/dev/null || echo '{}')
        local status
        status=$(echo "$state" | json_get "['status']" 2>/dev/null || echo "?")
        if [ "$status" = "idle" ]; then
            local sr
            sr=$(echo "$state" | python3 -c "
import sys,json; s=json.load(sys.stdin); sr=s.get('stop_reason',{})
print(sr.get('type',''))" 2>/dev/null || echo "")
            if [ "$sr" = "end_turn" ]; then
                # Stabilization: agent may start tool calls after replying.
                # Double-check with increasing delays.
                local stable=true
                for _stab in 1 2 3; do
                    sleep 5
                    local recheck_status
                    recheck_status=$(curl -sf "${CURL_AUTH_ARGS[@]}" "${API}/sessions/${sid}" 2>/dev/null | json_get "['status']" 2>/dev/null || echo "?")
                    if [ "$recheck_status" != "idle" ]; then
                        stable=false
                        break
                    fi
                done
                if [ "$stable" = "true" ]; then
                    return 0
                fi
                # Session went back to running, continue polling
                continue
            elif [ "$sr" = "requires_action" ]; then
                local eid
                eid=$(echo "$state" | python3 -c "
import sys,json; s=json.load(sys.stdin)
print(s.get('stop_reason',{}).get('event_ids',[''])[0])" 2>/dev/null || echo "")
                if [ -n "$eid" ]; then
                    local etype
                    etype=$(curl -sf "${CURL_AUTH_ARGS[@]}" "${API}/sessions/${sid}/events?limit=50" 2>/dev/null | python3 -c "
import sys,json
r=json.load(sys.stdin)
evts=r if isinstance(r,list) else r.get('events',r.get('data',[]))
for e in evts:
    if e.get('id')=='$eid':
        print(e.get('type',''))
        break
else:
    print('')
" 2>/dev/null || echo "")
                    if [ "$etype" = "agent.custom_tool_use" ]; then
                        curl -sf -X POST "${API}/sessions/${sid}/events" \
                            "${CURL_AUTH_ARGS[@]}" \
                            -H "Content-Type: application/json" \
                            -d "{\"events\":[{\"type\":\"user.custom_tool_result\",\"tool_use_event_id\":\"$eid\",\"content\":\"OK\"}]}" >/dev/null 2>&1
                    else
                        curl -sf -X POST "${API}/sessions/${sid}/events" \
                            "${CURL_AUTH_ARGS[@]}" \
                            -H "Content-Type: application/json" \
                            -d "{\"events\":[{\"type\":\"user.tool_confirmation\",\"tool_use_id\":\"$eid\",\"result\":\"allow\"}]}" >/dev/null 2>&1
                    fi
                fi
                continue
            fi
        fi
    done
    return 1
}

get_last_agent_reply() {
    local sid="$1" retries="${2:-5}" interval="${3:-2}"
    local reply=""
    for _r in $(seq 1 "$retries"); do
        reply=$(curl -sf "${CURL_AUTH_ARGS[@]}" "${API}/sessions/${sid}/events?limit=200" 2>/dev/null | python3 -c "
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

# ──────────────────────────────────────────────────────────────
# Step 0: Health check
# ──────────────────────────────────────────────────────────────
echo -e "${BOLD}[0]${NC} Health check"
HTTP_CODE=$(curl -sf "${CURL_AUTH_ARGS[@]}" -o /dev/null -w '%{http_code}' "$API/health/live" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "  ${GREEN}✓${NC} JoySafeter reachable"
else
    echo -e "  ${RED}✗${NC} Cannot reach $API/health/live ($HTTP_CODE)"
    exit 1
fi

# ──────────────────────────────────────────────────────────────
# Step 1: Create environment + agent
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[1]${NC} Create environment + agent"

ENV_NAME="e2e-parallel-env-$$"
ENV_RESP=$(curl -sf -X POST "${API}/environments" \
    "${CURL_AUTH_ARGS[@]}" \
    -H "Content-Type: application/json" \
    -d "{
        \"name\": \"$ENV_NAME\",
        \"config\": {\"type\": \"cloud\", \"networking\": {\"type\": \"unrestricted\"}}
    }" 2>/dev/null || echo '{}')
ENV_ID=$(echo "$ENV_RESP" | json_get "['id']" 2>/dev/null || echo "")
if [ -n "$ENV_ID" ]; then
    echo -e "  ${GREEN}✓${NC} Environment: $ENV_NAME"
else
    echo -e "  ${RED}✗${NC} Environment creation failed"
    exit 1
fi

AGENT_NAME="e2e-parallel-$$"
AGENT_RESP=$(curl -sf -X POST "${API}/agents" \
    "${CURL_AUTH_ARGS[@]}" \
    -H "Content-Type: application/json" \
    -d "{
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
    }" 2>/dev/null || echo '{}')
AGENT_ID=$(echo "$AGENT_RESP" | json_get "['id']" 2>/dev/null || echo "")
if [ -n "$AGENT_ID" ]; then
    echo -e "  ${GREEN}✓${NC} Agent: $AGENT_NAME ($AGENT_ID)"
else
    echo -e "  ${RED}✗${NC} Agent creation failed"
    exit 1
fi

# ──────────────────────────────────────────────────────────────
# Step 2: Create N sessions
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[2]${NC} Create $NUM_SESSIONS sessions"

SESSION_IDS=()
for i in $(seq 1 "$NUM_SESSIONS"); do
    resp=$(curl -sf -X POST "${API}/sessions" \
        "${CURL_AUTH_ARGS[@]}" \
        -H "Content-Type: application/json" \
        -d "{\"agent\":\"$AGENT_ID\",\"environment_id\":\"$ENV_ID\"}" 2>/dev/null || echo '{}')
    sid=$(echo "$resp" | json_get "['id']" 2>/dev/null || echo "")
    if [ -n "$sid" ]; then
        SESSION_IDS+=("$sid")
    fi
done
echo -e "  ${GREEN}✓${NC} Created ${#SESSION_IDS[@]}/$NUM_SESSIONS sessions"

if [ "${#SESSION_IDS[@]}" -eq 0 ]; then
    echo -e "  ${RED}✗${NC} No sessions created"
    curl -sf "${CURL_AUTH_ARGS[@]}" -X DELETE "${API}/agents/${AGENT_ID}?force=true" >/dev/null 2>&1 || true
    curl -sf "${CURL_AUTH_ARGS[@]}" -X DELETE "${API}/environments/${ENV_ID}" >/dev/null 2>&1 || true
    exit 1
fi

# ──────────────────────────────────────────────────────────────
# Step 3: Run multi-turn conversations in parallel
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[3]${NC} Running ${#SESSION_IDS[@]} parallel multi-turn conversations"
echo -e "  ${DIM}Each session: 5 turns with context-dependent questions${NC}"
echo ""

NAMES=("Alice" "Bob" "Charlie" "Diana" "Eve" "Frank" "Grace" "Henry" "Iris" "Jack"
       "Kate" "Leo" "Mia" "Noah" "Olive" "Paul" "Quinn" "Ruby" "Sam" "Tina")

run_session() {
    local idx=$1
    local sid=$2
    local name="${NAMES[$(( (idx - 1) % ${#NAMES[@]} ))]}"
    local outfile="${TMPDIR_TEST}/session_${idx}.log"
    local resultfile="${TMPDIR_TEST}/session_${idx}.result"

    local t_passed=0 t_failed=0
    local turn_results=""

    log() { echo "[Session $idx/$name] $*" >> "$outfile"; }

    # Turn 1: Introduce name
    log "Turn 1: sending name introduction"
    send_event "$sid" "My name is ${name}. Remember it. Reply with just: Got it." "S${idx}T1"
    if wait_session_idle "$sid" 30 5; then
        local reply
        reply=$(get_last_agent_reply "$sid")
        log "Turn 1 reply: $reply"
        if echo "$reply" | grep -qi "got it"; then
            t_passed=$((t_passed + 1))
            turn_results="${turn_results}1:PASS "
        else
            t_failed=$((t_failed + 1))
            turn_results="${turn_results}1:FAIL "
        fi
    else
        t_failed=$((t_failed + 1))
        turn_results="${turn_results}1:TIMEOUT "
        log "Turn 1: timeout"
    fi

    # Turn 2: Unique math per session
    local num1=$(( idx * 7 + 3 ))
    local num2=$(( idx * 3 + 5 ))
    local expected=$(( num1 * num2 ))
    log "Turn 2: asking $num1 * $num2 = $expected"
    send_event "$sid" "What is ${num1} times ${num2}? Reply with just the number." "S${idx}T2"
    if wait_session_idle "$sid" 30 5; then
        local reply
        reply=$(get_last_agent_reply "$sid")
        log "Turn 2 reply: $reply"
        if echo "$reply" | grep -q "$expected"; then
            t_passed=$((t_passed + 1))
            turn_results="${turn_results}2:PASS "
        else
            t_failed=$((t_failed + 1))
            turn_results="${turn_results}2:FAIL($reply) "
        fi
    else
        t_failed=$((t_failed + 1))
        turn_results="${turn_results}2:TIMEOUT "
        log "Turn 2: timeout"
    fi

    # Turn 3: Recall name (KEY TEST)
    log "Turn 3: asking for name recall"
    send_event "$sid" "What is my name? Reply with just the name, nothing else." "S${idx}T3"
    if wait_session_idle "$sid" 30 5; then
        local reply
        reply=$(get_last_agent_reply "$sid")
        log "Turn 3 reply: $reply"
        if echo "$reply" | grep -qi "$name"; then
            t_passed=$((t_passed + 1))
            turn_results="${turn_results}3:PASS "
        else
            t_failed=$((t_failed + 1))
            turn_results="${turn_results}3:FAIL($reply) "
        fi
    else
        t_failed=$((t_failed + 1))
        turn_results="${turn_results}3:TIMEOUT "
        log "Turn 3: timeout"
    fi

    # Turn 4: Recall math answer from Turn 2
    log "Turn 4: asking to recall the multiplication result"
    send_event "$sid" "What was the result of the multiplication I asked you earlier? Reply with just the number." "S${idx}T4"
    if wait_session_idle "$sid" 30 5; then
        local reply
        reply=$(get_last_agent_reply "$sid")
        log "Turn 4 reply: $reply"
        if echo "$reply" | grep -q "$expected"; then
            t_passed=$((t_passed + 1))
            turn_results="${turn_results}4:PASS "
        else
            t_failed=$((t_failed + 1))
            turn_results="${turn_results}4:FAIL($reply) "
        fi
    else
        t_failed=$((t_failed + 1))
        turn_results="${turn_results}4:TIMEOUT "
        log "Turn 4: timeout"
    fi

    # Turn 5: Combine context - use name + math in one question
    log "Turn 5: combined context question"
    send_event "$sid" "Write a single sentence that includes my name and the multiplication result from earlier. Format: '{name} calculated {result}.'" "S${idx}T5"
    if wait_session_idle "$sid" 30 5; then
        local reply
        reply=$(get_last_agent_reply "$sid")
        log "Turn 5 reply: $reply"
        local has_name=0 has_num=0
        echo "$reply" | grep -qi "$name" && has_name=1
        echo "$reply" | grep -q "$expected" && has_num=1
        if [ $has_name -eq 1 ] && [ $has_num -eq 1 ]; then
            t_passed=$((t_passed + 1))
            turn_results="${turn_results}5:PASS "
        elif [ $has_name -eq 1 ] || [ $has_num -eq 1 ]; then
            t_passed=$((t_passed + 1))
            turn_results="${turn_results}5:PARTIAL "
        else
            t_failed=$((t_failed + 1))
            turn_results="${turn_results}5:FAIL "
        fi
    else
        t_failed=$((t_failed + 1))
        turn_results="${turn_results}5:TIMEOUT "
        log "Turn 5: timeout"
    fi

    # Get token usage
    local usage
    usage=$(curl -sf "${CURL_AUTH_ARGS[@]}" "${API}/sessions/${sid}" 2>/dev/null | python3 -c "
import sys,json; s=json.load(sys.stdin); u=s.get('usage',{})
print(u.get('input_tokens',0))" 2>/dev/null || echo "0")

    echo "${t_passed}|${t_failed}|${turn_results}|${name}|${usage}" > "$resultfile"
}

TS_START=$(date +%s)

for i in $(seq 1 "${#SESSION_IDS[@]}"); do
    sid="${SESSION_IDS[$((i-1))]}"
    run_session "$i" "$sid" &
done

echo -e "  ${YELLOW}→${NC} All $NUM_SESSIONS sessions launched, waiting..."
wait

TS_END=$(date +%s)
DURATION=$((TS_END - TS_START))

# ──────────────────────────────────────────────────────────────
# Step 4: Collect and display results
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[4]${NC} Results"
echo ""

TOTAL_PASSED=0
TOTAL_FAILED=0
TOTAL_TOKENS=0
CONTEXT_PASS=0
CONTEXT_FAIL=0

printf "  ${BOLD}%-4s %-10s %-8s %-8s %-45s %s${NC}\n" "#" "Name" "Passed" "Failed" "Turns" "Tokens"
printf "  %-4s %-10s %-8s %-8s %-45s %s\n" "----" "----------" "------" "------" "---------------------------------------------" "------"

for i in $(seq 1 "${#SESSION_IDS[@]}"); do
    resultfile="${TMPDIR_TEST}/session_${i}.result"
    if [ -f "$resultfile" ]; then
        IFS='|' read -r sp sf turns name tokens < "$resultfile"
        TOTAL_PASSED=$((TOTAL_PASSED + sp))
        TOTAL_FAILED=$((TOTAL_FAILED + sf))
        TOTAL_TOKENS=$((TOTAL_TOKENS + tokens))

        # Check Turn 3 (context retention)
        if echo "$turns" | grep -q "3:PASS"; then
            CONTEXT_PASS=$((CONTEXT_PASS + 1))
        else
            CONTEXT_FAIL=$((CONTEXT_FAIL + 1))
        fi

        local_color="$GREEN"
        [ "$sf" -gt 0 ] && local_color="$RED"

        printf "  ${local_color}%-4s${NC} %-10s %-8s %-8s %-45s %s\n" \
            "$i" "$name" "$sp/5" "$sf/5" "$turns" "${tokens}"
    else
        printf "  ${RED}%-4s${NC} %-10s %-8s %-8s %-45s %s\n" \
            "$i" "?" "0/5" "5/5" "NO RESULT" "0"
        TOTAL_FAILED=$((TOTAL_FAILED + 5))
        CONTEXT_FAIL=$((CONTEXT_FAIL + 1))
    fi
done

# ──────────────────────────────────────────────────────────────
# Step 5: Summary
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD} SUMMARY${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Sessions:              ${#SESSION_IDS[@]}"
echo "  Turns per session:     5"
echo "  Total turns:           $((TOTAL_PASSED + TOTAL_FAILED))"
echo "  Passed:                ${TOTAL_PASSED}"
echo "  Failed:                ${TOTAL_FAILED}"
echo "  Duration:              ${DURATION}s"
echo "  Total tokens:          ${TOTAL_TOKENS}"
echo ""
echo "  Context retention (Turn 3 — name recall):"
echo "    Passed: ${CONTEXT_PASS}/${#SESSION_IDS[@]}"
echo "    Failed: ${CONTEXT_FAIL}/${#SESSION_IDS[@]}"
echo ""

# ──────────────────────────────────────────────────────────────
# Step 6: Cleanup
# ──────────────────────────────────────────────────────────────
echo -e "${BOLD}[5]${NC} Cleanup"

for sid in "${SESSION_IDS[@]}"; do
    curl -sf "${CURL_AUTH_ARGS[@]}" -X DELETE "${API}/sessions/${sid}" >/dev/null 2>&1 || true
done
echo -e "  ${GREEN}✓${NC} ${#SESSION_IDS[@]} sessions deleted"

curl -sf "${CURL_AUTH_ARGS[@]}" -X DELETE "${API}/agents/${AGENT_ID}?force=true" >/dev/null 2>&1 || true
echo -e "  ${GREEN}✓${NC} Agent deleted"

curl -sf "${CURL_AUTH_ARGS[@]}" -X DELETE "${API}/environments/${ENV_ID}" >/dev/null 2>&1 || true
echo -e "  ${GREEN}✓${NC} Environment deleted"

echo ""
if [ "$TOTAL_FAILED" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}PASS${NC} — all ${TOTAL_PASSED} turns across ${#SESSION_IDS[@]} sessions completed successfully."
    exit 0
elif [ "$CONTEXT_FAIL" -eq 0 ]; then
    echo -e "  ${YELLOW}${BOLD}WARN${NC} — context retention OK (${CONTEXT_PASS}/${#SESSION_IDS[@]}), but ${TOTAL_FAILED} turns failed."
    exit 1
else
    echo -e "  ${RED}${BOLD}FAIL${NC} — ${CONTEXT_FAIL}/${#SESSION_IDS[@]} sessions lost context. ${TOTAL_FAILED} total turn failures."
    exit 1
fi
