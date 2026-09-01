#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

assert_contains() {
    [[ "$1" == *"$2"* ]] || fail "expected output to contain: $2"
}

source "$DEPLOY_DIR/deploy.sh"

leader_state=old
test_tmp="$(mktemp -d)"
trap 'rm -rf "$test_tmp"' EXIT
delete_calls_file="$test_tmp/delete-calls"
redis_delete_calls_file="$test_tmp/redis-delete-calls"
: > "$delete_calls_file"
: > "$redis_delete_calls_file"

sleep() { :; }
kubernetes_verify() { return 0; }
kubernetes_pod_http_get() {
    local pod=$3
    if [ "$pod" = orchestrator-old ]; then
        printf '%s\n' \
            'joysafeter_xds_authenticated_streams_total 8' \
            'joysafeter_xds_rejected_streams_total{reason="authority_unavailable"} 0'
    else
        printf '%s\n' 'joysafeter_xds_authenticated_streams_total 2'
    fi
}
kubernetes_kubectl() {
    local joined="$*"
    case "$joined" in
        *"get pods"*"joysafeter-xds-leader=true"*)
            if [ "$leader_state" = old ]; then
                printf 'orchestrator-old\n'
            else
                printf 'orchestrator-new\n'
            fi
            ;;
        *"get pod orchestrator-old"*"metadata.uid"*)
            if [ "$leader_state" = old ]; then
                printf 'uid-old\n'
            else
                return 1
            fi
            ;;
        *"delete pod orchestrator-old"*)
            leader_state=new
            printf 'delete\n' >> "$delete_calls_file"
            ;;
        *"rollout status deployment/joysafeter-orchestrator"*) return 0 ;;
        *"get pod orchestrator-new"*"status.podIP"*) printf '10.0.0.12\n' ;;
        *"get endpoints joysafeter-orchestrator-xds"*) printf '10.0.0.12\n' ;;
        *"get pods"*"app=redis-e2e"*) printf 'redis-e2e-0\n' ;;
        *"exec -n verify-ns redis-e2e-0 -- redis-cli HGET"*) printf '1788232824\n' ;;
        *"exec -n verify-ns redis-e2e-0 -- redis-cli DEL"*)
            printf 'delete\n' >> "$redis_delete_calls_file"
            printf '1\n'
            ;;
        *"exec -n verify-ns redis-e2e-0 -- redis-cli EXISTS"*) printf '1\n' ;;
        *"exec -n verify-ns redis-e2e-0 -- redis-cli TTL"*) printf '20\n' ;;
        *"exec -n verify-ns redis-e2e-0 -- redis-cli HLEN"*) printf '3\n' ;;
        *) fail "unexpected kubectl call: $joined" ;;
    esac
}

output="$(kubernetes_verify_failover verify-ns verify-context 10m 240s false)"
assert_contains "$output" 'old=orchestrator-old'
assert_contains "$output" 'new=orchestrator-new'
assert_contains "$output" 'new_authenticated=2'
assert_contains "$output" 'xDS authority 故障切换与 Envoy 重连验证通过'
[[ "$(wc -l < "$delete_calls_file" | tr -d ' ')" -eq 1 ]] \
    || fail "expected exactly one leader deletion"
[[ "$(wc -l < "$redis_delete_calls_file" | tr -d ' ')" -eq 1 ]] \
    || fail "expected exactly one Redis instance-key deletion"

failover_args=""
kubernetes_verify_failover() { failover_args="$*"; }
run_kubernetes_command verify --namespace verify-ns --context verify-context \
    --since 10m --timeout 240s --failover
[[ "$failover_args" = 'verify-ns verify-context 10m 240s false' ]] \
    || fail "--failover routing mismatch: $failover_args"

printf 'kubernetes failover regression tests passed\n'
