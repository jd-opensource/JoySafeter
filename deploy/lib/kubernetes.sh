# shellcheck shell=bash

kubernetes_usage() {
    cat <<EOF
使用方法: $0 k8s <命令> [选项]

命令:
  deploy              Helm 安装或升级
  uninstall           Helm 卸载
  verify              验证 Deployment、Envoy、健康/指标契约和 xDS authority
  scale REPLICAS      扩缩 orchestrator
  status              查看 orchestrator 与 Envoy 状态
  secrets             创建或更新 joysafeter-secrets

通用选项:
  --context NAME      Kubernetes context（默认使用当前 context）
  --namespace NAME    namespace（默认: joysafeter）
  --release NAME      Helm release（默认: joysafeter-orchestrator）

deploy 选项:
  --mode MODE         multi 或 leader（默认: multi）
  --replicas N        orchestrator 副本数
  -f, --values FILE   额外 values 文件
  --sync-images       从统一镜像 Registry 注入 orchestrator 和四个 runtime 镜像
  --reuse-values      升级时先加载新 chart 默认值，再复用 release 已有覆盖
  --timeout DURATION  Helm/rollout 超时（默认: 180s）
  --dry-run           仅用 helm template 渲染，不访问集群

verify 选项:
  --since DURATION    日志检查窗口（默认: 5m）
  --runtime-images    创建临时 Pod 验证四个 runtime 镜像可启动并自动清理

secrets 选项:
  --from-env          从当前环境读取 DATABASE_URL、REDIS_URL 和密钥
  --from-file FILE    从 env 文件读取上述三个值，不执行该文件

示例:
  $0 --registry registry.example.com/joysafeter --tag v1 k8s deploy --sync-images
  $0 k8s deploy --namespace joysafeter --values values.local.yaml
  $0 k8s verify --namespace joysafeter
  $0 k8s scale 3 --namespace joysafeter
  $0 k8s secrets --namespace joysafeter --from-env
EOF
}

kubernetes_kubectl() {
    local context=$1
    shift
    if [ -n "$context" ]; then
        kubectl --context "$context" "$@"
    else
        kubectl "$@"
    fi
}

kubernetes_helm() {
    local context=$1
    shift
    if [ -n "$context" ]; then
        helm --kube-context "$context" "$@"
    else
        helm "$@"
    fi
}

kubernetes_validate_replicas() {
    [[ "$1" =~ ^[0-9]+$ ]] || {
        log_error "replicas 必须是非负整数: $1"
        return 1
    }
}

kubernetes_component_image_overrides() {
    local record component helm_key
    while IFS= read -r record; do
        IFS='|' read -r component _ _ _ _ _ _ _ _ _ _ _ helm_key <<< "$record"
        [ "$helm_key" = - ] && continue
        printf '%s=%s\n' "$helm_key" "$(component_image_ref "$component")"
    done < <(image_component_source_registry)
}

kubernetes_external_secret_name() {
    local values_file=${1:-}
    local context=${2:-}
    local namespace=${3:-joysafeter}
    local reuse_values=${4:-false}
    local configured=""

    if [ -n "$values_file" ]; then
        configured="$(awk '
            /^externalSecret:[[:space:]]*/ {
                sub(/^externalSecret:[[:space:]]*/, "")
                sub(/[[:space:]]+#.*$/, "")
                gsub(/^[[:space:]"'\'' ]+|[[:space:]"'\'' ]+$/, "")
                print
                exit
            }
        ' "$values_file")"
    fi

    if [ -z "$configured" ] && [ "$reuse_values" = true ]; then
        configured="$(
            kubernetes_kubectl "$context" get deployment joysafeter-orchestrator \
                -n "$namespace" \
                -o 'jsonpath={.spec.template.spec.containers[?(@.name=="orchestrator")].envFrom[*].secretRef.name}' \
                2>/dev/null || true
        )"
        configured="${configured%% *}"
    fi

    printf '%s\n' "${configured:-joysafeter-secrets}"
}

