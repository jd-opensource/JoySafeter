# shellcheck shell=bash

DEVELOPMENT_PIDS=()

development_cleanup() {
    local pid
    for pid in "${DEVELOPMENT_PIDS[@]:-}"; do
        kill "$pid" >/dev/null 2>&1 || true
    done
}

development_initialize_env() {
    ensure_env_file "$SCRIPT_DIR/.env" "$SCRIPT_DIR/.env.example"
    ensure_env_file "$PROJECT_ROOT/backend/.env" "$PROJECT_ROOT/backend/env.example"
    ensure_env_file "$PROJECT_ROOT/frontend/.env" "$PROJECT_ROOT/frontend/env.example"
}

development_report_toggles() {
  # 宿主机开发模式下，api/worker/orchestrator 读的是 backend/.env，并以本地进程运行。
  # PostgreSQL/Redis/Envoy 作为本地开发依赖容器运行。这里把实际状态打印出来，避免“为什么没扫描/没隔离”
  # 的静默困惑，并在扫描被打开但 scanner URL 指向宿主机连不到的容器 DNS 时明确告警。
  local scan enforcement envoy scanner
  scan="$(read_env_value "$PROJECT_ROOT/backend/.env" SKILL_SECURITY_SCAN_ENABLED)"; scan="${scan:-false}"
  enforcement="$(read_env_value "$PROJECT_ROOT/backend/.env" SKILL_SECURITY_SCAN_ENFORCEMENT_ENABLED)"; enforcement="${enforcement:-false}"
  envoy="$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_ENABLED)"; envoy="${envoy:-false}"
  scanner="$(read_env_value "$PROJECT_ROOT/backend/.env" SKILL_SECURITY_SCANNER_URL)"

  log_info "宿主机开发模式安全开关（来自 backend/.env）"
  echo "  SKILL_SECURITY_SCAN_ENABLED = $scan"
  echo "  SKILL_SECURITY_SCAN_ENFORCEMENT_ENABLED = $enforcement"
  echo "  JOYSAFETER_ENVOY_ENABLED    = $envoy"

  case "$scan" in
    true|True|TRUE|1)
      case "$scanner" in
        *://skillspector:*|*@skillspector:*)
          printf '\033[1;33m⚠ Skill 扫描已开启，但 SKILL_SECURITY_SCANNER_URL=%s 指向容器 DNS 名 skillspector，宿主机进程无法访问。\033[0m\n' "$scanner"
          echo "  本脚本不启动 skillspector（compose 里它只 expose 8010、未发布到宿主机）。要在宿主机路径跑扫描，二选一："
          echo "    - 用完整栈：cd deploy && ./deploy.sh local（skillspector 在 compose 网络内可达）"
          echo "    - 或把 backend/.env 的 SKILL_SECURITY_SCANNER_URL 改成宿主机可达的扫描器地址"
          echo "  扫描结果会记录为 failed；若 SKILL_SECURITY_SCAN_ENFORCEMENT_ENABLED=true，发布版本会被拒绝。"
          ;;
        *)
          echo "  扫描已开启，scanner URL=${scanner:-未设置}"
          ;;
      esac
      ;;
    *)
      echo "  提示：宿主机开发模式会启动 Envoy 依赖容器；受限沙箱的出口仍走 Envoy。"
      ;;
  esac
}

