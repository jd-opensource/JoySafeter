#!/usr/bin/env bash

set -euo pipefail
trap 'status=$?; printf "FAIL: unexpected command failure at line %s (exit %s)\n" "$LINENO" "$status" >&2; exit "$status"' ERR

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

helm_values_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/values.yaml")"
platform_chart="$DEPLOY_DIR/helm/joysafeter-platform"
platform_priority_class_source="$(cat "$platform_chart/templates/scheduling/production-priorityclass.yaml")"
event_stream_values_source="$(sed -n '/^  eventStream:/,/^  database:/p' "$DEPLOY_DIR/helm/joysafeter-orchestrator/values.yaml")"
helm_schema_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/values.schema.json")"
helm_dev_values_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/values-dev.yaml")"
helm_pre_values_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/values-pre.yaml")"
helm_prod_values_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/values-prod.yaml")"
helm_dev_images_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/images-dev.lock.yaml")"
helm_pre_images_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/images-pre.lock.yaml")"
helm_prod_images_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/images-prod.lock.yaml")"
runtime_rbac_template_source="$(cat \
    "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/orchestrator/role.yaml" \
    "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/agent-gateway/role.yaml")"
envoy_template_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/envoy/daemonset.yaml")"
network_policy_template_source="$(cat \
    "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/sandbox/networkpolicy.yaml" \
    "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/envoy/networkpolicy.yaml" \
    "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/orchestrator/networkpolicy.yaml" \
    "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/agent-gateway/networkpolicy.yaml")"
resource_quota_template_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/platform/resourcequota.yaml")"
agent_gateway_template_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/agent-gateway/deployment.yaml")"
orchestrator_configmap_source="$(cat "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/orchestrator/configmap.yaml")"
prometheus_rule_source="$(cat \
    "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/agent-gateway/prometheusrule.yaml" \
    "$DEPLOY_DIR/helm/joysafeter-orchestrator/templates/orchestrator/prometheusrule.yaml")"
images_capability_source="$(cat "$DEPLOY_DIR/lib/images.sh")"
deploy_entrypoint_source="$(cat "$DEPLOY_DIR/deploy.sh")"
runtime_dockerfile_source="$(cat "$DEPLOY_DIR/docker/runtime.Dockerfile")"
backend_dockerfile_source="$(cat "$DEPLOY_DIR/docker/backend.Dockerfile")"
frontend_dockerfile_source="$(cat "$DEPLOY_DIR/docker/frontend.Dockerfile")"
orchestrator_amd64_dockerfile_source="$(cat "$DEPLOY_DIR/docker/orchestrator-rs-amd64.Dockerfile")"
orchestrator_arm64_dockerfile_source="$(cat "$DEPLOY_DIR/docker/orchestrator-rs-arm64.Dockerfile")"
orchestrator_source_dockerfile_source="$(cat "$DEPLOY_DIR/docker/orchestrator-rs.Dockerfile")"
agent_gateway_dockerfile_source="$(cat "$DEPLOY_DIR/docker/agent-gateway.Dockerfile")"
assert_not_contains "$images_capability_source" 'docker buildx ls | grep -q "multiarch"'
assert_contains "$images_capability_source" 'docker buildx inspect multiarch'
assert_contains "$deploy_entrypoint_source" 'APT_MIRROR_BASE="${APT_MIRROR_BASE:-http://mirrors.ustc.edu.cn}"'
assert_contains "$deploy_entrypoint_source" 'ALPINE_MIRROR_BASE="${ALPINE_MIRROR_BASE:-https://mirrors.ustc.edu.cn/alpine}"'
assert_contains "$images_capability_source" 'APT_MIRROR_BASE=$APT_MIRROR_BASE'
assert_contains "$images_capability_source" 'ALPINE_MIRROR_BASE=$ALPINE_MIRROR_BASE'
assert_contains "$frontend_dockerfile_source" 'ARG ALPINE_MIRROR_BASE='
assert_contains "$frontend_dockerfile_source" '${ALPINE_MIRROR_BASE}'
assert_contains "$runtime_dockerfile_source" 'ARG APT_MIRROR_BASE='
assert_contains "$runtime_dockerfile_source" '${APT_MIRROR_BASE}/debian'
assert_contains "$runtime_dockerfile_source" '${APT_MIRROR_BASE}/ubuntu'
for debian_dockerfile_source in \
    "$backend_dockerfile_source" \
    "$orchestrator_amd64_dockerfile_source" \
    "$orchestrator_arm64_dockerfile_source" \
    "$orchestrator_source_dockerfile_source" \
    "$agent_gateway_dockerfile_source"; do
    assert_contains "$debian_dockerfile_source" 'ARG APT_MIRROR_BASE='
    assert_contains "$debian_dockerfile_source" '${APT_MIRROR_BASE}/debian'
    assert_not_contains "$debian_dockerfile_source" 'RUN apt-get update && apt-get install'
