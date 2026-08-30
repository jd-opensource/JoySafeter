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

compose_source="$(cat "$DEPLOY_DIR/docker-compose.yml")"
assert_contains "$compose_source" 'JOYSAFETER_ENVOY_SOCKET_HOST_DIR: ""'
assert_contains "$compose_source" 'JOYSAFETER_ENVOY_SOCKET_VOLUME: ${JOYSAFETER_ENVOY_SOCKET_VOLUME:-${COMPOSE_PROJECT_NAME:-deploy}_joysafeter-sockets}'
assert_contains "$compose_source" 'name: ${JOYSAFETER_ENVOY_SOCKET_VOLUME:-${COMPOSE_PROJECT_NAME:-deploy}_joysafeter-sockets}'
assert_not_contains "$compose_source" '${JOYSAFETER_ENVOY_SOCKET_HOST_DIR:-/tmp/joysafeter-sockets}:${JOYSAFETER_ENVOY_SOCKET_HOST_DIR:-/tmp/joysafeter-sockets}'
grep -Eq '^!scripts/credential_encryption_rotation\.py$' "$DEPLOY_DIR/../backend/.dockerignore" \
    || fail 'Backend image must include the credential canary initialization command'

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

REGISTRY="registry.example.test/joysafeter"
TAG="runtime-v1"
registry_helm_keys="$(awk -F '\t' '!/^#/ && NF && $13 != "-" { print $13 }' "$DEPLOY_DIR/image-components.tsv")"
[[ "$(printf '%s\n' "$registry_helm_keys" | sed '/^$/d' | wc -l | tr -d ' ')" == 5 ]] \
    || fail 'Image Registry must own exactly five Helm image keys'
assert_contains "$registry_helm_keys" 'image.orchestrator'
assert_contains "$registry_helm_keys" 'image.sandbox.claude'
assert_contains "$registry_helm_keys" 'image.sandbox.codex'
assert_contains "$registry_helm_keys" 'image.sandbox.native'
assert_contains "$registry_helm_keys" 'image.sandbox.pi'

kubernetes_images="$(kubernetes_component_image_overrides)"
assert_contains "$kubernetes_images" 'image.orchestrator=registry.example.test/joysafeter/joysafeter-orchestrator-rs:runtime-v1'
assert_contains "$kubernetes_images" 'image.sandbox.claude=registry.example.test/joysafeter/joysafeter-claudecode:runtime-v1'
assert_contains "$kubernetes_images" 'image.sandbox.codex=registry.example.test/joysafeter/joysafeter-codex:runtime-v1'
assert_contains "$kubernetes_images" 'image.sandbox.native=registry.example.test/joysafeter/joysafeter-native:runtime-v1'
assert_contains "$kubernetes_images" 'image.sandbox.pi=registry.example.test/joysafeter/joysafeter-pi:runtime-v1'
[[ "$(printf '%s\n' "$kubernetes_images" | wc -l | tr -d ' ')" == 5 ]] \
    || fail 'Kubernetes image overrides must contain exactly five owned images'

HELM_CALLS_FILE="$TEST_TMP/helm-calls"
export HELM_CALLS_FILE
check_command() { return 0; }
kubernetes_helm() {
    printf '%s\n' "$@" > "$HELM_CALLS_FILE"
}
run_kubernetes_command deploy --dry-run --sync-images
helm_call="$(cat "$HELM_CALLS_FILE")"
assert_contains "$helm_call" '--set-string'
assert_contains "$helm_call" 'image.orchestrator=registry.example.test/joysafeter/joysafeter-orchestrator-rs:runtime-v1'
assert_contains "$helm_call" 'image.sandbox.claude=registry.example.test/joysafeter/joysafeter-claudecode:runtime-v1'
assert_contains "$helm_call" 'image.sandbox.codex=registry.example.test/joysafeter/joysafeter-codex:runtime-v1'
assert_contains "$helm_call" 'image.sandbox.native=registry.example.test/joysafeter/joysafeter-native:runtime-v1'
assert_contains "$helm_call" 'image.sandbox.pi=registry.example.test/joysafeter/joysafeter-pi:runtime-v1'

: > "$HELM_CALLS_FILE"
kubernetes_kubectl() { return 0; }
run_kubernetes_command deploy --sync-images --reuse-values
helm_call="$(cat "$HELM_CALLS_FILE")"
assert_contains "$helm_call" 'upgrade'
assert_contains "$helm_call" '--reset-then-reuse-values'
assert_not_contains "$helm_call" '--reuse-values'
assert_contains "$helm_call" 'image.orchestrator=registry.example.test/joysafeter/joysafeter-orchestrator-rs:runtime-v1'

DOWN_ARGS_FILE="$TEST_TMP/down-args"
export DOWN_ARGS_FILE
check_docker_running() { return 0; }
get_docker_platform() { printf '%s\n' 'linux/arm64'; }
run_down() { printf '%s\n' "$#" > "$DOWN_ARGS_FILE"; }
if ! down_output="$(main down 2>&1)"; then
    printf '%s\n' "$down_output" >&2
    fail 'down without service arguments must not fail under set -u'
fi
[[ "$(cat "$DOWN_ARGS_FILE")" == "0" ]] \
    || fail 'down without service arguments must pass zero arguments to run_down'

: > "$COMPOSE_CALLS_FILE"
COMPOSE_UP_RESULT=0
wait_for_local_redis() { return 0; }
verify_local_db_credentials() { return 0; }
run_local_migrations >/dev/null
migration_calls="$(cat "$COMPOSE_CALLS_FILE")"
assert_contains "$migration_calls" 'run --rm db-init'
assert_contains "$migration_calls" \
    'run --rm db-init python scripts/credential_encryption_rotation.py --initialize-missing-canaries'

printf 'deploy-sh regression tests passed\n'