development_start_envoy() {
  local socket_dir socket_volume config_dir image container_name
  local -a socket_mount=()
  socket_dir="$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_SOCKET_HOST_DIR)"
  socket_volume="$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_SOCKET_VOLUME)"; socket_volume="${socket_volume:-joysafeter-sockets}"
  config_dir="$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_CONFIG_DIR)"; config_dir="${config_dir:-/tmp/joysafeter-envoy-config}"
  image="$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_IMAGE)"; image="${image:-envoyproxy/envoy:v1.37.1}"
  container_name="$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_CONTAINER_NAME)"; container_name="${container_name:-joysafeter-envoy}"

  log_info "启动 Envoy 出口网关容器（本地开发依赖）"
  mkdir -p "$config_dir/sandboxes"
  if [ -n "$socket_dir" ]; then
    mkdir -p "$socket_dir"
    socket_mount=(-v "$socket_dir:/sockets")
  else
    docker volume create "$socket_volume" >/dev/null
    socket_mount=(-v "$socket_volume:/sockets")
  fi
  [ -s "$config_dir/lds.json" ] || printf '{"version_info":"0","resources":[]}\n' > "$config_dir/lds.json"
  [ -s "$config_dir/cds.json" ] || printf '{"version_info":"0","resources":[]}\n' > "$config_dir/cds.json"

  local host_gateway_args=()
  # Docker Desktop already provides host.docker.internal. Overriding it with
  # host-gateway on macOS can point Envoy at a non-listening gateway IP and make
  # xDS to the host orchestrator fail with Connection refused.
  if [[ "${OSTYPE:-}" != darwin* ]]; then
    host_gateway_args=(--add-host host.docker.internal:host-gateway)
  fi

  docker rm -f "$container_name" >/dev/null 2>&1 || true
  docker run -d --name "$container_name" \
    "${socket_mount[@]}" \
    -v "$config_dir:/envoy-config" \
    "${host_gateway_args[@]}" \
    --entrypoint /bin/sh \
    "$image" \
    -c "set -eu; mkdir -p /sockets /envoy-config/sandboxes; while [ ! -s /envoy-config/bootstrap.json ]; do sleep 0.2; done; exec envoy -c /envoy-config/bootstrap.json --log-level ${JOYSAFETER_ENVOY_LOG_LEVEL:-info}" >/dev/null
}

development_start_runner_control_proxy() {
  local volume container_path container_dir container_name image
  volume="$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME)"
  [ -n "$volume" ] || return 0
  container_path="$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH)"; container_path="${container_path:-/control/grpc.sock}"
  container_dir="${container_path%/*}"; [ -n "$container_dir" ] || container_dir="/sockets"
  container_name="${JOYSAFETER_RUNNER_CONTROL_PROXY_CONTAINER:-joysafeter-runner-control-proxy}"
  image="${JOYSAFETER_RUNNER_CONTROL_PROXY_IMAGE:-$(component_image_ref claudecode)}"

  log_info "启动 Runner 控制面 UDS 代理容器（Docker Desktop 本地开发）"
  docker volume create "$volume" >/dev/null
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  docker run --rm --user 0 --entrypoint sh \
    -v "$volume:$container_dir" \
    "$image" \
    -lc "rm -f '$container_path'" >/dev/null
  local host_gateway_args=()
  if [[ "${OSTYPE:-}" != darwin* ]]; then
    host_gateway_args=(--add-host host.docker.internal:host-gateway)
  fi
  docker run -d --name "$container_name" \
    --user 0 \
    --entrypoint socat \
    -v "$volume:$container_dir" \
    "${host_gateway_args[@]}" \
    "$image" \
    UNIX-LISTEN:"$container_path",fork,mode=666,reuseaddr TCP:host.docker.internal:${JOYSAFETER_GRPC_PORT:-9090} >/dev/null
}

development_start_infra() {
  log_info "启动 PostgreSQL / Redis"
  cd "$SCRIPT_DIR"
  compose_local_env --profile local-redis up -d postgres redis
  development_start_envoy
  development_start_runner_control_proxy

  log_info "等待 PostgreSQL 就绪"
  local ready=false
  for _ in $(seq 1 60); do
    if compose_local_env --profile local-redis exec -T postgres \
        pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-joysafeter}" >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 1
  done
  if [ "$ready" != true ]; then
    echo "PostgreSQL 在 60s 内未就绪；请检查 ./deploy.sh logs postgres" >&2
    exit 1
  fi

  # 用宿主机源码跑迁移，而不是容器 db-init 镜像。api/worker/orchestrator 都从宿主机
  # 源码启动，迁移也应如此：容器 db-init 可能是陈旧的 joysafeter-backend:latest，
  # 会把库迁到旧 head，而宿主机源码期待更新的表，造成崩溃。宿主机 alembic 让 schema
  # 与代码始终一致，也不必为跑一次迁移去构建整个 backend 镜像。
  log_info "运行数据库迁移（宿主机源码 alembic upgrade head）"
  ( cd "$PROJECT_ROOT/backend" && uv run alembic upgrade head )
}