done
assert_contains "$runtime_dockerfile_source" 'CARGO_REGISTRIES_CRATES_IO_INDEX'
assert_contains "$runtime_dockerfile_source" '[source.crates-io]'
assert_contains "$runtime_dockerfile_source" 'replace-with = "runtime-mirror"'
assert_contains "$runtime_dockerfile_source" '--mount=type=cache,target=/usr/local/cargo/registry'
assert_contains "$runtime_dockerfile_source" '--mount=type=cache,target=/usr/local/cargo/git'
assert_contains "$helm_values_source" 'runnerAlerts:'
assert_contains "$prometheus_rule_source" 'JoySafeterRunnerSetupFailures'
assert_contains "$prometheus_rule_source" 'joysafeter_runner_setup_failures_total'
assert_contains "$prometheus_rule_source" 'JoySafeterRunnerReconnectRejected'
assert_contains "$prometheus_rule_source" 'joysafeter_runner_reconnect_setup_total{result="rejected"}'
assert_contains "$prometheus_rule_source" 'JoySafeterRunnerStaleSetupResults'
assert_contains "$prometheus_rule_source" 'joysafeter_runner_setup_stale_results_total'
assert_contains "$helm_pre_values_source" $'agentGateway:\n  replicas: 2'
assert_contains "$helm_prod_values_source" $'agentGateway:\n  replicas: 3'
assert_contains "$helm_dev_values_source" $'resourceQuota:\n  enabled: true'
assert_contains "$helm_pre_values_source" $'resourceQuota:\n  enabled: true'
assert_not_contains "$helm_dev_values_source" 'joysafeter.io/node-pool'
assert_not_contains "$helm_pre_values_source" 'joysafeter.io/node-pool'
assert_contains "$helm_pre_values_source" 'requestTimeoutSeconds: 25'
assert_contains "$helm_prod_values_source" 'requestTimeoutSeconds: 25'
assert_contains "$helm_dev_images_source" 'joysafeter-orchestrator-rs:dev'
assert_contains "$helm_dev_images_source" 'joysafeter-agent-gateway:dev'
assert_contains "$helm_dev_images_source" 'joysafeter-envoy:dev'
assert_contains "$helm_pre_images_source" 'joysafeter-orchestrator-rs:pre'
assert_contains "$helm_pre_images_source" 'joysafeter-agent-gateway:pre'
assert_contains "$helm_pre_images_source" 'joysafeter-envoy:pre'
assert_contains "$helm_prod_images_source" 'joysafeter-orchestrator-rs:prod'
assert_contains "$helm_prod_images_source" 'joysafeter-agent-gateway:prod'
assert_contains "$helm_prod_images_source" 'joysafeter-envoy:prod'
assert_not_contains "$helm_values_source" 'xdsLeaseName:'
assert_not_contains "$helm_values_source" $'  xds:\n    port:'
assert_not_contains "$helm_values_source" 'xdsMode:'
assert_not_contains "$helm_values_source" 'haMode:'
assert_not_contains "$helm_values_source" 'defaultMaxRetries:'
assert_not_contains "$helm_values_source" 'diskMb:'
assert_not_contains "$event_stream_values_source" 'group:'
assert_not_contains "$event_stream_values_source" 'batchSize:'
assert_not_contains "$event_stream_values_source" 'blockMs:'
assert_contains "$agent_gateway_template_source" 'agentGateway.enabled has been removed'
assert_contains "$agent_gateway_template_source" 'haMode has been removed'
assert_contains "$agent_gateway_template_source" 'the independent Agent Gateway architecture requires envoy.enabled=true'
assert_contains "$agent_gateway_template_source" 'agentGateway.requestTimeoutSeconds must be between'
assert_contains "$orchestrator_configmap_source" 'JOYSAFETER_AGENT_GATEWAY_REQUEST_TIMEOUT_SECS'
assert_contains "$orchestrator_configmap_source" 'JOYSAFETER_REDIS_QUEUE_PREFIX'
assert_contains "$orchestrator_configmap_source" 'JOYSAFETER_K8S_NODE_SELECTOR'
assert_contains "$orchestrator_configmap_source" 'JOYSAFETER_K8S_TOLERATIONS'
assert_not_contains "$orchestrator_configmap_source" 'JOYSAFETER_XDS_HOST'
assert_not_contains "$orchestrator_configmap_source" 'JOYSAFETER_XDS_LEADER_LEASE_NAME'
assert_not_contains "$orchestrator_configmap_source" 'JOYSAFETER_SANDBOX_DISK_MB'
assert_not_contains "$orchestrator_configmap_source" 'JOYSAFETER_TASK_DEFAULT_MAX_RETRIES'
assert_not_contains "$orchestrator_configmap_source" 'JOYSAFETER_EVENT_STREAM_GROUP'
assert_not_contains "$orchestrator_configmap_source" 'JOYSAFETER_EVENT_STREAM_BATCH_SIZE'
assert_not_contains "$orchestrator_configmap_source" 'JOYSAFETER_EVENT_STREAM_BLOCK_MS'
assert_contains "$helm_schema_source" '":latest($|@)"'
assert_contains "$runtime_rbac_template_source" 'resources: ["pods/exec"]'
assert_not_contains "$runtime_rbac_template_source" 'pods/log'
assert_not_contains "$runtime_rbac_template_source" 'pods/attach'
assert_not_contains "$runtime_rbac_template_source" 'resources: ["persistentvolumeclaims"]'
assert_not_contains "$runtime_rbac_template_source" 'resources: ["networkpolicies"]'
assert_contains "$envoy_template_source" '"address": "127.0.0.1"'
assert_not_contains "$envoy_template_source" '"address": "0.0.0.0"'
assert_contains "$envoy_template_source" 'exec 3<>/dev/tcp/127.0.0.1/9901'
assert_not_contains "$network_policy_template_source" 'namespaceSelector: {}'
assert_contains "$network_policy_template_source" 'kubernetes.io/metadata.name: kube-system'
assert_contains "$network_policy_template_source" 'ingressDeny:'
assert_contains "$network_policy_template_source" 'ingress: []'
assert_contains "$resource_quota_template_source" 'kind: ResourceQuota'
assert_contains "$platform_priority_class_source" 'kind: PriorityClass'
assert_contains "$platform_priority_class_source" 'name: joysafeter-production'
assert_contains "$platform_priority_class_source" 'globalDefault: false'

