#!/bin/bash
set -euo pipefail

# ------------------------------------------------------------------
# E2E concurrency test for JoySafeter (with real LLM inference)
#
# Phases:
#   0. Health check
#   1. Concurrent health baseline
#   2. Create N agents with secret/env
#   3. Read pressure (concurrent GET /agents on the configured API base)
#   4. Submit N tasks with diverse prompts (coding, math, SQL, etc.)
#   5. Poll tasks to completion
#   6. Cleanup agents
#
# Usage:
#   ./scripts/e2e_concurrency.sh [CONCURRENCY] [BASE_URL] [SECRET_REF] [ENV_REF]
#
# Examples:
#   ./scripts/e2e_concurrency.sh 10
#   ./scripts/e2e_concurrency.sh 50 http://jagents.jd.com deepseekv4pro_secret unrestricted
#   ./scripts/e2e_concurrency.sh 100 http://localhost:8080 deepseekv4-pro-secret unrestricted_env
# ------------------------------------------------------------------

CONCURRENCY="${1:-3}"
BASE="${2:-${JOYSAFETER_URL:-http://localhost:8080}}"
BASE="${BASE%/}"
SECRET_REF="${3:-}"
ENV_REF="${4:-unrestricted_env}"
API_KEY="${JOYSAFETER_API_KEY:-${API_KEY:-}}"
CURL_AUTH_ARGS=()
if [ -n "$API_KEY" ]; then
  CURL_AUTH_ARGS=(-H "X-Api-Key: $API_KEY")
fi

if [ -n "${JOYSAFETER_API_BASE:-}" ]; then
  API="${JOYSAFETER_API_BASE%/}"
elif [[ "$BASE" == */api/v1 || "$BASE" == */api/v2 || "$BASE" == */v1 || "$BASE" == */v2 ]]; then
  API="$BASE"
else
  API="${BASE}/api/v2"
fi

ENGINE_KIND="${ENGINE_KIND:-claude}"

# Engine-kind defaults
case "$ENGINE_KIND" in
    codex) _DEFAULT_SECRET="codex-secret"; _DEFAULT_MODEL="" ;;
    *)     _DEFAULT_SECRET="deepseekv4-pro-secret"; _DEFAULT_MODEL="Claude-Opus-4.6" ;;
esac
SECRET_REF="${SECRET_REF:-$_DEFAULT_SECRET}"
MODEL_ID="${MODEL_ID:-$_DEFAULT_MODEL}"
TMPDIR_BENCH=$(mktemp -d)
trap "rm -rf ${TMPDIR_BENCH}" EXIT

now_ms() { python3 -c 'import time; print(int(time.time()*1000))'; }

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

header() { echo -e "\n${BOLD}${CYAN}[$1]${NC} $2"; }
ok()     { echo -e "  ${GREEN}✓${NC} $*"; }
fail()   { echo -e "  ${RED}✗${NC} $*"; }
info()   { echo -e "  ${YELLOW}→${NC} $*"; }

calc_stats() {
  local file="$1"
  local count total sorted
  count=$(wc -l < "$file" | tr -d ' ')
  if [ "$count" -eq 0 ]; then echo "  (no data)"; return; fi
  total=$(paste -sd+ "$file" | bc)
  sorted=$(sort -n "$file")
  local min max avg p50 p95 p99
  min=$(echo "$sorted" | head -1)
  max=$(echo "$sorted" | tail -1)
  avg=$(echo "scale=1; $total / $count" | bc)
  p50=$(echo "$sorted" | sed -n "$(echo "($count * 50 + 99) / 100" | bc)p")
  p95=$(echo "$sorted" | sed -n "$(echo "($count * 95 + 99) / 100" | bc)p")
  p99=$(echo "$sorted" | sed -n "$(echo "($count * 99 + 99) / 100" | bc)p")
  local qps="∞"
  [ "$(echo "$total > 0" | bc)" -eq 1 ] && qps=$(echo "scale=1; $count * 1000 / $total" | bc)
  printf "  requests: %d | avg: %sms | p50: %sms | p95: %sms | p99: %sms | min: %sms | max: %sms\n" \
    "$count" "$avg" "$p50" "$p95" "$p99" "$min" "$max"
  printf "  serial QPS (est): %s req/s\n" "$qps"
}

echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD} JoySafeter E2E Concurrency Test${NC}"
echo -e "   Concurrency:  ${CONCURRENCY}"
echo -e "   Target:       ${BASE}"
echo -e "   API:          ${API}"
echo -e "   Engine:       ${ENGINE_KIND}"
echo -e "   Model:        ${MODEL_ID}"
echo -e "   Secret:       ${SECRET_REF}"
echo -e "   Environment:  ${ENV_REF}"
if [ -n "$API_KEY" ]; then
  echo -e "   Auth:         X-Api-Key (${API_KEY:0:10}...)"
else
  echo -e "   Auth:         none (set JOYSAFETER_API_KEY or API_KEY if required)"
fi
echo -e "${BOLD}============================================${NC}"

# ==================================================================
# Phase 0: Health check
# ==================================================================
header "0" "Health check"
HTTP_CODE=$(curl -sf "${CURL_AUTH_ARGS[@]}" -o /dev/null -w '%{http_code}' "${API}/health/live" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  ok "JoySafeter is reachable (HTTP $HTTP_CODE)"
else
  fail "Cannot reach ${API}/health/live (HTTP $HTTP_CODE)"
  exit 1
fi

# ==================================================================
# Phase 1: Concurrent health endpoint (baseline)
# ==================================================================
header "1" "Baseline: ${CONCURRENCY} concurrent GET ${API}/health/live"

HEALTH_DIR="${TMPDIR_BENCH}/health"
mkdir -p "$HEALTH_DIR"

hit_health() {
  local i=$1
  local start_ms end_ms elapsed_ms code
  start_ms=$(now_ms)
  code=$(curl -sf "${CURL_AUTH_ARGS[@]}" -o /dev/null -w '%{http_code}' "${API}/health/live" 2>/dev/null || echo "000")
  end_ms=$(now_ms)
  elapsed_ms=$((end_ms - start_ms))
  echo "$elapsed_ms" > "${HEALTH_DIR}/${i}.ms"
  echo "$code" > "${HEALTH_DIR}/${i}.code"
}

for i in $(seq 1 "$CONCURRENCY"); do hit_health "$i" & done
wait

HEALTH_OK=0; HEALTH_FAIL=0
for i in $(seq 1 "$CONCURRENCY"); do
  c=$(cat "${HEALTH_DIR}/${i}.code" 2>/dev/null || echo "000")
  [ "$c" = "200" ] && HEALTH_OK=$((HEALTH_OK+1)) || HEALTH_FAIL=$((HEALTH_FAIL+1))
done
cat "${HEALTH_DIR}"/*.ms > "${TMPDIR_BENCH}/health_all.ms"

ok "${HEALTH_OK} succeeded, ${HEALTH_FAIL} failed"
calc_stats "${TMPDIR_BENCH}/health_all.ms"

# ==================================================================
# Phase 2: Create agents with secret + environment
# ==================================================================
header "2" "Create ${CONCURRENCY} agents (secret=${SECRET_REF}, env=${ENV_REF})"

AGENT_DIR="${TMPDIR_BENCH}/agents"
mkdir -p "$AGENT_DIR"

AGENT_BODY_TEMPLATE='{
  "name": "__NAME__",
  "engine_kind": "__ENGINE__",
  __MODEL_FIELD__
  "system_prompt": "You are a senior software engineer. Answer precisely and concisely. When writing code, write clean production-quality code without excessive comments. Do not use auto-memory. Do not write memory files or create notes about the conversation. Only use tools when the user explicitly asks you to run a command.",
  "secret_ref": "__SECRET__",
  "environment_ref": "__ENV__"
}'

MODEL_FIELD=''
if [ -n "$MODEL_ID" ]; then
  MODEL_FIELD="\"model\": {\"id\": \"$MODEL_ID\"},"
fi
SAMPLE_BODY=$(echo "$AGENT_BODY_TEMPLATE" | sed "s/__NAME__/bench-agent-1-$$/;s/__ENGINE__/${ENGINE_KIND}/;s#__MODEL_FIELD__#${MODEL_FIELD}#;s/__SECRET__/${SECRET_REF}/;s/__ENV__/${ENV_REF}/")
echo -e "  ${DIM}Sample request: POST ${API}/agents${NC}"
echo -e "  ${DIM}${SAMPLE_BODY}${NC}"

create_agent() {
  local i=$1
  local name="bench-agent-${i}-$$"
  local body
  body=$(echo "$AGENT_BODY_TEMPLATE" | sed "s/__NAME__/${name}/;s/__ENGINE__/${ENGINE_KIND}/;s#__MODEL_FIELD__#${MODEL_FIELD}#;s/__SECRET__/${SECRET_REF}/;s/__ENV__/${ENV_REF}/")
  local start_ms end_ms elapsed_ms
  start_ms=$(now_ms)
  local resp
  resp=$(curl -sf -X POST "${API}/agents" \
    "${CURL_AUTH_ARGS[@]}" \
    -H 'content-type: application/json' \
    -d "$body" 2>/dev/null || echo '{}')
  end_ms=$(now_ms)
  elapsed_ms=$((end_ms - start_ms))
  echo "$elapsed_ms" > "${AGENT_DIR}/${i}.ms"
  echo "$resp" > "${AGENT_DIR}/${i}.json"
}

for i in $(seq 1 "$CONCURRENCY"); do
  create_agent "$i" &
  if (( i % 50 == 0 )); then wait; fi
done
wait

AGENT_OK=0; AGENT_FAIL=0; AGENT_IDS=(); AGENT_NAMES=()
for i in $(seq 1 "$CONCURRENCY"); do
  aid=$(jq -r '.id // empty' "${AGENT_DIR}/${i}.json" 2>/dev/null || true)
  aname=$(jq -r '.name // empty' "${AGENT_DIR}/${i}.json" 2>/dev/null || true)
  if [ -n "$aid" ]; then
    AGENT_OK=$((AGENT_OK+1))
    AGENT_IDS+=("$aid")
    AGENT_NAMES+=("$aname")
  else
    AGENT_FAIL=$((AGENT_FAIL+1))
  fi
done
cat "${AGENT_DIR}"/*.ms > "${TMPDIR_BENCH}/agent_create_all.ms"

ok "${AGENT_OK} created, ${AGENT_FAIL} failed"
echo -e "  ${DIM}Sample response:${NC}"
jq -c '{id, name, secret_ref, environment_ref}' "${AGENT_DIR}/1.json" 2>/dev/null | sed "s/^/  ${DIM}/" | sed "s/$/${NC}/"
calc_stats "${TMPDIR_BENCH}/agent_create_all.ms"

# ==================================================================
# Phase 3: Read pressure
# ==================================================================
header "3" "Read pressure: ${CONCURRENCY} concurrent GET ${API}/agents"

LIST_DIR="${TMPDIR_BENCH}/list"
mkdir -p "$LIST_DIR"

list_agents() {
  local i=$1
  local start_ms end_ms elapsed_ms code
  start_ms=$(now_ms)
  code=$(curl -sf "${CURL_AUTH_ARGS[@]}" -o /dev/null -w '%{http_code}' "${API}/agents" 2>/dev/null || echo "000")
  end_ms=$(now_ms)
  elapsed_ms=$((end_ms - start_ms))
  echo "$elapsed_ms" > "${LIST_DIR}/${i}.ms"
  echo "$code" > "${LIST_DIR}/${i}.code"
}

for i in $(seq 1 "$CONCURRENCY"); do list_agents "$i" & done
wait

LIST_OK=0; LIST_FAIL=0
for i in $(seq 1 "$CONCURRENCY"); do
  c=$(cat "${LIST_DIR}/${i}.code" 2>/dev/null || echo "000")
  [ "$c" = "200" ] && LIST_OK=$((LIST_OK+1)) || LIST_FAIL=$((LIST_FAIL+1))
done
cat "${LIST_DIR}"/*.ms > "${TMPDIR_BENCH}/list_all.ms"

ok "${LIST_OK} succeeded, ${LIST_FAIL} failed"
calc_stats "${TMPDIR_BENCH}/list_all.ms"

# ==================================================================
# Phase 4: Submit tasks
# ==================================================================
header "4" "Submit ${CONCURRENCY} tasks concurrently"

if [ ${#AGENT_IDS[@]} -eq 0 ]; then
  fail "No agents available, skipping task test"
else
  TASK_DIR="${TMPDIR_BENCH}/tasks"
  mkdir -p "$TASK_DIR"
  NUM_AGENTS=${#AGENT_NAMES[@]}

  get_prompt() {
    local i=$1
    local idx=$(( (i - 1) % 10 ))
    case $idx in
      0) echo "Write a Python function that checks if a string is a valid IPv4 address. Include edge cases like leading zeros and values above 255. Show the code only, no explanation." ;;
      1) echo "A train leaves city A at 8:00 AM traveling at 90 km/h. Another train leaves city B (450 km away) at 9:00 AM traveling toward city A at 110 km/h. At what time do they meet? Show your step-by-step reasoning." ;;
      2) echo "Explain the difference between optimistic and pessimistic locking in databases. Give a concrete scenario where each is preferred. Keep it under 200 words." ;;
      3) echo "Write a bash one-liner that finds all files larger than 100MB in /var/log, sorts them by size descending, and shows the top 5 with human-readable sizes." ;;
      4) echo "Given a sorted array of integers with one duplicate, find the duplicate in O(log n) time. Write the solution in Python and explain the binary search approach." ;;
      5) echo "Design a rate limiter using the token bucket algorithm. Provide a Python class with methods refill() and allow_request(). Include thread safety." ;;
      6) echo "What are the trade-offs between using a B-tree index vs a hash index in PostgreSQL? When would you choose one over the other? Be specific with examples." ;;
      7) echo "Write a SQL query that finds the top 3 customers by total revenue in the last 30 days, including their most frequently purchased product category. Use CTEs for readability." ;;
      8) echo "Implement a simple LRU cache in Python with O(1) get and put operations. Use a doubly-linked list and a hash map. Show the complete implementation." ;;
      9) echo "A company has 5 servers. Each has 99.9%% uptime independently. What is the probability that at least 4 out of 5 are up at any given time? Show the binomial calculation." ;;
    esac
  }

  SAMPLE_PROMPT=$(get_prompt 1)
  echo -e "  ${DIM}Sample request: POST ${API}/tasks${NC}"
  echo -e "  ${DIM}{\"agent_name\":\"${AGENT_NAMES[0]}\",\"prompt\":\"${SAMPLE_PROMPT:0:80}...\",\"timeout_sec\":180,\"max_retries\":0}${NC}"
  echo -e "  ${DIM}(10 diverse prompts: coding, math, system design, SQL, algorithms)${NC}"

  submit_task() {
    local i=$1
    local aidx=$(( (i - 1) % NUM_AGENTS ))
    local aname="${AGENT_NAMES[$aidx]}"
    local prompt
    prompt=$(get_prompt "$i")
    local start_ms end_ms elapsed_ms
    local escaped_prompt
    escaped_prompt=$(printf '%s' "$prompt" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
    start_ms=$(now_ms)
    local resp
    resp=$(curl -sf -X POST "${API}/tasks" \
      "${CURL_AUTH_ARGS[@]}" \
      -H 'content-type: application/json' \
      -d "{
        \"agent_name\": \"${aname}\",
        \"prompt\": ${escaped_prompt},
        \"timeout_sec\": 180,
        \"max_retries\": 0
      }" 2>/dev/null || echo '{}')
    end_ms=$(now_ms)
    elapsed_ms=$((end_ms - start_ms))
    echo "$elapsed_ms" > "${TASK_DIR}/${i}.ms"
    echo "$resp" > "${TASK_DIR}/${i}.json"
  }

  TS_TASK_START=$(date +%s)

  for i in $(seq 1 "$CONCURRENCY"); do
    submit_task "$i" &
    if (( i % 50 == 0 )); then wait; info "submitted $i / $CONCURRENCY"; fi
  done
  wait

  TS_TASK_END=$(date +%s)
  TASK_SUBMIT_SEC=$((TS_TASK_END - TS_TASK_START))

  TASK_OK=0; TASK_FAIL=0; TASK_IDS=()
  for i in $(seq 1 "$CONCURRENCY"); do
    tid=$(jq -r '.id // empty' "${TASK_DIR}/${i}.json" 2>/dev/null || true)
    if [ -n "$tid" ]; then
      TASK_OK=$((TASK_OK+1))
      TASK_IDS+=("$tid")
    else
      TASK_FAIL=$((TASK_FAIL+1))
    fi
  done
  cat "${TASK_DIR}"/*.ms > "${TMPDIR_BENCH}/task_submit_all.ms"

  ok "${TASK_OK} accepted, ${TASK_FAIL} rejected (${TASK_SUBMIT_SEC}s)"
  echo -e "  ${DIM}Sample submit response:${NC}"
  jq -c '.' "${TASK_DIR}/1.json" 2>/dev/null | sed "s/^/  ${DIM}/" | sed "s/$/${NC}/"
  calc_stats "${TMPDIR_BENCH}/task_submit_all.ms"

  # ----------------------------------------------------------------
  # Phase 5: Poll tasks to completion
  # ----------------------------------------------------------------
  if [ "${#TASK_IDS[@]}" -gt 0 ]; then
    header "5" "Polling ${#TASK_IDS[@]} tasks to completion (max 10min)"

    POLL_INTERVAL=3
    MAX_WAIT=600
    STATUS_DIR="${TMPDIR_BENCH}/task_status"
    RESULT_DIR="${TMPDIR_BENCH}/task_result"
    mkdir -p "$STATUS_DIR" "$RESULT_DIR"

    is_terminal() {
      case "$1" in
        completed|failed|aborted|timeout|cancelled) return 0 ;;
        *) return 1 ;;
      esac
    }

    for tid in "${TASK_IDS[@]}"; do echo "pending" > "${STATUS_DIR}/${tid}"; done

    TS_POLL_START=$(date +%s)
    POLL_ROUNDS=$(( MAX_WAIT / POLL_INTERVAL ))

    for round in $(seq 1 "$POLL_ROUNDS"); do
      STILL=0
      C_pending=0; C_claimed=0; C_running=0; C_completed=0; C_failed=0; C_other=0

      for tid in "${TASK_IDS[@]}"; do
        cur=$(cat "${STATUS_DIR}/${tid}" 2>/dev/null || echo "pending")
        if ! is_terminal "$cur"; then
          full_resp=$(curl -sf "${CURL_AUTH_ARGS[@]}" "${API}/tasks/${tid}" 2>/dev/null || echo '{}')
          cur=$(echo "$full_resp" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
          echo "$cur" > "${STATUS_DIR}/${tid}"
          if is_terminal "$cur"; then
            echo "$full_resp" > "${RESULT_DIR}/${tid}.json"
          fi
        fi
        is_terminal "$cur" || STILL=$((STILL+1))
        case "$cur" in
          pending)   C_pending=$((C_pending+1)) ;;
          claimed)   C_claimed=$((C_claimed+1)) ;;
          running)   C_running=$((C_running+1)) ;;
          completed) C_completed=$((C_completed+1)) ;;
          failed)    C_failed=$((C_failed+1)) ;;
          *)         C_other=$((C_other+1)) ;;
        esac
      done

      ELAPSED=$(( $(date +%s) - TS_POLL_START ))
      printf "  [%3ds] pending=%d claimed=%d running=%d completed=%d failed=%d other=%d\n" \
        "$ELAPSED" "$C_pending" "$C_claimed" "$C_running" "$C_completed" "$C_failed" "$C_other"

      [ "$STILL" -eq 0 ] && break
      sleep "$POLL_INTERVAL"
    done

    TS_POLL_END=$(date +%s)
    TOTAL_SEC=$((TS_POLL_END - TS_TASK_START))

    F_completed=0; F_failed=0; F_timeout=0; F_other=0
    for tid in "${TASK_IDS[@]}"; do
      st=$(cat "${STATUS_DIR}/${tid}" 2>/dev/null || echo "unknown")
      case "$st" in
        completed) F_completed=$((F_completed+1)) ;;
        failed)    F_failed=$((F_failed+1)) ;;
        timeout)   F_timeout=$((F_timeout+1)) ;;
        *)         F_other=$((F_other+1)) ;;
      esac
    done

    # ----------------------------------------------------------
    # Print task request/response samples
    # ----------------------------------------------------------
    PROMPT_LABELS=(
      "IPv4 validator (Python)"
      "Train meeting time (math)"
      "Optimistic vs pessimistic lock"
      "Bash find large files"
      "Find duplicate O(logn) (Python)"
      "Token bucket rate limiter"
      "B-tree vs hash index (PG)"
      "Top customers SQL query"
      "LRU cache (Python)"
      "Server uptime probability"
    )

    echo ""
    echo -e "  ${BOLD}--- Task Results (all ${#TASK_IDS[@]} tasks) ---${NC}"
    IDX=0
    for tid in "${TASK_IDS[@]}"; do
      IDX=$((IDX+1))
      st=$(cat "${STATUS_DIR}/${tid}" 2>/dev/null || echo "unknown")
      label_idx=$(( (IDX - 1) % 10 ))
      label="${PROMPT_LABELS[$label_idx]}"
      if [ -f "${RESULT_DIR}/${tid}.json" ]; then
        output=$(jq -r '.output // "(none)"' "${RESULT_DIR}/${tid}.json" 2>/dev/null)
        error=$(jq -r '.error // "(none)"' "${RESULT_DIR}/${tid}.json" 2>/dev/null)
        sid=$(jq -r '.chat_session_id // empty' "${RESULT_DIR}/${tid}.json" 2>/dev/null)
        out_tokens=""
        if [ -n "$sid" ]; then
          out_tokens=$(curl -sf "${CURL_AUTH_ARGS[@]}" "${API}/sessions/${sid}/events" 2>/dev/null | \
            jq '[.data[] | select(.type=="span.model_request_end") | .usage.output_tokens // 0] | add // 0' 2>/dev/null || echo "?")
        fi
        output_preview="${output:0:60}"
        [ ${#output} -gt 60 ] && output_preview="${output_preview}..."
        if [ "$st" = "completed" ]; then
          printf "  ${GREEN}#%-2d${NC} %-10s │ %-33s │ out_tokens: %-5s │ %s\n" \
            "$IDX" "$st" "$label" "$out_tokens" "$output_preview"
        else
          printf "  ${RED}#%-2d${NC} %-10s │ %-33s │ error: %s\n" \
            "$IDX" "$st" "$label" "${error:0:60}"
        fi
      else
        printf "  ${YELLOW}#%-2d${NC} %-10s │ %-33s │ (no result)\n" \
          "$IDX" "$st" "$label"
      fi
    done

    # Show one full sample response
    SAMPLE_TID="${TASK_IDS[0]}"
    if [ -f "${RESULT_DIR}/${SAMPLE_TID}.json" ]; then
      echo ""
      echo -e "  ${BOLD}--- Sample full task response (task #1) ---${NC}"
      jq '{id, status, output, error, agent_id, chat_session_id, sandbox_id, started_at, completed_at}' \
        "${RESULT_DIR}/${SAMPLE_TID}.json" 2>/dev/null | sed 's/^/  /'

      SAMPLE_SID=$(jq -r '.chat_session_id // empty' "${RESULT_DIR}/${SAMPLE_TID}.json" 2>/dev/null)
      if [ -n "$SAMPLE_SID" ]; then
        echo ""
        echo -e "  ${BOLD}--- Sample session events (task #1) ---${NC}"
        curl -sf "${CURL_AUTH_ARGS[@]}" "${API}/sessions/${SAMPLE_SID}/events" 2>/dev/null | \
          jq '.data[] | {type, content: .content, usage: .usage, stop_reason: .stop_reason}' 2>/dev/null | sed 's/^/  /'
      fi
    fi
  else
    header "5" "No tasks accepted, skipping poll"
    TOTAL_SEC=$(($(date +%s) - TS_TASK_START))
  fi
fi

# ==================================================================
# Phase 6: Cleanup
# ==================================================================
DEL_OK=0; DEL_FAIL=0

if [ "${#AGENT_IDS[@]}" -gt 0 ]; then
  header "6" "Cleanup: delete ${#AGENT_IDS[@]} agents"

  DEL_DIR="${TMPDIR_BENCH}/delete"
  mkdir -p "$DEL_DIR"

  delete_agent() {
    local i=$1; local aid=$2
    local start_ms end_ms elapsed_ms code
    start_ms=$(now_ms)
    code=$(curl -sf "${CURL_AUTH_ARGS[@]}" -o /dev/null -w '%{http_code}' -X DELETE "${API}/agents/${aid}" 2>/dev/null || echo "000")
    end_ms=$(now_ms)
    elapsed_ms=$((end_ms - start_ms))
    echo "$elapsed_ms" > "${DEL_DIR}/${i}.ms"
    echo "$code" > "${DEL_DIR}/${i}.code"
  }

  IDX=0
  for aid in "${AGENT_IDS[@]}"; do
    IDX=$((IDX+1))
    delete_agent "$IDX" "$aid" &
    if (( IDX % 50 == 0 )); then wait; fi
  done
  wait

  for i in $(seq 1 "$IDX"); do
    c=$(cat "${DEL_DIR}/${i}.code" 2>/dev/null || echo "000")
    [ "$c" = "200" ] || [ "$c" = "204" ] && DEL_OK=$((DEL_OK+1)) || DEL_FAIL=$((DEL_FAIL+1))
  done
  cat "${DEL_DIR}"/*.ms > "${TMPDIR_BENCH}/delete_all.ms"

  ok "${DEL_OK} deleted, ${DEL_FAIL} failed"
  calc_stats "${TMPDIR_BENCH}/delete_all.ms"
else
  header "6" "Cleanup: no agents to delete"
fi

# ==================================================================
# Summary
# ==================================================================
echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD} SUMMARY${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""
echo "  Concurrency:          ${CONCURRENCY}"
echo "  Engine:               ${ENGINE_KIND}"
echo "  Model:                ${MODEL_ID}"
echo "  Secret:               ${SECRET_REF}"
echo "  Environment:          ${ENV_REF}"
echo "  Health (GET):         ${HEALTH_OK}/${CONCURRENCY} ok"
echo "  Agent create (POST):  ${AGENT_OK}/${CONCURRENCY} ok"
echo "  Agent list (GET):     ${LIST_OK}/${CONCURRENCY} ok"

if [ "${TASK_OK:-0}" -gt 0 ]; then
  echo "  Task submit (POST):   ${TASK_OK}/${CONCURRENCY} ok"
  echo "  Task results:"
  echo "    completed: ${F_completed:-0}  failed: ${F_failed:-0}  timeout: ${F_timeout:-0}  other: ${F_other:-0}"
  echo "  Task submit time:     ${TASK_SUBMIT_SEC}s"
  echo "  Total (submit+exec):  ${TOTAL_SEC}s"
  if [ "${F_completed:-0}" -gt 0 ]; then
    THROUGHPUT=$(echo "scale=2; ${F_completed} / ${TOTAL_SEC}" | bc)
    echo "  Throughput:           ${THROUGHPUT} tasks/s"
  fi
fi

echo "  Agent delete (DEL):   ${DEL_OK}/${#AGENT_IDS[@]} ok"
echo ""

if [ "${TASK_OK:-0}" -gt 0 ] && [ "${F_completed:-0}" -eq "${TASK_OK:-0}" ]; then
  echo -e "  ${GREEN}${BOLD}PASS${NC} — all tasks completed successfully."
  exit 0
elif [ "${TASK_OK:-0}" -eq 0 ]; then
  echo -e "  ${YELLOW}${BOLD}WARN${NC} — no tasks were submitted."
  exit 1
else
  echo -e "  ${YELLOW}${BOLD}WARN${NC} — ${F_completed:-0}/${TASK_OK:-0} completed. Check JoySafeter logs."
  if [ "${F_failed:-0}" -gt 0 ]; then
    echo ""; echo "  Sample failures (first 3):"; SHOWN=0
    for tid in "${TASK_IDS[@]}"; do
      st=$(cat "${STATUS_DIR}/${tid}" 2>/dev/null || echo "unknown")
      if [ "$st" = "failed" ] && [ $SHOWN -lt 3 ]; then
        ERR=$(jq -r '.error // "unknown"' "${RESULT_DIR}/${tid}.json" 2>/dev/null || echo "?")
        echo "    - ${ERR:0:200}"; SHOWN=$((SHOWN+1))
      fi
    done
  fi
  exit 1
fi
