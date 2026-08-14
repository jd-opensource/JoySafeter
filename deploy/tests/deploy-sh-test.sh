#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

assert_contains() {
    [[ "$1" == *"$2"* ]] || fail "expected output to contain: $2"
}

assert_not_contains() {
    [[ "$1" != *"$2"* ]] || fail "expected output not to contain: $2"
}

# shellcheck source=../deploy.sh
source "$DEPLOY_DIR/deploy.sh"

grep -Eq '^  JOYSAFETER_ENVOY_SOCKET_HOST_DIR:' "$DEPLOY_DIR/docker-compose.yml" \
    || fail 'Compose must inject JOYSAFETER_ENVOY_SOCKET_HOST_DIR into backend services'

bundled_env="$TEST_TMP/bundled.env"
cat > "$bundled_env" <<'EOF'
POSTGRES_PASSWORD=current-secret
DATABASE_URL=postgresql+asyncpg://postgres:stale-secret@postgres:5432/joysafeter
EOF
bundled_output="$(validate_local_database_config "$bundled_env" 2>&1)"
assert_contains "$bundled_output" 'DATABASE_URL'
assert_contains "$bundled_output" 'POSTGRES_'
assert_not_contains "$bundled_output" 'current-secret'
assert_not_contains "$bundled_output" 'stale-secret'
[[ -z "$(read_env_value "$bundled_env" DATABASE_URL)" ]] \
    || fail 'legacy bundled DATABASE_URL must be removed'

external_env="$TEST_TMP/external.env"
cat > "$external_env" <<'EOF'
POSTGRES_PASSWORD=current-secret
DATABASE_URL=postgresql+asyncpg://external:other-secret@db.example.com:5432/joysafeter
EOF
if external_output="$(validate_local_database_config "$external_env" 2>&1)"; then
    fail 'external DATABASE_URL must be rejected for local Compose'
fi
assert_contains "$external_output" 'POSTGRES_'
assert_not_contains "$external_output" 'other-secret'

COMPOSE_CALLS_FILE="$TEST_TMP/compose-calls"
export COMPOSE_CALLS_FILE
COMPOSE_UP_RESULT=0
compose_local_env() {
    printf '%s\n' "$*" >> "$COMPOSE_CALLS_FILE"
    if [[ " $* " == *' up '* ]]; then
        return "$COMPOSE_UP_RESULT"
    fi
    return 0
}

success_output="$(LOCAL_COMPOSE_READY_TIMEOUT_SECONDS=240 start_local_compose 2>&1)"
assert_contains "$(cat "$COMPOSE_CALLS_FILE")" 'up -d --no-build --wait --wait-timeout 240'
assert_contains "$success_output" '本地 Compose 服务已启动并通过健康检查'

: > "$COMPOSE_CALLS_FILE"
COMPOSE_UP_RESULT=1
if failure_output="$(LOCAL_COMPOSE_READY_TIMEOUT_SECONDS=240 start_local_compose 2>&1)"; then
    fail 'readiness failure must return non-zero'
fi
assert_contains "$(cat "$COMPOSE_CALLS_FILE")" 'ps -a'
assert_contains "$failure_output" '未通过健康检查'
assert_not_contains "$failure_output" '本地 Compose 服务已启动并通过健康检查'

printf 'deploy-sh regression tests passed\n'