if command -v helm >/dev/null 2>&1; then
    helm lint "$platform_chart" >/dev/null
    platform_render="$(helm template joysafeter-platform "$platform_chart" \
        --namespace joysafeter-system)"
    assert_contains "$platform_render" 'kind: PriorityClass'
    assert_contains "$platform_render" 'name: joysafeter-production'
    assert_contains "$platform_render" 'value: 1000000'

    helm_chart="$DEPLOY_DIR/helm/joysafeter-orchestrator"
    immutable_images=(
        --set-string image.orchestrator=registry.test/orchestrator:v20260903
        --set-string image.agentGateway=registry.test/agent-gateway:v20260903
        --set-string image.envoy=registry.test/envoy:v1.37.1
        --set-string image.sandbox.claude=registry.test/claude:v20260903
        --set-string image.sandbox.codex=registry.test/codex:v20260903
        --set-string image.sandbox.native=registry.test/native:v20260903
        --set-string image.sandbox.pi=registry.test/pi:v20260903
    )
    pre_gateway_render="$(helm template pre "$helm_chart" \
        --namespace joysafeter-pre \
        -f "$helm_chart/values-pre.yaml" \
        "${immutable_images[@]}" \
        --show-only templates/agent-gateway/deployment.yaml)"
    prod_gateway_render="$(helm template prod "$helm_chart" \
        --namespace joysafeter-prod \
        -f "$helm_chart/values-prod.yaml" \
        "${immutable_images[@]}" \
        --show-only templates/agent-gateway/deployment.yaml)"
    assert_contains "$pre_gateway_render" $'name: joysafeter-agent-gateway\n  namespace: joysafeter-pre\nspec:\n  replicas: 2'
    assert_contains "$prod_gateway_render" $'name: joysafeter-agent-gateway\n  namespace: joysafeter-prod\nspec:\n  replicas: 3'

    if helm template mutable-pre "$helm_chart" \
        --namespace joysafeter-pre \
        -f "$helm_chart/values-pre.yaml" >/dev/null 2>&1; then
        fail 'Helm schema must reject latest image tags in pre'
    fi
    if helm template unpinned-pre "$helm_chart" \
        --namespace joysafeter-pre \
        -f "$helm_chart/values-pre.yaml" \
        "${immutable_images[@]}" \
        --set-string image.orchestrator=registry.test/orchestrator >/dev/null 2>&1; then
        fail 'Helm schema must reject untagged images in pre'
    fi
    if helm template unprioritized-prod "$helm_chart" \
        --namespace joysafeter-prod \
        -f "$helm_chart/values-prod.yaml" \
        "${immutable_images[@]}" \
        --set-string orchestrator.sandboxPlacement.priorityClassName= >/dev/null 2>&1; then
        fail 'Helm schema must reject production without sandbox PriorityClass'
    fi
    if helm template unbounded-pre "$helm_chart" \
        --namespace joysafeter-pre \
        -f "$helm_chart/values-pre.yaml" \
        "${immutable_images[@]}" \
        --set resourceQuota.enabled=false >/dev/null 2>&1; then
        fail 'Helm schema must require ResourceQuota in pre'
    fi
    if helm template prod-no-quota "$helm_chart" \
        --namespace joysafeter-prod \
        -f "$helm_chart/values-prod.yaml" \
        "${immutable_images[@]}" | grep -q '^kind: ResourceQuota$'; then
        fail 'Production must not render a ResourceQuota'
    fi

    if helm template invalid-envoy "$helm_chart" \
        --set envoy.enabled=false >/dev/null 2>&1; then
        fail 'Helm validation must reject Agent Gateway without Envoy'
    fi
    if helm template removed-gateway-switch "$helm_chart" \
        --set agentGateway.enabled=false >/dev/null 2>&1; then
        fail 'Helm validation must reject the removed Agent Gateway enablement switch'
    fi
    if helm template removed-ha-mode "$helm_chart" \
        --set haMode=leader >/dev/null 2>&1; then
        fail 'Helm validation must reject the removed Orchestrator leader mode'
    fi
    if helm template invalid-timeout "$helm_chart" \
        --set agentGateway.requestTimeoutSeconds=22 >/dev/null 2>&1; then
        fail 'Helm validation must reject a request timeout shorter than delivery + replication budget'
    fi
