# shellcheck shell=bash

kubernetes_usage() {
    cat <<EOF
使用方法: $0 k8s <命令> [选项]

命令:
  deploy              Helm 安装或升级
  uninstall           Helm 卸载
  verify              验证 Deployment、Envoy 和 readiness
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
  --timeout DURATION  Helm/rollout 超时（默认: 180s）
  --dry-run           仅用 helm template 渲染，不访问集群

verify 选项:
  --since DURATION    日志检查窗口（默认: 5m）

secrets 选项:
  --from-env          从当前环境读取 DATABASE_URL、REDIS_URL 和密钥
  --from-file FILE    从 env 文件读取上述三个值，不执行该文件

示例:
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

kubernetes_deploy() {
    local namespace=$1 release=$2 context=$3 mode=$4 replicas=$5 values_file=$6 dry_run=$7 timeout=$8
    local chart_dir="$SCRIPT_DIR/helm/joysafeter-orchestrator"
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
        helm_args=(template "$release" "$chart_dir" --namespace "$namespace" --set "haMode=$mode")
        [ -n "$replicas" ] && helm_args+=(--set "orchestrator.replicas=$replicas")
        [ -n "$values_file" ] && helm_args+=(-f "$values_file")
        kubernetes_helm "$context" "${helm_args[@]}"
        return
    fi

    check_command kubectl || return 1
    if ! kubernetes_kubectl "$context" get secret joysafeter-secrets -n "$namespace" >/dev/null 2>&1; then
        log_error "namespace '$namespace' 中不存在 Secret 'joysafeter-secrets'"
        log_error "请先运行: $0 k8s secrets --namespace $namespace --from-env"
        return 1
    fi

    helm_args=(upgrade --install "$release" "$chart_dir" --namespace "$namespace" --create-namespace --wait --timeout "$timeout" --set "haMode=$mode")
    [ -n "$replicas" ] && helm_args+=(--set "orchestrator.replicas=$replicas")
    [ -n "$values_file" ] && helm_args+=(-f "$values_file")

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

kubernetes_verify() {
    local namespace=$1 context=$2 since=$3 timeout=$4
    local deployment_ready daemon_ready daemon_desired error_count pod health failures=0

    check_command kubectl || return 1
    kubernetes_kubectl "$context" rollout status deployment/joysafeter-orchestrator -n "$namespace" --timeout="$timeout" || failures=$((failures + 1))
    kubernetes_kubectl "$context" rollout status daemonset/joysafeter-envoy -n "$namespace" --timeout="$timeout" || failures=$((failures + 1))

    deployment_ready="$(kubernetes_kubectl "$context" get deployment joysafeter-orchestrator -n "$namespace" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true)"
    daemon_ready="$(kubernetes_kubectl "$context" get daemonset joysafeter-envoy -n "$namespace" -o jsonpath='{.status.numberAvailable}' 2>/dev/null || true)"
    daemon_desired="$(kubernetes_kubectl "$context" get daemonset joysafeter-envoy -n "$namespace" -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || true)"
    printf 'orchestrator available replicas: %s\n' "${deployment_ready:-0}"
    printf 'envoy available/desired: %s/%s\n' "${daemon_ready:-0}" "${daemon_desired:-0}"

    while IFS= read -r pod; do
        [ -z "$pod" ] && continue
        health="$(kubernetes_kubectl "$context" exec -n "$namespace" "$pod" -- sh -c 'curl -fsS http://localhost:9091/healthz/ready' 2>/dev/null || true)"
        printf '%s readiness: %s\n' "$pod" "${health:-FAILED}"
        [ -n "$health" ] || failures=$((failures + 1))
    done < <(kubernetes_kubectl "$context" get pods -n "$namespace" -l app=joysafeter-orchestrator -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.name}{"\n"}{end}')

    error_count="$(kubernetes_kubectl "$context" logs -n "$namespace" -l app=joysafeter-orchestrator --since="$since" 2>/dev/null | grep -ci error || true)"
    printf 'orchestrator error lines (%s): %s\n' "$since" "${error_count:-0}"
    [ "${error_count:-0}" -le 10 ] || failures=$((failures + 1))

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

    case "$action" in
        help|-h|--help) kubernetes_usage ;;
        deploy) kubernetes_deploy "$namespace" "$release" "$context" "$mode" "$replicas" "$values_file" "$dry_run" "$timeout" ;;
        uninstall) kubernetes_uninstall "$namespace" "$release" "$context" ;;
        verify) kubernetes_verify "$namespace" "$context" "$since" "$timeout" ;;
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
