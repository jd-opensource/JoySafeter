# shellcheck shell=bash

verification_require_metric_sample() {
    local body=$1 metric=$2 label=$3
    if ! printf '%s\n' "$body" | grep -Eq "^${metric}(\\{|[[:space:]])"; then
        log_error "$label 缺少指标样本: $metric"
        return 1
    fi
}

verify_orchestrator_metrics_contract() {
    local metrics=$1 failures=0 metric
    local required_metrics=(
        joysafeter_xds_enabled
        joysafeter_runner_setup_sent_total
        joysafeter_runner_setup_results_total
        joysafeter_runner_setup_failures_total
        joysafeter_runner_reconnect_setup_total
        joysafeter_runner_start_task_dispatched_total
    )

    for metric in "${required_metrics[@]}"; do
        verification_require_metric_sample "$metrics" "$metric" "orchestrator /metrics" \
            || failures=$((failures + 1))
    done
    [ "$failures" -eq 0 ]
}

verify_orchestrator_http_contract() {
    local fetcher=$1 xds_expectation=${2:-required}
    shift 2
    local fetcher_args=("$@")
    local live ready xds metrics

    live="$($fetcher ${fetcher_args[@]+"${fetcher_args[@]}"} /healthz/live)" || {
        log_error "orchestrator /healthz/live 不可用"
        return 1
    }
    [ "$live" = "ok" ] || {
        log_error "orchestrator /healthz/live 返回异常: ${live:-<empty>}"
        return 1
    }

    ready="$($fetcher ${fetcher_args[@]+"${fetcher_args[@]}"} /healthz/ready)" || {
        log_error "orchestrator /healthz/ready 不可用"
        return 1
    }
    [ "$ready" = "ok" ] || {
        log_error "orchestrator /healthz/ready 返回异常: ${ready:-<empty>}"
        return 1
    }

    case "$xds_expectation" in
        required)
            xds="$($fetcher ${fetcher_args[@]+"${fetcher_args[@]}"} /healthz/xds)" || {
                log_error "orchestrator /healthz/xds 不可用"
                return 1
            }
            [ "$xds" = "ready" ] || {
                log_error "orchestrator xDS authority 未 ready: ${xds:-<empty>}"
                return 1
            }
            ;;
        skip) ;;
        *)
            log_error "未知 xDS 验证模式: $xds_expectation"
            return 1
            ;;
    esac

    metrics="$($fetcher ${fetcher_args[@]+"${fetcher_args[@]}"} /metrics)" || {
        log_error "orchestrator /metrics 不可用"
        return 1
    }
    verify_orchestrator_metrics_contract "$metrics"
}

runtime_component_image_ref() {
    local component=$1 deploy_env=$2 record env_keys env_key configured old_ifs
    record="$(image_component_record "$component")" || return 1
    IFS='|' read -r _ _ _ _ _ _ _ _ env_keys _ <<< "$record"

    old_ifs=$IFS
    IFS=','
    for env_key in $env_keys; do
        configured="${!env_key:-}"
        if [ -z "$configured" ] && [ -f "$deploy_env" ]; then
            configured="$(read_env_value "$deploy_env" "$env_key")"
        fi
        if [ -n "$configured" ]; then
            IFS=$old_ifs
            printf '%s\n' "$configured"
            return 0
        fi
    done
    IFS=$old_ifs
    component_image_ref "$component"
}

runtime_image_inventory() {
    local deploy_env=$1 record component group
    while IFS= read -r record; do
        IFS='|' read -r component group _ <<< "$record"
        [ "$group" = runtime ] || continue
        printf '%s|%s\n' "$component" "$(runtime_component_image_ref "$component" "$deploy_env")"
    done < <(image_component_source_registry)
}

verify_local_runtime_images() {
    local deploy_env=$1 inventory component image failures=0
    if ! inventory="$(runtime_image_inventory "$deploy_env")"; then
        log_error "无法解析本地 Runtime 镜像库存"
        return 1
    fi
    if [ -z "$inventory" ]; then
        log_error "本地 Runtime 镜像库存为空"
        return 1
    fi
    while IFS='|' read -r component image; do
        if docker image inspect "$image" >/dev/null 2>&1; then
            log_success "Runtime 镜像可用: $component -> $image"
        else
            log_error "Runtime 镜像缺失: $component -> $image"
            failures=$((failures + 1))
        fi
    done <<< "$inventory"
    [ "$failures" -eq 0 ]
}