fi

complete_metrics='joysafeter_xds_enabled 1
joysafeter_runner_setup_sent_total 1
joysafeter_runner_setup_results_total{result="applied"} 1
joysafeter_runner_setup_failures_total{reason="ack_timeout"} 0
joysafeter_runner_reconnect_setup_total{result="accepted"} 1
joysafeter_runner_start_task_dispatched_total 1'
verify_orchestrator_metrics_contract "$complete_metrics"
if verify_orchestrator_metrics_contract 'joysafeter_xds_enabled 1' >/dev/null 2>&1; then
    fail 'metrics verification must reject missing Runner lifecycle metrics'
fi
help_only_metrics='# HELP joysafeter_xds_enabled Whether xDS is enabled.
# HELP joysafeter_runner_setup_sent_total Setup requests sent.
# HELP joysafeter_runner_setup_results_total Setup results received.
# HELP joysafeter_runner_setup_failures_total Setup failures.
# HELP joysafeter_runner_reconnect_setup_total Reconnect setup proofs.
# HELP joysafeter_runner_start_task_dispatched_total StartTask dispatches.'
if verify_orchestrator_metrics_contract "$help_only_metrics" >/dev/null 2>&1; then
    fail 'metrics verification must require metric samples, not HELP declarations'
fi

verification_fetch() {
    case "$1" in
        /healthz/live|/healthz/ready) printf 'ok\n' ;;
        /healthz/xds) printf 'ready\n' ;;
        /metrics) printf '%s\n' "$complete_metrics" ;;
        *) return 1 ;;
    esac
}
verify_orchestrator_http_contract verification_fetch required

