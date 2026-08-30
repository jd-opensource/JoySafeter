# shellcheck shell=bash
compose_path_exists() {
    local path="$1"
    case "$path" in
        /*) [ -e "$path" ] ;;
        *) [ -e "$SCRIPT_DIR/$path" ] ;;
    esac
}

detect_docker_socket_path() {
    # 输出要 bind-mount 进容器的 Docker socket 路径。
    #
    # 关键点：bind-mount 的“源路径”由 Docker DAEMON 解析，而不是当前这台机器。
    # 对 VM 型运行时（macOS/Windows 上的 Docker Desktop / Colima / Lima / Rancher，
    # 以及 Linux 上的 Docker Desktop / Colima），daemon 跑在虚拟机里，它自己的 socket
    # 永远是虚拟机内的 /var/run/docker.sock —— 而不是宿主机侧的转发 socket
    # （如 ~/.colima/<profile>/docker.sock）。宿主机侧的转发 socket 在虚拟机里只是
    # virtiofs/9p 上的一个特殊文件，无法作为 unix socket 挂载，Docker 会退化成 mkdir
    # 从而报 “operation not supported”。
    local host_os endpoint sockpath ctx_name
    host_os="$(uname -s 2>/dev/null || echo unknown)"
    endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
    ctx_name="$(docker context inspect --format '{{.Name}}' 2>/dev/null || true)"
    case "$endpoint" in
        unix://*) sockpath="${endpoint#unix://}" ;;
        *)        sockpath="" ;;  # tcp:// / ssh:// 远程 daemon，或未取到
    esac

    # macOS / Windows：dockerd 一定在虚拟机内，daemon 侧 socket 即 /var/run/docker.sock。
    case "$host_os" in
        Darwin|MINGW*|MSYS*|CYGWIN*)
            printf '%s\n' "/var/run/docker.sock"
            return
            ;;
    esac

    # Linux 上的 VM 型运行时（Colima / Docker Desktop）：daemon 侧 socket 同样是
    # 虚拟机内的 /var/run/docker.sock。用 context 名与转发 socket 路径识别。
    case "$ctx_name" in
        colima*|desktop*)
            printf '%s\n' "/var/run/docker.sock"
            return
            ;;
    esac
    case "$sockpath" in
        */.colima/*|*/.lima/*|*/.docker/*)
            printf '%s\n' "/var/run/docker.sock"
            return
            ;;
    esac

    # 原生 Linux（root 或 rootless）：daemon 在宿主机，context 里的 socket 路径可直接挂载。
    if [ -S "$sockpath" ]; then
        printf '%s\n' "$sockpath"
        return
    fi
    if [ -S "/var/run/docker.sock" ]; then
        printf '%s\n' "/var/run/docker.sock"
        return
    fi
    if [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "$XDG_RUNTIME_DIR/docker.sock" ]; then
        printf '%s\n' "$XDG_RUNTIME_DIR/docker.sock"
        return
    fi
    # 未检测到本地 socket（例如远程 DOCKER_HOST）。不输出，由调用方给出告警。
}

skillspector_source_valid() {
    local path="$1"
    [ -d "$path" ] && [ -f "$path/pyproject.toml" ] && [ -d "$path/src" ]
}

clone_skillspector() {
    local dest="$1"
    check_command git || exit 1
    if [ -d "$dest" ]; then
        rm -rf "$dest"
    fi
    mkdir -p "$(dirname "$dest")"
    log_info "克隆 SkillSpector: $SKILLSPECTOR_REPO_URL -> $dest"
    git clone --depth 1 "$SKILLSPECTOR_REPO_URL" "$dest"
}

ensure_skillspector_source() {
    local deploy_env="$1"
    local configured_path="${SKILLSPECTOR_SOURCE_PATH:-$(read_env_value "$deploy_env" "SKILLSPECTOR_SOURCE_PATH")}"

    if [ -n "$configured_path" ]; then
        local resolved_path
        case "$configured_path" in
            /*) resolved_path="$configured_path" ;;
            *)  resolved_path="$SCRIPT_DIR/$configured_path" ;;
        esac
        if skillspector_source_valid "$resolved_path"; then
            set_env_value "$deploy_env" "SKILLSPECTOR_SOURCE_PATH" "$configured_path"
            log_success "SkillSpector 源码: $configured_path"
            return
        fi
        log_warning "配置的 SkillSpector 路径无效（缺少 pyproject.toml 或 src/）: $resolved_path"
    fi

    if ! skillspector_source_valid "$DEFAULT_SKILLSPECTOR_SOURCE_PATH"; then
        clone_skillspector "$DEFAULT_SKILLSPECTOR_SOURCE_PATH"
    fi

    set_env_value "$deploy_env" "SKILLSPECTOR_SOURCE_PATH" "../.deps/SkillSpector"
    log_success "SkillSpector 源码: ../.deps/SkillSpector"
}

warn_if_port_busy() {
    local name="$1"
    local port="$2"
    if [ -z "$port" ]; then
        return
    fi
    if ! command -v lsof >/dev/null 2>&1; then
        return
    fi
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        log_warning "$name 端口 $port 已被监听；如果不是现有 JoySafeter 容器，启动可能失败"
    fi
}

check_local_ports() {
    local deploy_env="$1"
    warn_if_port_busy "Frontend" "$(read_env_value "$deploy_env" "FRONTEND_PORT_HOST")"
    warn_if_port_busy "Backend API" "$(read_env_value "$deploy_env" "BACKEND_PORT_HOST")"
    warn_if_port_busy "PostgreSQL" "$(read_env_value "$deploy_env" "POSTGRES_PORT_HOST")"
    warn_if_port_busy "Redis" "$(read_env_value "$deploy_env" "REDIS_PORT_HOST")"
    warn_if_port_busy "Rust orchestrator gRPC" "$(read_env_value "$deploy_env" "JOYSAFETER_GRPC_PORT_HOST")"
}

warn_if_sandbox_runtime_image_missing() {
    local deploy_env="$1"
    local sandbox_image="${JOYSAFETER_SANDBOX_IMAGE:-$(read_env_value "$deploy_env" "JOYSAFETER_SANDBOX_IMAGE")}"
    sandbox_image="${sandbox_image:-$(component_image_ref claudecode)}"

    if docker image inspect "$sandbox_image" >/dev/null 2>&1; then
        log_success "Sandbox runtime image: $sandbox_image"
        return
    fi

    log_warning "Sandbox runtime image missing: $sandbox_image; agent task execution will fail until it is built/pulled"
    log_warning "Build it with: ./deploy.sh build --component claudecode --arch $(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')"
}

validate_local_compose_config() {
    (
        cd "$SCRIPT_DIR"
        DOCKER_DEFAULT_PLATFORM="$PLATFORMS" \
        BASE_IMAGE_REGISTRY="$BASE_IMAGE_REGISTRY" \
        RUST_IMAGE="$RUST_IMAGE" \
        RUNTIME_IMAGE="$RUNTIME_IMAGE" \
        compose --profile local-redis --profile rust-orchestrator config >/dev/null
    )
    log_success "Compose 配置预检通过"
}

compose_local_env() {
    DOCKER_DEFAULT_PLATFORM="$PLATFORMS" \
    BASE_IMAGE_REGISTRY="$BASE_IMAGE_REGISTRY" \
    RUST_IMAGE="$RUST_IMAGE" \
    RUNTIME_IMAGE="$RUNTIME_IMAGE" \
    COMPOSE_BAKE="${COMPOSE_BAKE:-false}" \
    compose "$@"
}

build_local_compose_images() {
    local deploy_env="$SCRIPT_DIR/.env"

    log_info "构建本地 Compose 核心服务镜像..."
    (
        PUSH=false
        IMAGE_COMPONENT_SELECTION=""
        select_image_group core
        build_selected_images
        sync_selected_image_env "$deploy_env"
    )
}

wait_for_local_redis() {
    local timeout_seconds="${LOCAL_REDIS_READY_TIMEOUT_SECONDS:-60}"
    local elapsed=0

    log_info "等待本地 Redis 就绪..."
    while [ "$elapsed" -lt "$timeout_seconds" ]; do
        if compose_local_env --profile local-redis --profile rust-orchestrator exec -T redis redis-cli ping 2>/dev/null | grep -q '^PONG$'; then
            log_success "本地 Redis 已就绪"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_error "本地 Redis 在 ${timeout_seconds}s 内未就绪；请检查 docker compose logs redis"
    exit 1
}

# 解析出迁移实际使用的数据库凭据，写入全局 DB_CHECK_USER/PASS/NAME。
# 优先级与应用一致：deploy/.env 的 DATABASE_URL 优先于 POSTGRES_* 拆分参数
# （见 deploy/.env 注释），DATABASE_URL 为空再回退 backend/.env，最后回退
# compose 默认值 postgres/postgres/joysafeter。
# 注意：DATABASE_URL 中若密码含被 URL 编码的特殊字符，这里不做解码，可能导致
# 误报；本地默认密码为纯文本，通常无此问题。
resolve_db_credentials() {
    local deploy_env="$SCRIPT_DIR/.env"
    local backend_env="$PROJECT_ROOT/backend/.env"

    local url
    url="$(read_env_value "$deploy_env" "DATABASE_URL")"
    [ -z "$url" ] && url="$(read_env_value "$backend_env" "DATABASE_URL")"

    if [ -n "$url" ]; then
        local rest userpass hostpart dbpart
        rest="${url#*://}"          # user:pass@host:port/db?params
        userpass="${rest%%@*}"      # user:pass
        hostpart="${rest#*@}"       # host:port/db?params
        dbpart="${hostpart#*/}"     # db?params
        DB_CHECK_USER="${userpass%%:*}"
        DB_CHECK_PASS="${userpass#*:}"
        DB_CHECK_NAME="${dbpart%%\?*}"
    else
        DB_CHECK_USER=""
        DB_CHECK_PASS=""
        DB_CHECK_NAME=""
    fi

    [ -z "$DB_CHECK_USER" ] && DB_CHECK_USER="$(read_env_value "$deploy_env" "POSTGRES_USER")"
    [ -z "$DB_CHECK_USER" ] && DB_CHECK_USER="$(read_env_value "$backend_env" "POSTGRES_USER")"
    [ -z "$DB_CHECK_USER" ] && DB_CHECK_USER="postgres"

    [ -z "$DB_CHECK_PASS" ] && DB_CHECK_PASS="$(read_env_value "$deploy_env" "POSTGRES_PASSWORD")"
    [ -z "$DB_CHECK_PASS" ] && DB_CHECK_PASS="$(read_env_value "$backend_env" "POSTGRES_PASSWORD")"
    [ -z "$DB_CHECK_PASS" ] && DB_CHECK_PASS="postgres"

    [ -z "$DB_CHECK_NAME" ] && DB_CHECK_NAME="$(read_env_value "$deploy_env" "POSTGRES_DB")"
    [ -z "$DB_CHECK_NAME" ] && DB_CHECK_NAME="$(read_env_value "$backend_env" "POSTGRES_DB")"
    [ -z "$DB_CHECK_NAME" ] && DB_CHECK_NAME="joysafeter"

    # 显式返回 0：末行的 `[ -z ] && ...` 在变量已有值时判假返回非零，
    # 会成为函数返回值，在 set -e 下导致调用方中断。
    return 0
}