kubernetes_deploy() {
    local namespace=$1 release=$2 context=$3 mode=$4 replicas=$5 values_file=$6 dry_run=$7 timeout=$8 sync_images=$9 reuse_values=${10}
    local chart_dir="$SCRIPT_DIR/helm/joysafeter-orchestrator"
    local external_secret
    local -a helm_args=()

    case "$mode" in
        multi|leader) ;;
        *) log_error "ha mode 只支持 multi 或 leader: $mode"; return 1 ;;
    esac
    if [ -n "$replicas" ]; then
        kubernetes_validate_replicas "$replicas"
    elif [ "$mode" = "leader" ]; then
        replicas=2
    fi
    if [ -n "$values_file" ] && [ ! -f "$values_file" ]; then
        log_error "values 文件不存在: $values_file"
        return 1
    fi

    check_command helm || return 1
    if [ "$dry_run" = true ]; then
        if [ "$reuse_values" = true ]; then
            log_error "--reuse-values 不能与 --dry-run 同时使用"
            return 1
        fi
        helm_args=(template "$release" "$chart_dir" --namespace "$namespace" --set "haMode=$mode")
        [ -n "$replicas" ] && helm_args+=(--set "orchestrator.replicas=$replicas")
        [ -n "$values_file" ] && helm_args+=(-f "$values_file")
        if [ "$sync_images" = true ]; then
            while IFS= read -r image_override; do
                helm_args+=(--set-string "$image_override")
            done < <(kubernetes_component_image_overrides)
        fi
        kubernetes_helm "$context" "${helm_args[@]}"
        return
    fi

    check_command kubectl || return 1
    external_secret="$(kubernetes_external_secret_name "$values_file" "$context" "$namespace" "$reuse_values")"
    if ! kubernetes_kubectl "$context" get secret "$external_secret" -n "$namespace" >/dev/null 2>&1; then
        log_error "namespace '$namespace' 中不存在 Secret '$external_secret'"
        log_error "请先创建该 Secret，或让 values 中的 externalSecret 指向已存在的 Secret"
        return 1
    fi

    helm_args=(upgrade --install "$release" "$chart_dir" --namespace "$namespace" --create-namespace --wait --timeout "$timeout" --set "haMode=$mode")
    [ "$reuse_values" = true ] && helm_args+=(--reset-then-reuse-values)
    [ -n "$replicas" ] && helm_args+=(--set "orchestrator.replicas=$replicas")
    [ -n "$values_file" ] && helm_args+=(-f "$values_file")
    if [ "$sync_images" = true ]; then
        while IFS= read -r image_override; do
            helm_args+=(--set-string "$image_override")
        done < <(kubernetes_component_image_overrides)
    fi

    kubernetes_helm "$context" "${helm_args[@]}"
    kubernetes_kubectl "$context" rollout status deployment/joysafeter-orchestrator -n "$namespace" --timeout="$timeout"
    kubernetes_status "$namespace" "$context"
}

kubernetes_uninstall() {
    local namespace=$1 release=$2 context=$3
    check_command helm || return 1
    kubernetes_helm "$context" uninstall "$release" -n "$namespace"
}

kubernetes_status() {
    local namespace=$1 context=$2
    check_command kubectl || return 1
    kubernetes_kubectl "$context" get deployment joysafeter-orchestrator -n "$namespace" -o wide
    kubernetes_kubectl "$context" get pods -n "$namespace" -l app=joysafeter-orchestrator -o wide
    kubernetes_kubectl "$context" get daemonset joysafeter-envoy -n "$namespace" -o wide
    kubernetes_kubectl "$context" get pods -n "$namespace" -l app=joysafeter-envoy -o wide
}

kubernetes_scale() {
    local namespace=$1 context=$2 replicas=$3 timeout=$4
    kubernetes_validate_replicas "$replicas"
    check_command kubectl || return 1
    kubernetes_kubectl "$context" scale deployment joysafeter-orchestrator -n "$namespace" --replicas="$replicas"
    kubernetes_kubectl "$context" rollout status deployment/joysafeter-orchestrator -n "$namespace" --timeout="$timeout"
}

kubernetes_pod_http_get() {
    local context=$1 namespace=$2 pod=$3 path=$4
    kubernetes_kubectl "$context" exec -n "$namespace" "$pod" -- \
        curl -fsS --max-time 5 "http://127.0.0.1:9091$path"
}

kubernetes_pod_http_body() {
    local context=$1 namespace=$2 pod=$3 path=$4
    kubernetes_kubectl "$context" exec -n "$namespace" "$pod" -- \
        curl -sS --max-time 5 "http://127.0.0.1:9091$path"
}