verification_fetch_with_context() {
    [ "$1" = context-a ] || return 1
    [ "$2" = namespace-a ] || return 1
    [ "$3" = pod-a ] || return 1
    verification_fetch "$4"
}
verify_orchestrator_http_contract \
    verification_fetch_with_context required context-a namespace-a pod-a

gateway_metrics='joysafeter_xds_enabled 1
joysafeter_xds_authority_phase{phase="ready"} 1
joysafeter_xds_active_envoy_nodes 1
joysafeter_xds_pending_deliveries 0
joysafeter_agent_gateway_projected_sandboxes 1'
gateway_standby_metrics='joysafeter_xds_enabled 1
joysafeter_xds_authority_phase{phase="ready"} 0
joysafeter_xds_active_envoy_nodes 0
joysafeter_xds_pending_deliveries 0
joysafeter_agent_gateway_projected_sandboxes 0'
verify_agent_gateway_metrics_contract "$gateway_metrics"
if verify_agent_gateway_metrics_contract 'joysafeter_xds_enabled 1' >/dev/null 2>&1; then
    fail 'Agent Gateway metrics verification must reject an incomplete contract'
fi
gateway_verification_fetch() {
    [ "$1" = context-a ] || return 1
    [ "$2" = namespace-a ] || return 1
    [ "$3" = gateway-a ] || return 1
    [ "$4" = 9193 ] || return 1
    case "$5" in
        /health/live) printf 'live\n' ;;
        /health/ready) printf 'ready\n' ;;
        /metrics) printf '%s\n' "$gateway_metrics" ;;
        *) return 1 ;;
    esac
}
verify_agent_gateway_http_contract \
    gateway_verification_fetch context-a namespace-a gateway-a 9193

runtime_images="$(runtime_image_inventory "$TEST_TMP/nonexistent.env")"
assert_contains "$runtime_images" 'claudecode|joysafeter-claudecode:latest'
assert_contains "$runtime_images" 'codex|joysafeter-codex:latest'
assert_contains "$runtime_images" 'native|joysafeter-native:latest'
assert_contains "$runtime_images" 'pi|joysafeter-pi:latest'
if (
    runtime_image_inventory() { return 1; }
    verify_local_runtime_images "$TEST_TMP/nonexistent.env" >/dev/null 2>&1
); then
    fail 'local runtime verification must propagate inventory lookup failures'
fi

docker() {
    if [ "$1 $2 $3" = 'image inspect --format' ]; then
        printf '%s\n' "${TEST_IMAGE_ARCH:-arm64}"
        return 0
    fi
    return 1
}
TEST_IMAGE_ARCH=arm64
verify_local_image_platform test-image:latest linux/arm64
TEST_IMAGE_ARCH=amd64
if verify_local_image_platform test-image:latest linux/arm64 >/dev/null 2>&1; then
    fail 'local image verification must reject a mismatched target architecture'
fi
unset -f docker

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
[[ "$(printf '%s\n' "$registry_helm_keys" | sed '/^$/d' | wc -l | tr -d ' ')" == 6 ]] \
    || fail 'Image Registry must own exactly six Helm image keys'
assert_contains "$registry_helm_keys" 'image.orchestrator'
assert_contains "$registry_helm_keys" 'image.agentGateway'
assert_contains "$registry_helm_keys" 'image.sandbox.claude'
assert_contains "$registry_helm_keys" 'image.sandbox.codex'
assert_contains "$registry_helm_keys" 'image.sandbox.native'
assert_contains "$registry_helm_keys" 'image.sandbox.pi'