# 等待 Postgres 接受连接（pg_isready 不校验密码，只探测服务就绪）。
wait_for_local_postgres() {
    local timeout_seconds="${LOCAL_DB_READY_TIMEOUT_SECONDS:-60}"
    local elapsed=0

    log_info "等待本地 PostgreSQL 就绪..."
    while [ "$elapsed" -lt "$timeout_seconds" ]; do
        if compose_local_env --profile local-redis --profile rust-orchestrator exec -T postgres \
            pg_isready -U "$DB_CHECK_USER" -d "$DB_CHECK_NAME" >/dev/null 2>&1; then
            log_success "本地 PostgreSQL 已就绪"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_error "本地 PostgreSQL 在 ${timeout_seconds}s 内未就绪；请检查 docker compose logs postgres"
    exit 1
}

# 删除数据库命名卷并重建 postgres 容器。仅在用户明确确认后调用（会清空本地库全部数据）。
reset_local_db_volume() {
    log_warning "重置数据库数据卷（将删除本地数据库全部数据）..."
    compose_local_env --profile local-redis --profile rust-orchestrator rm -sf postgres >/dev/null 2>&1 || true

    # 卷名带 compose 项目前缀（如 deploy_joysafeter-db-data），用后缀匹配以适配任意前缀。
    local vol
    vol="$(docker volume ls --format '{{.Name}}' | grep -E '(^|_)joysafeter-db-data$' | head -1)"
    if [ -n "$vol" ]; then
        if ! docker volume rm "$vol" >/dev/null 2>&1; then
            log_error "无法删除数据卷 $vol（可能仍被容器占用）；请手动执行 cd deploy && docker compose down -v 后重试"
            exit 1
        fi
        log_success "已删除数据库数据卷 $vol"
    else
        log_warning "未找到 joysafeter-db-data 数据卷，跳过删除"
    fi

    compose_local_env --profile local-redis --profile rust-orchestrator up -d --no-build postgres
    wait_for_local_postgres
}