kubernetes_runtime_config_key() {
    case "$1" in
        claudecode) printf '%s\n' JOYSAFETER_IMAGE_CLAUDE ;;
        codex) printf '%s\n' JOYSAFETER_IMAGE_CODEX ;;
        native) printf '%s\n' JOYSAFETER_IMAGE_NATIVE ;;
        pi) printf '%s\n' JOYSAFETER_IMAGE_PI ;;
        *) return 1 ;;
    esac
}

kubernetes_runtime_image_inventory() {
    local namespace=$1 context=$2 record component group config_key image
    while IFS= read -r record; do
        IFS='|' read -r component group _ <<< "$record"
        [ "$group" = runtime ] || continue
        config_key="$(kubernetes_runtime_config_key "$component")" || return 1
        image="$(kubernetes_kubectl "$context" get configmap joysafeter-orchestrator-config \
            -n "$namespace" -o "go-template={{ index .data \"$config_key\" }}")" || return 1
        printf '%s|%s\n' "$component" "$image"
    done < <(image_component_source_registry)
}

kubernetes_verify_runtime_images() {
    local namespace=$1 context=$2 timeout=$3 inventory component image pod failures=0
    if ! inventory="$(kubernetes_runtime_image_inventory "$namespace" "$context")"; then
        log_error "无法读取 Kubernetes Runtime 镜像库存"
        return 1
    fi
    if [ -z "$inventory" ]; then
        log_error "Kubernetes Runtime 镜像库存为空"
        return 1
    fi
    while IFS='|' read -r component image; do
        if [ -z "$image" ]; then
            log_error "Kubernetes runtime 镜像配置为空: $component"
            failures=$((failures + 1))
            continue
        fi
        pod="joysafeter-image-check-${component}-$$"
        kubernetes_kubectl "$context" delete pod "$pod" -n "$namespace" \
            --ignore-not-found --wait=false >/dev/null 2>&1 || true
        if kubernetes_kubectl "$context" run "$pod" -n "$namespace" \
            --image="$image" --image-pull-policy=IfNotPresent --restart=Never \
            --command -- /bin/sh -c 'exit 0' >/dev/null \
            && kubernetes_kubectl "$context" wait -n "$namespace" \
                --for=jsonpath='{.status.phase}'=Succeeded "pod/$pod" --timeout="$timeout" >/dev/null; then
            log_success "Kubernetes runtime 镜像可启动: $component -> $image"
        else
            log_error "Kubernetes runtime 镜像验证失败: $component -> $image"
            kubernetes_kubectl "$context" describe pod "$pod" -n "$namespace" >&2 || true
            failures=$((failures + 1))
        fi
        kubernetes_kubectl "$context" delete pod "$pod" -n "$namespace" \
            --ignore-not-found --wait=false >/dev/null 2>&1 || true
    done <<< "$inventory"
    [ "$failures" -eq 0 ]
}

kubernetes_verify() {
    local namespace=$1 context=$2 since=$3 timeout=$4 check_runtime_images=${5:-false}
    local deployment_ready daemon_ready daemon_desired critical_count pod pods metrics xds_health orchestrator_logs
    local xds_enabled_count=0 xds_ready_count=0 xds_health_ready_count=0
    local authority_metrics="" active_envoy_nodes="" failures=0

    check_command kubectl || return 1
    kubernetes_kubectl "$context" rollout status deployment/joysafeter-orchestrator -n "$namespace" --timeout="$timeout" || failures=$((failures + 1))
    kubernetes_kubectl "$context" rollout status daemonset/joysafeter-envoy -n "$namespace" --timeout="$timeout" || failures=$((failures + 1))

    deployment_ready="$(kubernetes_kubectl "$context" get deployment joysafeter-orchestrator -n "$namespace" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true)"
    daemon_ready="$(kubernetes_kubectl "$context" get daemonset joysafeter-envoy -n "$namespace" -o jsonpath='{.status.numberAvailable}' 2>/dev/null || true)"
    daemon_desired="$(kubernetes_kubectl "$context" get daemonset joysafeter-envoy -n "$namespace" -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || true)"
    printf 'orchestrator available replicas: %s\n' "${deployment_ready:-0}"
    printf 'envoy available/desired: %s/%s\n' "${daemon_ready:-0}" "${daemon_desired:-0}"

    pods="$(kubernetes_kubectl "$context" get pods -n "$namespace" -l app=joysafeter-orchestrator -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.name}{"\n"}{end}')"
    if [ -z "$pods" ]; then
        log_error "没有 Running orchestrator Pod"
        failures=$((failures + 1))
    fi

    while IFS= read -r pod; do
        [ -z "$pod" ] && continue
        if verify_orchestrator_http_contract kubernetes_pod_http_get skip \
            "$context" "$namespace" "$pod"; then
            log_success "$pod 健康与指标契约通过"
        else
            failures=$((failures + 1))
            continue
        fi

        metrics="$(kubernetes_pod_http_get "$context" "$namespace" "$pod" /metrics)"
        if printf '%s\n' "$metrics" | grep -qxF 'joysafeter_xds_enabled 1'; then
            xds_enabled_count=$((xds_enabled_count + 1))
        fi
        if printf '%s\n' "$metrics" | grep -qxF 'joysafeter_xds_authority_phase{phase="ready"} 1'; then
            xds_ready_count=$((xds_ready_count + 1))
            authority_metrics="$metrics"
        fi
        xds_health="$(kubernetes_pod_http_body "$context" "$namespace" "$pod" /healthz/xds 2>/dev/null || true)"
        [ "$xds_health" = ready ] && xds_health_ready_count=$((xds_health_ready_count + 1))
    done <<< "$pods"

    if [ "$xds_enabled_count" -eq 0 ]; then
        log_error "xDS control plane 未启用"
        failures=$((failures + 1))
    else
        if [ "$xds_ready_count" -ne 1 ] || [ "$xds_health_ready_count" -ne 1 ]; then
            log_error "xDS authority 必须恰好一个 Ready：metrics=$xds_ready_count health=$xds_health_ready_count"
            failures=$((failures + 1))
        else
            log_success "xDS authority 唯一且 Ready"
        fi
    fi

    if [ -n "$authority_metrics" ] && [[ "${daemon_ready:-}" =~ ^[0-9]+$ ]]; then
        active_envoy_nodes="$(printf '%s\n' "$authority_metrics" | awk '$1 == "joysafeter_xds_active_envoy_nodes" {print $2; exit}')"
        if [ "$active_envoy_nodes" != "$daemon_ready" ]; then
            log_error "xDS active Envoy 节点与可用 DaemonSet Pod 不一致: ${active_envoy_nodes:-missing}/${daemon_ready}"
            failures=$((failures + 1))
        else
            log_success "xDS active Envoy 节点数与 DaemonSet 一致: $daemon_ready"
        fi
    fi

    if ! orchestrator_logs="$(kubernetes_kubectl "$context" logs -n "$namespace" \
        -l app=joysafeter-orchestrator --since="$since" 2>/dev/null)"; then
        log_error "无法读取 orchestrator 日志"
        failures=$((failures + 1))
    else
        critical_count="$(printf '%s\n' "$orchestrator_logs" \
            | grep -Eci 'panic|fatal|critical service exited' || true)"
        printf 'orchestrator critical log lines (%s): %s\n' "$since" "${critical_count:-0}"
        [ "${critical_count:-0}" -eq 0 ] || failures=$((failures + 1))
    fi

    if [ "$check_runtime_images" = true ]; then
        kubernetes_verify_runtime_images "$namespace" "$context" "$timeout" \
            || failures=$((failures + 1))
    fi

    if [ "$failures" -ne 0 ]; then
        log_error "Kubernetes 验证失败: $failures 项"
        return 1
    fi
    log_success "Kubernetes 部署验证通过"
}

kubernetes_apply_secrets() {
    local namespace=$1 context=$2 from_env=$3 from_file=$4
    local database_url redis_url vault_key namespace_manifest secret_manifest

    check_command kubectl || return 1
    if [ -n "$from_file" ]; then
        [ -f "$from_file" ] || { log_error "env 文件不存在: $from_file"; return 1; }
        database_url="$(read_env_value "$from_file" DATABASE_URL)"
        redis_url="$(read_env_value "$from_file" REDIS_URL)"
        vault_key="$(read_env_value "$from_file" JOYSAFETER_VAULT_ENCRYPTION_KEY)"
    elif [ "$from_env" = true ]; then
        database_url="${DATABASE_URL:-}"
        redis_url="${REDIS_URL:-}"
        vault_key="${JOYSAFETER_VAULT_ENCRYPTION_KEY:-}"
    else
        read -r -p "DATABASE_URL: " database_url
        read -r -p "REDIS_URL: " redis_url
        read -r -s -p "JOYSAFETER_VAULT_ENCRYPTION_KEY: " vault_key
        printf '\n'
    fi

    if [ -z "$database_url" ] || [ -z "$redis_url" ] || [ -z "$vault_key" ]; then
        log_error "DATABASE_URL、REDIS_URL 和 JOYSAFETER_VAULT_ENCRYPTION_KEY 均不能为空"
        return 1
    fi
    if ! vault_key_is_valid "$vault_key"; then
        log_error "JOYSAFETER_VAULT_ENCRYPTION_KEY 必须是 64 位 hex 或 base64 编码的 32 字节密钥"
        return 1
    fi

    namespace_manifest="$(kubernetes_kubectl "$context" create namespace "$namespace" --dry-run=client -o yaml)"
    printf '%s\n' "$namespace_manifest" | kubernetes_kubectl "$context" apply -f - >/dev/null
    secret_manifest="$(kubernetes_kubectl "$context" create secret generic joysafeter-secrets -n "$namespace" \
        --from-literal="DATABASE_URL=$database_url" \
        --from-literal="REDIS_URL=$redis_url" \
        --from-literal="JOYSAFETER_VAULT_ENCRYPTION_KEY=$vault_key" \
        --dry-run=client -o yaml)"
    printf '%s\n' "$secret_manifest" | kubernetes_kubectl "$context" apply -f - >/dev/null
    log_success "Secret 'joysafeter-secrets' 已应用到 namespace '$namespace'"
}

run_kubernetes_command() {
    local action="${1:-help}"
    [ "$#" -gt 0 ] && shift
    local namespace="${KUBE_NAMESPACE:-joysafeter}"
    local release="${HELM_RELEASE:-joysafeter-orchestrator}"
    local context="${KUBE_CONTEXT:-}"
    local mode="multi"
    local replicas=""
    local values_file=""
    local timeout="180s"
    local since="5m"
    local dry_run=false
    local sync_images=false
    local reuse_values=false
    local runtime_images=false
    local from_env=false
    local from_file=""

    while [ "$#" -gt 0 ]; do
        case "$1" in
            -h|--help) kubernetes_usage; return 0 ;;
            --context) context="$2"; shift 2 ;;
            --namespace) namespace="$2"; shift 2 ;;
            --release) release="$2"; shift 2 ;;
            --mode) mode="$2"; shift 2 ;;
            --replicas) replicas="$2"; shift 2 ;;
            -f|--values) values_file="$2"; shift 2 ;;
            --timeout) timeout="$2"; shift 2 ;;
            --since) since="$2"; shift 2 ;;
            --dry-run) dry_run=true; shift ;;
            --sync-images) sync_images=true; shift ;;
            --reuse-values) reuse_values=true; shift ;;
            --runtime-images) runtime_images=true; shift ;;
            --from-env) from_env=true; shift ;;
            --from-file) from_file="$2"; shift 2 ;;
            *)
                if [ "$action" = scale ] && [ -z "$replicas" ]; then
                    replicas="$1"
                    shift
                else
                    log_error "未知 k8s 选项: $1"
                    kubernetes_usage
                    return 1
                fi
                ;;
        esac
    done

    if { [ "$sync_images" = true ] || [ "$reuse_values" = true ]; } && [ "$action" != deploy ]; then
        log_error "--sync-images 和 --reuse-values 仅适用于 k8s deploy"
        return 1
    fi
    if [ "$runtime_images" = true ] && [ "$action" != verify ]; then
        log_error "--runtime-images 仅适用于 k8s verify"
        return 1
    fi

    case "$action" in
        help|-h|--help) kubernetes_usage ;;
        deploy) kubernetes_deploy "$namespace" "$release" "$context" "$mode" "$replicas" "$values_file" "$dry_run" "$timeout" "$sync_images" "$reuse_values" ;;
        uninstall) kubernetes_uninstall "$namespace" "$release" "$context" ;;
        verify) kubernetes_verify "$namespace" "$context" "$since" "$timeout" "$runtime_images" ;;
        scale)
            [ -n "$replicas" ] || { log_error "k8s scale 需要副本数"; return 1; }
            kubernetes_scale "$namespace" "$context" "$replicas" "$timeout"
            ;;
        status) kubernetes_status "$namespace" "$context" ;;
        secrets) kubernetes_apply_secrets "$namespace" "$context" "$from_env" "$from_file" ;;
        *)
            log_error "未知 k8s 命令: $action"
            kubernetes_usage
            return 1
            ;;
    esac
}