kubernetes_images="$(kubernetes_component_image_overrides)"
assert_contains "$kubernetes_images" 'image.orchestrator=registry.example.test/joysafeter/joysafeter-orchestrator-rs:runtime-v1'
assert_contains "$kubernetes_images" 'image.agentGateway=registry.example.test/joysafeter/joysafeter-agent-gateway:runtime-v1'
assert_contains "$kubernetes_images" 'image.sandbox.claude=registry.example.test/joysafeter/joysafeter-claudecode:runtime-v1'
assert_contains "$kubernetes_images" 'image.sandbox.codex=registry.example.test/joysafeter/joysafeter-codex:runtime-v1'
assert_contains "$kubernetes_images" 'image.sandbox.native=registry.example.test/joysafeter/joysafeter-native:runtime-v1'
assert_contains "$kubernetes_images" 'image.sandbox.pi=registry.example.test/joysafeter/joysafeter-pi:runtime-v1'
[[ "$(printf '%s\n' "$kubernetes_images" | wc -l | tr -d ' ')" == 6 ]] \
    || fail 'Kubernetes image overrides must contain exactly six owned images'

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
assert_contains "$helm_call" 'image.agentGateway=registry.example.test/joysafeter/joysafeter-agent-gateway:runtime-v1'
assert_contains "$helm_call" 'image.sandbox.claude=registry.example.test/joysafeter/joysafeter-claudecode:runtime-v1'
assert_contains "$helm_call" 'image.sandbox.codex=registry.example.test/joysafeter/joysafeter-codex:runtime-v1'
assert_contains "$helm_call" 'image.sandbox.native=registry.example.test/joysafeter/joysafeter-native:runtime-v1'
assert_contains "$helm_call" 'image.sandbox.pi=registry.example.test/joysafeter/joysafeter-pi:runtime-v1'

: > "$HELM_CALLS_FILE"
KUBECTL_CALLS_FILE="$TEST_TMP/kubectl-calls"
export KUBECTL_CALLS_FILE
kubernetes_kubectl() {
    printf '%s\n' "$*" >> "$KUBECTL_CALLS_FILE"
    return 0
}
run_kubernetes_command deploy --values "$DEPLOY_DIR/helm/joysafeter-orchestrator/values-pre.yaml"
assert_contains "$(cat "$KUBECTL_CALLS_FILE")" 'get secret joysafeter-secrets-pre -n joysafeter'

: > "$HELM_CALLS_FILE"
: > "$KUBECTL_CALLS_FILE"
kubernetes_kubectl() {
    if [[ "$*" == *'get deployment joysafeter-orchestrator'*'jsonpath='* ]]; then
        printf '%s\n' 'joysafeter-secrets-existing'
        return 0
    fi
    printf '%s\n' "$*" >> "$KUBECTL_CALLS_FILE"
    return 0
}
run_kubernetes_command deploy --reuse-values
assert_contains "$(cat "$KUBECTL_CALLS_FILE")" 'get secret joysafeter-secrets-existing -n joysafeter'

: > "$HELM_CALLS_FILE"
: > "$KUBECTL_CALLS_FILE"
run_kubernetes_command deploy --sync-images --reuse-values
helm_call="$(cat "$HELM_CALLS_FILE")"
assert_contains "$helm_call" 'upgrade'
assert_contains "$helm_call" '--reset-then-reuse-values'
assert_not_contains "$helm_call" '--reuse-values'
assert_contains "$helm_call" 'image.orchestrator=registry.example.test/joysafeter/joysafeter-orchestrator-rs:runtime-v1'
assert_contains "$helm_call" 'image.agentGateway=registry.example.test/joysafeter/joysafeter-agent-gateway:runtime-v1'