# 用配置的凭据真正连库，验证密码是否与卷内固化的密码一致。
# 命中 "password authentication failed" 时交互询问是否重置数据卷；
# 其他错误如实报出并退出，绝不对未知错误执行破坏性重置。
verify_local_db_credentials() {
    resolve_db_credentials
    wait_for_local_postgres

    log_info "校验数据库连接凭据（用户 ${DB_CHECK_USER} / 库 ${DB_CHECK_NAME}）..."
    # 用服务名 postgres（走网络接口）连接，命中 pg_hba 的 scram-sha-256 规则，
    # 与 alembic/应用一致；127.0.0.1 在容器内命中 trust 规则会跳过密码校验，不可用。
    # set -e 下命令替换失败会中断脚本，故用 || true 兜底，把失败留给下方分支处理。
    local out
    out="$(compose_local_env --profile local-redis --profile rust-orchestrator exec -T postgres \
        env PGPASSWORD="$DB_CHECK_PASS" psql -h postgres -U "$DB_CHECK_USER" -d "$DB_CHECK_NAME" -tAc 'select 1' 2>&1 || true)"

    if printf '%s' "$out" | grep -q '^1$'; then
        log_success "数据库凭据校验通过"
        return 0
    fi

    if ! printf '%s' "$out" | grep -qi 'password authentication failed'; then
        log_error "数据库连接失败（非密码问题）："
        printf '%s\n' "$out" >&2
        log_error "请检查 postgres 服务状态：cd deploy && docker compose logs postgres"
        exit 1
    fi

    # 密码不匹配：解释根因（Postgres 只在首次初始化空卷时采用 POSTGRES_PASSWORD，
    # 之后永久沿用卷内固化的旧密码，改 .env 无效）。
    log_error "数据库密码校验失败：配置的密码与现有数据卷中固化的密码不一致。"
    log_warning "原因：PostgreSQL 只在【首次初始化空卷】时采用 POSTGRES_PASSWORD；"
    log_warning "     卷一旦建成，改 .env / DATABASE_URL 都不会更新库内密码。"
    log_warning "解决办法二选一："
    log_warning "  1) 保留数据：docker exec -it joysafeter-db psql -U ${DB_CHECK_USER} -c \"ALTER USER ${DB_CHECK_USER} PASSWORD '<你在.env里配置的密码>';\""
    log_warning "  2) 丢弃数据：删除数据卷后用当前 .env 密码重新初始化（下面可直接执行）"

    if [ ! -t 0 ]; then
        log_error "当前为非交互环境，不自动重置数据卷。请修正密码或手动执行：cd deploy && docker compose down -v"
        exit 1
    fi

    local reply
    printf "${YELLOW}是否删除数据库数据卷并用当前 .env 密码重新初始化？此操作会清空本地库全部数据 [y/N]: ${NC}" >&2
    read -r reply < /dev/tty || reply=""
    case "$reply" in
        y|Y|yes|YES)
            reset_local_db_volume
            log_info "重置后重新校验数据库凭据..."
            out="$(compose_local_env --profile local-redis --profile rust-orchestrator exec -T postgres \
                env PGPASSWORD="$DB_CHECK_PASS" psql -h postgres -U "$DB_CHECK_USER" -d "$DB_CHECK_NAME" -tAc 'select 1' 2>&1 || true)"
            if printf '%s' "$out" | grep -q '^1$'; then
                log_success "重置完成，数据库凭据校验通过"
                return 0
            fi
            log_error "重置后仍无法连接："
            printf '%s\n' "$out" >&2
            exit 1
            ;;
        *)
            log_error "已取消。请修正 .env 中的数据库密码后重试。"
            exit 1
            ;;
    esac
}