development_start_backend() {
  cd "$PROJECT_ROOT/backend"
  export JOYSAFETER_EVENT_STREAM_ENABLED=true
  export JOYSAFETER_GRPC_PUBLIC_URL="${JOYSAFETER_GRPC_PUBLIC_URL:-http://host.docker.internal:9090}"
  export JOYSAFETER_RUNNER_CONTROL_SOCKET_HOST_DIR="${JOYSAFETER_RUNNER_CONTROL_SOCKET_HOST_DIR:-/tmp/joysafeter-runner-control}"
  export JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME="${JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME:-}"
  export JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH="${JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH:-/control/grpc.sock}"
  export JOYSAFETER_ENVOY_SOCKET_HOST_DIR="${JOYSAFETER_ENVOY_SOCKET_HOST_DIR:-$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_SOCKET_HOST_DIR)}"
  export JOYSAFETER_ENVOY_SOCKET_VOLUME="${JOYSAFETER_ENVOY_SOCKET_VOLUME:-$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_SOCKET_VOLUME)}"
  export JOYSAFETER_ENVOY_XDS_MODE="${JOYSAFETER_ENVOY_XDS_MODE:-$(read_env_value "$PROJECT_ROOT/backend/.env" JOYSAFETER_ENVOY_XDS_MODE)}"
  if [ -z "${JOYSAFETER_ENVOY_SOCKET_HOST_DIR:-}" ]; then
    export JOYSAFETER_ENVOY_XDS_MODE="${JOYSAFETER_ENVOY_XDS_MODE:-grpc}"
  fi

  log_info "启动 API :8000"
  JOYSAFETER_SERVICE_ROLE=api uv run uvicorn app.joysafeter_api.main:app --host 0.0.0.0 --port 8000 &
  DEVELOPMENT_PIDS+=("$!")

  log_info "启动 Rust Orchestrator gRPC :9090"
  (
    cd "$PROJECT_ROOT/backend/app/joysafeter_orchestrator_rs"
    JOYSAFETER_GRPC_HOST=0.0.0.0 \
      JOYSAFETER_GRPC_PORT="${JOYSAFETER_GRPC_PORT:-9090}" \
      JOYSAFETER_RUNNER_CONTROL_SOCKET_HOST_DIR="$JOYSAFETER_RUNNER_CONTROL_SOCKET_HOST_DIR" \
      JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME="$JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME" \
      JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH="$JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH" \
      JOYSAFETER_ENVOY_SOCKET_HOST_DIR="$JOYSAFETER_ENVOY_SOCKET_HOST_DIR" \
      JOYSAFETER_ENVOY_SOCKET_VOLUME="$JOYSAFETER_ENVOY_SOCKET_VOLUME" \
      JOYSAFETER_ENVOY_XDS_MODE="$JOYSAFETER_ENVOY_XDS_MODE" \
      cargo run --release
  ) &
  DEVELOPMENT_PIDS+=("$!")

  log_info "启动 Worker :8002"
  JOYSAFETER_SERVICE_ROLE=worker uv run uvicorn app.joysafeter_worker.main:app --host 127.0.0.1 --port 8002 &
  DEVELOPMENT_PIDS+=("$!")
}

development_start_frontend() {
  cd "$PROJECT_ROOT/frontend"
  export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
  log_info "启动 Frontend :3000"
  bun run dev &
  DEVELOPMENT_PIDS+=("$!")
}

run_host_development() {
    check_command docker || return 1
    check_command uv || return 1
    check_command cargo || return 1
    check_command bun || return 1
    check_docker_running
    if [ -z "$PLATFORMS" ]; then
        PLATFORMS="$(get_docker_platform)"
    fi
    development_initialize_env
    development_report_toggles
    trap development_cleanup EXIT INT TERM
    development_start_infra
    development_start_backend
    development_start_frontend
    log_success "宿主机开发环境已启动"
    echo "Frontend: http://localhost:3000"
    echo "API:      http://localhost:8000"
    echo "Docs:     http://localhost:8000/docs"
    echo "Runner gRPC: http://host.docker.internal:${JOYSAFETER_GRPC_PORT:-9090}"
    echo "按 Ctrl+C 停止宿主进程；依赖容器可用: cd deploy && ./deploy.sh down postgres redis"
    wait
}