KUBE_READY_AUTHORITIES=1
KUBE_XDS_ENABLED=1
KUBE_LOGS_FAIL=false
KUBE_GATEWAY_ENABLED=false
KUBE_GATEWAY_REPLICAS=1
KUBE_GATEWAY_RUNNING=1
kubernetes_kubectl() {
    local joined="$*" pod url ready_value=0
    case "$joined" in
        *'get deployment joysafeter-agent-gateway'*'.spec.replicas'*)
            [ "$KUBE_GATEWAY_ENABLED" = true ] || return 1
            printf '%s\n' "$KUBE_GATEWAY_REPLICAS"
            ;;
        *'get deployment joysafeter-agent-gateway'*'containerPort'*)
            [ "$KUBE_GATEWAY_ENABLED" = true ] || return 1
            printf '9193\n'
            ;;
        *'rollout status'*) return 0 ;;
        *'get deployment joysafeter-orchestrator'*'availableReplicas'*) printf '2\n' ;;
        *'get daemonset joysafeter-envoy'*'numberAvailable'*) printf '2\n' ;;
        *'get daemonset joysafeter-envoy'*'desiredNumberScheduled'*) printf '2\n' ;;
        *'get pods'*'app=joysafeter-agent-gateway'*'status.phase'*)
            printf 'gateway-a\n'
            [ "$KUBE_GATEWAY_RUNNING" -ge 2 ] && printf 'gateway-b\n'
            [ "$KUBE_GATEWAY_RUNNING" -ge 3 ] && printf 'gateway-c\n'
            ;;
        *'get pods'*'status.phase'*) printf 'orchestrator-a\norchestrator-b\n' ;;
        *' exec '*)
            if [[ "$joined" == *gateway-a* ]]; then
                pod=gateway-a
            elif [[ "$joined" == *gateway-b* ]]; then
                pod=gateway-b
            elif [[ "$joined" == *gateway-c* ]]; then
                pod=gateway-c
            elif [[ "$joined" == *orchestrator-a* ]]; then
                pod=orchestrator-a
            else
                pod=orchestrator-b
            fi
            url="${!#}"
            case "$url" in
                */health/live) printf 'live\n' ;;
                */health/ready) printf 'ready\n' ;;
                */healthz/live|*/healthz/ready) printf 'ok\n' ;;
                */healthz/xds)
                    if [ "$KUBE_READY_AUTHORITIES" -gt 0 ] \
                        && { [ "$pod" = orchestrator-a ] || [ "$KUBE_READY_AUTHORITIES" -eq 2 ]; }; then
                        printf 'ready\n'
                    else
                        printf 'standby\n'
                    fi
                    ;;
                */metrics)
                    if [[ "$pod" == gateway-* ]]; then
                        if [ "$pod" = gateway-a ]; then
                            printf '%s\n' "${gateway_metrics/joysafeter_xds_active_envoy_nodes 1/joysafeter_xds_active_envoy_nodes 2}"
                        elif [ "$KUBE_READY_AUTHORITIES" -eq 2 ]; then
                            printf '%s\n' "$gateway_metrics"
                        else
                            printf '%s\n' "$gateway_standby_metrics"
                        fi
                        return 0
                    fi
                    if [ "$KUBE_READY_AUTHORITIES" -gt 0 ] \
                        && { [ "$pod" = orchestrator-a ] || [ "$KUBE_READY_AUTHORITIES" -eq 2 ]; }; then
                        ready_value=1
                    fi
                    printf '%s\n' "${complete_metrics/joysafeter_xds_enabled 1/joysafeter_xds_enabled $KUBE_XDS_ENABLED}"
                    printf 'joysafeter_xds_authority_phase{phase="ready"} %s\n' "$ready_value"
                    printf 'joysafeter_xds_active_envoy_nodes 2\n'
                    ;;
                *) return 1 ;;
            esac
            ;;
        *' logs '*) [ "$KUBE_LOGS_FAIL" = false ] ;;
        *) return 1 ;;
    esac
}
verify_output="$(kubernetes_verify verify-ns verify-context 10m 240s false 2>&1)"
assert_contains "$verify_output" 'xDS authority 副本全部 Ready: 1'
assert_contains "$verify_output" 'xDS active Envoy 节点数与 DaemonSet 一致: 2'

KUBE_READY_AUTHORITIES=2
if verify_output="$(kubernetes_verify verify-ns verify-context 10m 240s false 2>&1)"; then
    fail 'Kubernetes verification must reject multiple Ready xDS authorities'
fi
assert_contains "$verify_output" 'xDS Ready 副本数不匹配'