run_local_migrations() {
    (
        cd "$SCRIPT_DIR"
        log_info "启动数据库、Redis、SkillSpector 基础服务..."
        compose_local_env --profile local-redis --profile rust-orchestrator up -d --no-build postgres redis skillspector

        wait_for_local_redis
        verify_local_db_credentials

        log_info "运行数据库迁移..."
        compose_local_env --profile local-redis --profile rust-orchestrator --profile init run --rm db-init

        log_info "初始化凭据加密 canary..."
        compose_local_env --profile local-redis --profile rust-orchestrator --profile init run --rm db-init \
            python scripts/credential_encryption_rotation.py --initialize-missing-canaries
    )
    log_success "数据库迁移和凭据加密 canary 初始化完成"
}

require_single_platform() {
    if echo "$PLATFORMS" | grep -q ","; then
        log_error "本地 Compose 部署一次只能使用单一平台；请使用 --arch amd64 或 --arch arm64"
        exit 1
    fi
}

configure_local_compose_env() {
    local deploy_env="$SCRIPT_DIR/.env"

    ensure_env_file "$deploy_env" "$SCRIPT_DIR/.env.example"
    ensure_env_file "$PROJECT_ROOT/backend/.env" "$PROJECT_ROOT/backend/env.example"
    ensure_env_file "$PROJECT_ROOT/frontend/.env" "$PROJECT_ROOT/frontend/env.example"

    ensure_vault_encryption_key "$deploy_env" "$PROJECT_ROOT/backend/.env"
    validate_local_database_config "$deploy_env"

    set_env_value "$deploy_env" "BASE_IMAGE_REGISTRY" "$BASE_IMAGE_REGISTRY"
    set_env_value "$deploy_env" "RUST_IMAGE" "$RUST_IMAGE"
    set_env_value "$deploy_env" "RUNTIME_IMAGE" "$RUNTIME_IMAGE"
    set_env_value "$deploy_env" "DB_IMAGE" "${DB_IMAGE:-${BASE_IMAGE_REGISTRY}postgres:15}"
    set_env_value "$deploy_env" "REDIS_IMAGE" "${REDIS_IMAGE:-${BASE_IMAGE_REGISTRY}redis:alpine3.22}"
    set_env_value "$deploy_env" "JOYSAFETER_ENVOY_IMAGE" "${JOYSAFETER_ENVOY_IMAGE:-${DOCKER_MIRROR}/envoyproxy/envoy:v1.37.1}"
    set_env_value "$deploy_env" "DOCKER_DEFAULT_PLATFORM" "$PLATFORMS"

    ensure_skillspector_source "$deploy_env"

    # detect_docker_socket_path 返回的是“容器内挂载源”，即 daemon 侧路径。VM 型运行时
    # 会返回虚拟机内的 /var/run/docker.sock，它在宿主机上并不存在，所以这里不能再用
    # 宿主机 `[ -S ... ]` 去校验（那正是旧代码在 Colima/Docker Desktop 上失败的原因）。
    local docker_socket="${DOCKER_SOCKET_PATH:-$(detect_docker_socket_path)}"
    if [ -n "$docker_socket" ]; then
        set_env_value "$deploy_env" "DOCKER_SOCKET_PATH" "$docker_socket"
        log_success "Docker socket (容器内挂载源): $docker_socket"
    else
        log_warning "未能自动定位 Docker socket；如 orchestrator-rs 无法创建 sandbox，请设置 deploy/.env 的 DOCKER_SOCKET_PATH"
    fi
}

