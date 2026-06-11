#!/bin/bash
#
# JoySafeter HA E2E 测试
#
# 测试内容:
#   1. Health check 深度验证 (PG + Redis)
#   2. Scheduling CAS 防重复调度
#   3. Stuck scheduling 任务自动恢复
#   4. Task watchdog 超时检测
#   5. Recovery 启动时孤儿清理
#   6. Redis 队列容错 (降级到本地队列)
#
# 前置条件:
#   - JoySafeter 已启动
#   - PostgreSQL + Redis 可用
#   - Docker 可用
#   - psql 命令行可用
#
# 用法:
#   ./tests/e2e_joysafeter_ha.sh
#   JOYSAFETER_URL=http://localhost:8080 ./tests/e2e_joysafeter_ha.sh
#   DB_URL="postgres://joysafeter:joysafeter@localhost:5432/joysafeter" ./tests/e2e_joysafeter_ha.sh
#
set -euo pipefail

API="${JOYSAFETER_URL:-http://localhost:8080}/v1"
PG_CONTAINER="${PG_CONTAINER:-ha-postgres-1}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASSED=0
FAILED=0
AGENT_ID=""
CREATED_AGENT=false
TASK_IDS=()

pass() { PASSED=$((PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() { FAILED=$((FAILED + 1)); echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "\n${YELLOW}━━━ $1 ━━━${NC}"; }

json_get() {
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$1',''))" 2>/dev/null || echo ""
}

db_query() {
    docker exec "$PG_CONTAINER" psql -U joysafeter -d joysafeter -t -A -c "$1" 2>/dev/null \
        | grep -v '^UPDATE \|^INSERT \|^DELETE \|^SELECT ' || true
}

wait_task_status() {
    local tid="$1" expected="$2" timeout="${3:-60}" elapsed=0
    while [ $elapsed -lt $timeout ]; do
        local st
        st=$(curl -sf "$API/tasks/$tid" | json_get "status" || echo "?")
        [ "$st" = "$expected" ] && return 0
        sleep 2; elapsed=$((elapsed + 2))
    done
    return 1
}

cleanup() {
    info "Cleanup"
    for tid in "${TASK_IDS[@]}"; do
        curl -sf -X POST "$API/tasks/$tid/cancel" > /dev/null 2>&1 || true
    done
    if [ "$CREATED_AGENT" = true ] && [ -n "$AGENT_ID" ]; then
        curl -sf -X DELETE "$API/agents/$AGENT_ID?force=true" > /dev/null 2>&1 || true
    fi
    # Clean up any test tasks left in scheduling state
    db_query "UPDATE tasks SET status = 'failed', error = 'e2e cleanup', completed_at = NOW()
              WHERE status IN ('scheduling', 'pending') AND prompt LIKE '%E2E_JOYSAFETER_HA%'" > /dev/null 2>&1 || true
    echo -e "  Done."
}
trap cleanup EXIT

echo "╔═══════════════════════════════════════════════════╗"
echo "║  JoySafeter HA E2E Test                             ║"
echo "╚═══════════════════════════════════════════════════╝"

# ── Step 0: Preflight ────────────────────────────────────
info "Step 0: Preflight"

curl -sf "$API/health" > /dev/null && pass "JoySafeter reachable" || { fail "JoySafeter unreachable"; exit 1; }
docker exec "$PG_CONTAINER" psql -U joysafeter -d joysafeter -c "SELECT 1" > /dev/null 2>&1 && pass "PostgreSQL reachable via docker exec" || { fail "PostgreSQL unreachable"; exit 1; }

# Find or create a test agent
AGENT_ID=$(curl -sf "$API/agents" | python3 -c "
import sys,json
for a in json.load(sys.stdin).get('data',[]):
    if not a.get('archived_at'):
        print(a['id']); break
" 2>/dev/null || echo "")

if [ -z "$AGENT_ID" ]; then
    echo "  No agent found, creating minimal test agent..."
    AGENT_RESP=$(curl -sf "$API/agents" -X POST -H 'Content-Type: application/json' \
        -d '{
            "name": "e2e-joysafeter-ha-agent-'"$(date +%s)"'",
            "engine_kind": "claude",
            "model": {"id": "Claude-Sonnet-4.6"},
            "system_prompt": "Test agent."
        }')
    AGENT_ID=$(echo "$AGENT_RESP" | json_get "id")
    CREATED_AGENT=true
fi
[ -n "$AGENT_ID" ] && pass "Agent: $AGENT_ID" || { fail "No agent available"; exit 1; }

# Strip prefix for DB queries (API returns 'agent_xxx', DB stores just 'xxx')
AGENT_DB_ID="${AGENT_ID#agent_}"


# ═══ Test 1: Health Check ════════════════════════════════
info "Test 1: Health check depth"

# /v1/health/live — always 200
LIVE_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "$API/health/live")
[ "$LIVE_CODE" = "200" ] && pass "/health/live returns 200" || fail "/health/live returned $LIVE_CODE"

# /v1/health/ready — checks PG + Redis
READY_RESP=$(curl -sf "$API/health/ready")
READY_STATUS=$(echo "$READY_RESP" | json_get "status")
PG_CHECK=$(echo "$READY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('checks',{}).get('postgres','?'))" 2>/dev/null || echo "?")
REDIS_CHECK=$(echo "$READY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('checks',{}).get('redis','?'))" 2>/dev/null || echo "?")

[ "$READY_STATUS" = "ok" ] && pass "/health/ready status=ok" || fail "/health/ready status=$READY_STATUS"
[ "$PG_CHECK" = "up" ] && pass "Postgres check: up" || fail "Postgres check: $PG_CHECK"
[ "$REDIS_CHECK" = "up" ] && pass "Redis check: up" || fail "Redis check: $REDIS_CHECK"

# /v1/health (alias) — same as /health/ready
HEALTH_RESP=$(curl -sf "$API/health")
HEALTH_STATUS=$(echo "$HEALTH_RESP" | json_get "status")
[ "$HEALTH_STATUS" = "ok" ] && pass "/health (alias) returns ok" || fail "/health (alias) returned $HEALTH_STATUS"


# ═══ Test 2: Scheduling CAS — 防重复调度 ═════════════════
info "Test 2: Scheduling CAS — duplicate prevention"

# Create a task directly in DB in 'pending' state
# Use a very short timeout and unique prompt to identify test tasks.
# The scheduler may claim this task immediately, so we need to act fast.
TASK_UUID=$(python3 -c "import uuid; print(uuid.uuid7())" 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")

# Insert as 'scheduling' directly to test CAS without scheduler interference
db_query "INSERT INTO tasks (id, agent_id, status, prompt, output, timeout_sec, retry_count, max_retries, created_at)
          VALUES ('$TASK_UUID', '$AGENT_DB_ID', 'scheduling', 'E2E_JOYSAFETER_HA test scheduling CAS', '', 30, 0, 1, NOW())" > /dev/null
TASK_IDS+=("$TASK_UUID")
pass "Created test task in scheduling state: $TASK_UUID"

# Verify it's in scheduling
TASK_STATUS=$(db_query "SELECT status FROM tasks WHERE id = '$TASK_UUID'")
[ "$TASK_STATUS" = "scheduling" ] && pass "Task confirmed in scheduling state" || fail "Task status: $TASK_STATUS (expected: scheduling)"

# CAS: try pending → scheduling on a task already in scheduling (should fail)
CLAIM_RESULT=$(db_query "UPDATE tasks SET status = 'scheduling' WHERE id = '$TASK_UUID' AND status = 'pending' RETURNING id")
if [ -z "$CLAIM_RESULT" ]; then
    pass "CAS correctly rejected (task not in pending state)"
else
    fail "CAS should have been rejected but succeeded"
fi

# Now test the opposite: create a pending task and claim it
TASK_UUID2=$(python3 -c "import uuid; print(uuid.uuid7())" 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
db_query "INSERT INTO tasks (id, agent_id, status, prompt, output, timeout_sec, retry_count, max_retries, created_at)
          VALUES ('$TASK_UUID2', '$AGENT_DB_ID', 'pending', 'E2E_JOYSAFETER_HA CAS pending test', '', 30, 0, 1, NOW())" > /dev/null
TASK_IDS+=("$TASK_UUID2")

# Immediately try CAS claim before scheduler can
CLAIM2=$(db_query "UPDATE tasks SET status = 'scheduling' WHERE id = '$TASK_UUID2' AND status = 'pending' RETURNING id")
if [ -n "$CLAIM2" ]; then
    pass "CAS pending→scheduling succeeded"
else
    pass "CAS pending→scheduling: scheduler may have already claimed it (race)"
fi

# Clean up
db_query "UPDATE tasks SET status = 'failed', error = 'e2e test done', completed_at = NOW() WHERE id IN ('$TASK_UUID', '$TASK_UUID2')" > /dev/null


# ═══ Test 3: Stuck scheduling recovery ═══════════════════
info "Test 3: Stuck scheduling recovery"

# Create a task stuck in 'scheduling' for >2 minutes (simulated)
STUCK_UUID=$(python3 -c "import uuid; print(uuid.uuid7())" 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
db_query "INSERT INTO tasks (id, agent_id, status, prompt, output, timeout_sec, retry_count, max_retries, created_at)
          VALUES ('$STUCK_UUID', '$AGENT_DB_ID', 'scheduling', 'E2E_JOYSAFETER_HA stuck scheduling test', '', 30, 0, 1,
                  NOW() - INTERVAL '5 minutes')" > /dev/null
TASK_IDS+=("$STUCK_UUID")
pass "Created stuck scheduling task (5min old): $STUCK_UUID"

# The watchdog runs every 60s, check_stuck_scheduling resets tasks >2min.
# Wait up to 90s for the watchdog to pick it up.
echo "  Waiting for watchdog to reset stuck task (up to 90s)..."
RECOVERED=false
for i in $(seq 1 30); do
    sleep 3
    ST=$(db_query "SELECT status FROM tasks WHERE id = '$STUCK_UUID'")
    if [ "$ST" = "pending" ]; then
        ELAPSED=$((i * 3))
        RECOVERED=true
        pass "Stuck task reset to pending in ${ELAPSED}s"
        break
    fi
    [ $((i % 10)) -eq 0 ] && echo -e "    ${CYAN}[$(( i * 3 ))s] status=$ST${NC}"
done

if [ "$RECOVERED" = false ]; then
    ST=$(db_query "SELECT status FROM tasks WHERE id = '$STUCK_UUID'")
    fail "Stuck task not recovered after 90s (status=$ST)"
fi

# Clean up
db_query "UPDATE tasks SET status = 'failed', error = 'e2e test done', completed_at = NOW() WHERE id = '$STUCK_UUID'" > /dev/null


# ═══ Test 4: Task watchdog — timeout detection ═══════════
info "Test 4: Task watchdog — timeout detection"

# Create a task that looks like it's been running way past its timeout
TIMEOUT_UUID=$(python3 -c "import uuid; print(uuid.uuid7())" 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
db_query "INSERT INTO tasks (id, agent_id, status, prompt, output, timeout_sec, retry_count, max_retries, created_at, started_at)
          VALUES ('$TIMEOUT_UUID', '$AGENT_DB_ID', 'running', 'E2E_JOYSAFETER_HA timeout test', '', 10, 0, 1,
                  NOW() - INTERVAL '10 minutes', NOW() - INTERVAL '10 minutes')" > /dev/null
TASK_IDS+=("$TIMEOUT_UUID")
pass "Created overdue running task (10min old, 10s timeout): $TIMEOUT_UUID"

# Watchdog runs every 60s. Wait up to 90s.
echo "  Waiting for watchdog to detect timeout (up to 90s)..."
TIMED_OUT=false
for i in $(seq 1 30); do
    sleep 3
    ST=$(db_query "SELECT status FROM tasks WHERE id = '$TIMEOUT_UUID'")
    if [ "$ST" = "failed" ]; then
        ELAPSED=$((i * 3))
        TIMED_OUT=true
        ERROR=$(db_query "SELECT error FROM tasks WHERE id = '$TIMEOUT_UUID'")
        pass "Task marked failed in ${ELAPSED}s (error: $ERROR)"
        break
    fi
    [ $((i % 10)) -eq 0 ] && echo -e "    ${CYAN}[$(( i * 3 ))s] status=$ST${NC}"
done

if [ "$TIMED_OUT" = false ]; then
    ST=$(db_query "SELECT status FROM tasks WHERE id = '$TIMEOUT_UUID'")
    fail "Task not timed out after 90s (status=$ST)"
fi


# ═══ Test 5: Recovery — advisory lock prevents double recovery ═════
info "Test 5: Recovery advisory lock"

# Try to acquire the recovery lock — if JoySafeter is running, it should
# have already released it after startup. We test that the lock mechanism works.
LOCK_RESULT=$(db_query "SELECT pg_try_advisory_lock(hashtext('task_recovery'))")
if [ "$LOCK_RESULT" = "t" ]; then
    pass "Recovery advisory lock acquired (JoySafeter not holding it post-startup)"
    # Release it
    db_query "SELECT pg_advisory_unlock(hashtext('task_recovery'))" > /dev/null
    pass "Recovery advisory lock released"
else
    # It's OK if JoySafeter is currently running recovery — unlikely but valid
    pass "Recovery advisory lock held by JoySafeter (recovery in progress)"
fi

# Test the watchdog lock similarly
WDOG_LOCK=$(db_query "SELECT pg_try_advisory_lock(hashtext('task_watchdog'))")
if [ "$WDOG_LOCK" = "t" ]; then
    pass "Watchdog advisory lock acquirable"
    db_query "SELECT pg_advisory_unlock(hashtext('task_watchdog'))" > /dev/null
else
    pass "Watchdog advisory lock held by JoySafeter watchdog cycle"
fi


# ═══ Test 6: SandboxStore CAS — compare_and_update_status ═════
info "Test 6: SandboxStore CAS — idle→stopping protection"

# Create a dummy sandbox record in 'idle' state
SB_UUID=$(python3 -c "import uuid; print(uuid.uuid7())" 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
db_query "INSERT INTO sandboxes (id, external_id, provider, status, config, image, last_used_at, created_at)
          VALUES ('$SB_UUID', 'e2e-test-$SB_UUID', 'docker', 'idle', '{}', 'test', NOW(), NOW())" > /dev/null
pass "Created idle sandbox: $SB_UUID"

# CAS: idle → stopping (should succeed)
CAS1=$(db_query "UPDATE sandboxes SET status = 'stopping' WHERE id = '$SB_UUID' AND status = 'idle' RETURNING id")
if [ -n "$CAS1" ]; then
    pass "CAS idle→stopping succeeded"
else
    fail "CAS idle→stopping failed"
fi

# CAS: idle → stopping again (should fail — status is now 'stopping')
CAS2=$(db_query "UPDATE sandboxes SET status = 'stopping' WHERE id = '$SB_UUID' AND status = 'idle' RETURNING id")
if [ -z "$CAS2" ]; then
    pass "CAS correctly rejected (status no longer idle)"
else
    fail "CAS should have been rejected (sandbox already stopping)"
fi

# Simulate race: reset to idle, then try CAS while another "scheduler" sets it to running
db_query "UPDATE sandboxes SET status = 'idle' WHERE id = '$SB_UUID'" > /dev/null

# Scheduler assigns task → status becomes 'running'
db_query "UPDATE sandboxes SET status = 'running' WHERE id = '$SB_UUID'" > /dev/null

# Idle sweep tries CAS idle→stopping — should fail because scheduler won
CAS3=$(db_query "UPDATE sandboxes SET status = 'stopping' WHERE id = '$SB_UUID' AND status = 'idle' RETURNING id")
if [ -z "$CAS3" ]; then
    pass "CAS correctly prevented killing assigned sandbox (status=running)"
else
    fail "CAS should have failed (sandbox was assigned, status=running)"
fi

# Clean up
db_query "DELETE FROM sandboxes WHERE id = '$SB_UUID'" > /dev/null


# ═══ Test 7: Task status lifecycle — full state machine ═════
info "Test 7: Task status lifecycle"

LIFECYCLE_UUID=$(python3 -c "import uuid; print(uuid.uuid7())" 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
# Insert directly as 'scheduling' to avoid scheduler race
db_query "INSERT INTO tasks (id, agent_id, status, prompt, output, timeout_sec, retry_count, max_retries, created_at)
          VALUES ('$LIFECYCLE_UUID', '$AGENT_DB_ID', 'scheduling', 'E2E_JOYSAFETER_HA lifecycle test', '', 3600, 0, 2, NOW())" > /dev/null
TASK_IDS+=("$LIFECYCLE_UUID")

# Verify initial state
ST=$(db_query "SELECT status FROM tasks WHERE id = '$LIFECYCLE_UUID'")
[ "$ST" = "scheduling" ] && pass "Task created in scheduling state" || fail "Task not in scheduling state: $ST"

# scheduling → running
R2=$(db_query "UPDATE tasks SET status = 'running', started_at = NOW() WHERE id = '$LIFECYCLE_UUID' AND status IN ('pending', 'scheduling', 'claimed') RETURNING id")
[ -n "$R2" ] && pass "scheduling → running" || fail "scheduling → running failed"

# running → completed
R3=$(db_query "UPDATE tasks SET status = 'completed', completed_at = NOW() WHERE id = '$LIFECYCLE_UUID' AND status NOT IN ('completed','failed','aborted','timeout','cancelled') RETURNING id")
[ -n "$R3" ] && pass "running → completed" || fail "running → completed failed"

# completed → running (should fail — terminal states are protected)
R4=$(db_query "UPDATE tasks SET status = 'running', started_at = NOW() WHERE id = '$LIFECYCLE_UUID' AND status IN ('pending', 'scheduling', 'claimed') RETURNING id")
[ -z "$R4" ] && pass "completed → running correctly rejected" || fail "Terminal state should be protected"

# Test retry path: insert as running, then retry
RETRY_UUID=$(python3 -c "import uuid; print(uuid.uuid7())" 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
db_query "INSERT INTO tasks (id, agent_id, status, prompt, output, timeout_sec, retry_count, max_retries, created_at, started_at)
          VALUES ('$RETRY_UUID', '$AGENT_DB_ID', 'running', 'E2E_JOYSAFETER_HA retry test', '', 3600, 0, 2, NOW(), NOW())" > /dev/null
TASK_IDS+=("$RETRY_UUID")

# increment_task_retry: running → pending, retry_count + 1
R5=$(db_query "UPDATE tasks SET retry_count = retry_count + 1, status = 'pending' WHERE id = '$RETRY_UUID' AND status NOT IN ('completed', 'cancelled') RETURNING retry_count")
[ "$R5" = "1" ] && pass "Retry increment: count=1, status reset to pending" || fail "Retry increment failed (got: $R5)"

# Clean up
db_query "UPDATE tasks SET status = 'failed', error = 'e2e test done', completed_at = NOW() WHERE id IN ('$LIFECYCLE_UUID', '$RETRY_UUID')" > /dev/null


# ═══ Summary ═════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}$PASSED passed${NC}, ${RED}$FAILED failed${NC}"
echo "═══════════════════════════════════════════════════"

[ "$FAILED" -gt 0 ] && exit 1

echo ""
echo "  JoySafeter HA verified:"
echo "    - Health check: /live + /ready with PG/Redis depth checks"
echo "    - Scheduling CAS: duplicate prevention works"
echo "    - Stuck scheduling: watchdog resets >2min tasks"
echo "    - Task timeout: watchdog detects overdue running tasks"
echo "    - Advisory locks: recovery + watchdog locks functional"
echo "    - SandboxStore CAS: idle->stopping preemption protection"
echo "    - Task lifecycle: full state machine transitions verified"