KUBE_READY_AUTHORITIES=0
KUBE_XDS_ENABLED=0
if verify_output="$(kubernetes_verify verify-ns verify-context 10m 240s false 2>&1)"; then
    fail 'Kubernetes verification must reject a disabled xDS control plane'
fi
assert_contains "$verify_output" 'xDS control plane 未启用'

KUBE_READY_AUTHORITIES=1
KUBE_XDS_ENABLED=1
KUBE_GATEWAY_ENABLED=true
KUBE_GATEWAY_REPLICAS=2
KUBE_GATEWAY_RUNNING=2
if ! verify_output="$(kubernetes_verify verify-ns verify-context 10m 240s false 2>&1)"; then
    printf '%s\n' "$verify_output" >&2
    fail 'Kubernetes verification must accept one Ready Agent Gateway authority'
fi
assert_contains "$verify_output" 'gateway-a Agent Gateway 健康与指标契约通过'
assert_contains "$verify_output" 'gateway-b Agent Gateway 健康与指标契约通过'
assert_contains "$verify_output" 'xDS authority 副本全部 Ready: 1'

KUBE_READY_AUTHORITIES=2
if verify_output="$(kubernetes_verify verify-ns verify-context 10m 240s false 2>&1)"; then
    fail 'Kubernetes verification must reject multiple Ready Agent Gateway authorities'
fi
assert_contains "$verify_output" 'xDS Ready 副本数不匹配'

KUBE_READY_AUTHORITIES=1
KUBE_GATEWAY_RUNNING=1
if verify_output="$(kubernetes_verify verify-ns verify-context 10m 240s false 2>&1)"; then
    fail 'Kubernetes verification must reject missing Agent Gateway replicas'
fi
assert_contains "$verify_output" 'Agent Gateway Running Pod 未达到期望副本数'

KUBE_GATEWAY_ENABLED=false
KUBE_GATEWAY_REPLICAS=1
KUBE_GATEWAY_RUNNING=1
KUBE_LOGS_FAIL=true
if verify_output="$(kubernetes_verify verify-ns verify-context 10m 240s false 2>&1)"; then
    fail 'Kubernetes verification must reject an unreadable orchestrator log stream'
fi
assert_contains "$verify_output" '无法读取 orchestrator 日志'
KUBE_LOGS_FAIL=false

kubernetes_runtime_image_inventory() { return 1; }
if kubernetes_verify_runtime_images verify-ns verify-context 240s >/dev/null 2>&1; then
    fail 'Kubernetes runtime verification must propagate inventory lookup failures'
fi

KUBE_VERIFY_ARGS_FILE="$TEST_TMP/kube-verify-args"
export KUBE_VERIFY_ARGS_FILE
kubernetes_verify() { printf '%s\n' "$*" > "$KUBE_VERIFY_ARGS_FILE"; }
run_kubernetes_command verify --namespace verify-ns --context verify-context --since 10m --timeout 240s --runtime-images
assert_contains "$(cat "$KUBE_VERIFY_ARGS_FILE")" 'verify-ns verify-context 10m 240s true'

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

COMPOSE_VERIFY_CWD_FILE="$TEST_TMP/compose-verify-cwd"
export COMPOSE_VERIFY_CWD_FILE
(
    validate_local_compose_config() { return 0; }
    compose_local_env() {
        pwd > "$COMPOSE_VERIFY_CWD_FILE"
        printf '%s\n' \
            joysafeter-envoy skillspector postgres redis api orchestrator-rs worker frontend
    }
    verify_orchestrator_http_contract() { return 0; }
    verify_local_runtime_images() { return 0; }
    run_local_verification >/dev/null
)
[[ "$(cat "$COMPOSE_VERIFY_CWD_FILE")" == "$DEPLOY_DIR" ]] \
    || fail 'local verification must execute Compose from deploy/'

VERIFY_CALLED_FILE="$TEST_TMP/verify-called"
export VERIFY_CALLED_FILE
run_local_verification() { printf 'called\n' > "$VERIFY_CALLED_FILE"; }
main verify
[[ "$(cat "$VERIFY_CALLED_FILE")" == "called" ]] \
    || fail 'verify command must route through the local verification capability'

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