start_local_compose() {
    local timeout_seconds="${LOCAL_COMPOSE_READY_TIMEOUT_SECONDS:-240}"

    if ! (
        cd "$SCRIPT_DIR"
        log_info "启动本地 Compose 服务并等待健康检查（最长 ${timeout_seconds}s）..."
        compose_local_env --profile local-redis --profile rust-orchestrator \
            up -d --no-build --wait --wait-timeout "$timeout_seconds"
    ); then
        log_error "本地 Compose 服务未通过健康检查"
        (
            cd "$SCRIPT_DIR"
            compose_local_env --profile local-redis --profile rust-orchestrator ps -a || true
            compose_local_env --profile local-redis --profile rust-orchestrator \
                logs --no-color --tail=120 orchestrator-rs joysafeter-envoy api worker || true
        )
        return 1
    fi
    log_success "本地 Compose 服务已启动并通过健康检查"
}

run_local_compose() {
    require_single_platform
    configure_local_compose_env
    check_local_ports "$SCRIPT_DIR/.env"
    warn_if_sandbox_runtime_image_missing "$SCRIPT_DIR/.env"
    validate_local_compose_config

    log_info "Docker daemon 平台: $PLATFORMS"
    log_info "基础镜像源: $BASE_IMAGE_REGISTRY"
    log_info "第三方镜像代理: $DOCKER_MIRROR"

    build_local_compose_images
    run_local_migrations
    start_local_compose
}

run_local_doctor() {
    require_single_platform
    configure_local_compose_env
    check_local_ports "$SCRIPT_DIR/.env"
    warn_if_sandbox_runtime_image_missing "$SCRIPT_DIR/.env"
    validate_local_compose_config

    log_success "本地部署环境预检完成"
    echo ""
    echo "下一步:"
    echo "  cd deploy"
    echo "  ./deploy.sh local"
}

# ---- 生命周期管理命令 ----
# 统一在 SCRIPT_DIR 下、带本地部署的 profile 集合执行 compose 子命令，
# 保证 down/logs/restart/status 覆盖 redis 与 rust-orchestrator 等 profile 服务，
# 并复用与 local 一致的 env（deploy/.env + LOCAL_* 镜像变量）。
compose_lifecycle() {
    (
        cd "$SCRIPT_DIR"
        compose_local_env --profile local-redis --profile rust-orchestrator "$@"
    )
}

run_down() {
    log_info "停止并移除 JoySafeter 本地 Compose 服务（保留数据卷）..."
    compose_lifecycle down "$@"
    log_success "服务已停止；命名数据卷已保留。如需连数据一起清除，请手动执行：cd deploy && docker compose down -v"
}

run_logs() {
    if [ "$#" -gt 0 ]; then
        log_info "跟随服务日志: $*（Ctrl-C 退出）"
    else
        log_info "跟随全部服务日志（Ctrl-C 退出）"
    fi
    compose_lifecycle logs -f "$@"
}

run_restart() {
    if [ "$#" -gt 0 ]; then
        log_info "重启服务: $*"
    else
        log_info "重启全部 JoySafeter 本地 Compose 服务..."
    fi
    compose_lifecycle restart "$@"
    log_success "服务已重启"
}

run_status() {
    compose_lifecycle ps "$@"
}

# 初始化 Docker Buildx
