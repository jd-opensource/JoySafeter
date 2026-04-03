#!/bin/bash
# =============================================================================
# JoySafeter 快速启动脚本
# 支持多种启动模式和自定义端口配置
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 加载公共函数库
source "$SCRIPT_DIR/scripts/_common.sh"

# 全局错误捕获：set -e 触发退出时打印行号，便于定位问题
trap 'log_error "脚本在第 $LINENO 行异常退出 (退出码 $?)"' ERR

# --- 全局状态 ---
SKIP_ENV=false
SKIP_DB_INIT=false
STARTUP_MODE=""
PORT_FRONTEND=3000
PORT_BACKEND=8000
PORT_POSTGRES=5432
PORT_REDIS=6379
HOST_ADDR=localhost          # 访问地址：localhost 或 IP/域名
URL_SCHEME=http              # URL 协议：http 或 https
BACKEND_ADDR=localhost       # 后端地址（前端模式用）
FRONTEND_ADDR=localhost      # 前端地址（后端模式用）
DB_ADDR=localhost            # 数据库地址（后端/both 模式用）
REDIS_ADDR=localhost         # Redis 地址（后端/both 模式用）
BACKEND_PID=""
IS_MACOS=false

# =============================================================================
# 工具函数
# =============================================================================

detect_os() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        IS_MACOS=true
    fi
}

sed_inplace() {
    local expression="$1"
    local file="$2"
    if [ "$IS_MACOS" = true ]; then
        sed -i '' "$expression" "$file"
    else
        sed -i "$expression" "$file"
    fi
}

show_usage() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -h, --help          显示帮助信息
  --skip-env          跳过 .env 文件初始化
  --skip-db-init      跳过数据库初始化

启动模式:
  脚本启动后会交互式选择以下模式之一：
  (1) Docker Compose 全栈  — 所有服务容器化运行
  (2) 仅本地前端           — bun run dev（需后端已启动）
  (3) 仅本地后端           — uvicorn --reload（需中间件已启动）
  (4) 本地前端 + 后端      — 自动启动中间件，后端后台 + 前端前台

示例:
  $0
  $0 --skip-env
  $0 --skip-db-init
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            --skip-env)
                SKIP_ENV=true
                shift
                ;;
            --skip-db-init)
                SKIP_DB_INIT=true
                shift
                ;;
            *)
                log_error "未知选项: $1"
                show_usage
                exit 1
                ;;
        esac
    done
}

# =============================================================================
# 模式选择
# =============================================================================

show_mode_menu() {
    echo ""
    echo "请选择启动模式:"
    echo ""
    echo "  (1) Docker Compose 全栈    — 所有服务容器化运行"
    echo "  (2) 仅本地前端              — bun run dev"
    echo "  (3) 仅本地后端              — uvicorn --reload"
    echo "  (4) 本地前端 + 后端         — 后端后台 + 前端前台"
    echo ""

    while true; do
        printf "请输入选项 [1-4]: "
        read -r choice
        case "$choice" in
            1) STARTUP_MODE="docker";   break ;;
            2) STARTUP_MODE="frontend"; break ;;
            3) STARTUP_MODE="backend";  break ;;
            4) STARTUP_MODE="both";     break ;;
            *) log_warning "无效选项，请输入 1-4" ;;
        esac
    done

    echo ""
    case "$STARTUP_MODE" in
        docker)   log_info "已选择: Docker Compose 全栈" ;;
        frontend) log_info "已选择: 仅本地前端" ;;
        backend)  log_info "已选择: 仅本地后端" ;;
        both)     log_info "已选择: 本地前端 + 后端" ;;
    esac
}

# =============================================================================
# 端口检测与选择
# =============================================================================

check_port_in_use() {
    local port="$1"
    if [ "$IS_MACOS" = true ]; then
        lsof -i :"$port" -sTCP:LISTEN >/dev/null 2>&1
    else
        if command -v ss >/dev/null 2>&1; then
            ss -tlnp "sport = :$port" 2>/dev/null | grep -q LISTEN
        elif command -v lsof >/dev/null 2>&1; then
            lsof -i :"$port" -sTCP:LISTEN >/dev/null 2>&1
        else
            # 无法检测，假设未占用
            return 1
        fi
    fi
}

get_port_process_info() {
    local port="$1"
    if [ "$IS_MACOS" = true ]; then
        lsof -i :"$port" -sTCP:LISTEN 2>/dev/null | tail -1 | awk '{print $1 " (PID: " $2 ")"}'
    else
        if command -v ss >/dev/null 2>&1; then
            ss -tlnp "sport = :$port" 2>/dev/null | grep LISTEN | awk '{print $NF}'
        elif command -v lsof >/dev/null 2>&1; then
            lsof -i :"$port" -sTCP:LISTEN 2>/dev/null | tail -1 | awk '{print $1 " (PID: " $2 ")"}'
        fi
    fi
}

# prompt_port <label> <default_port>
# 交互式端口选择，检测冲突并循环重试
prompt_port() {
    local label="$1"
    local default_port="$2"
    local port=""

    while true; do
        printf "%s [%s]: " "$label" "$default_port" >&2
        read -r port
        port="${port:-$default_port}"

        # 验证数字
        if ! [[ "$port" =~ ^[0-9]+$ ]]; then
            log_warning "请输入有效的端口号（数字）" >&2
            continue
        fi

        # 验证范围
        if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
            log_warning "端口号范围: 1-65535" >&2
            continue
        fi

        # 特权端口警告
        if [ "$port" -lt 1024 ]; then
            log_warning "端口 $port 为特权端口，可能需要 sudo 权限" >&2
        fi

        # 检测冲突
        if check_port_in_use "$port"; then
            local proc_info
            proc_info=$(get_port_process_info "$port")
            log_warning "端口 $port 已被占用: $proc_info" >&2
            log_info "请输入其他端口" >&2
            continue
        fi

        echo "$port"
        return 0
    done
}

# =============================================================================
# 访问地址配置
# =============================================================================

# 询问单个服务的远程地址，返回 IP/域名（通过 echo）
# prompt_remote_service <label> <default>
prompt_remote_service() {
    local label="$1"
    local default="$2"

    while true; do
        printf "%s [%s]: " "$label" "$default" >&2
        read -r input_addr
        input_addr="${input_addr:-$default}"
        input_addr="${input_addr#http://}"
        input_addr="${input_addr#https://}"
        input_addr="${input_addr%%/*}"
        input_addr="${input_addr%%:*}"

        if [ -z "$input_addr" ]; then
            log_warning "地址不能为空" >&2
            continue
        fi
        echo "$input_addr"
        return 0
    done
}

prompt_host_addr() {
    echo "" >&2
    log_step "配置访问地址..." >&2
    echo "" >&2
    echo "  当前服务将部署在哪里？" >&2
    echo "" >&2
    echo "  (1) 本机 (localhost)        — 本地开发/测试" >&2
    echo "  (2) 远程服务器 / 指定 IP    — 输入 IP 或域名" >&2
    echo "" >&2

    while true; do
        printf "请选择 [1-2]: " >&2
        read -r addr_choice
        case "$addr_choice" in
            1)
                HOST_ADDR="localhost"
                URL_SCHEME="http"
                break
                ;;
            2)
                echo "" >&2
                while true; do
                    printf "请输入服务器 IP 或域名 (如 192.168.1.100 或 example.com): " >&2
                    read -r input_addr
                    input_addr="${input_addr#http://}"
                    input_addr="${input_addr#https://}"
                    input_addr="${input_addr%%/*}"
                    input_addr="${input_addr%%:*}"

                    if [ -z "$input_addr" ]; then
                        log_warning "地址不能为空" >&2
                        continue
                    fi
                    HOST_ADDR="$input_addr"
                    break
                done

                # 询问协议
                echo "" >&2
                echo "  是否使用 HTTPS？" >&2
                echo "  (1) http  — 内网/测试环境" >&2
                echo "  (2) https — 已配置 SSL 证书 / 反向代理" >&2
                echo "" >&2
                while true; do
                    printf "请选择 [1-2] (默认 1): " >&2
                    read -r scheme_choice
                    scheme_choice="${scheme_choice:-1}"
                    case "$scheme_choice" in
                        1) URL_SCHEME="http";  break ;;
                        2) URL_SCHEME="https"; break ;;
                        *) log_warning "请输入 1 或 2" >&2 ;;
                    esac
                done
                break
                ;;
            *)
                log_warning "请输入 1 或 2" >&2
                ;;
        esac
    done

    echo "" >&2
    log_success "访问地址: ${URL_SCHEME}://${HOST_ADDR}" >&2
}

# 构造服务 URL（自动处理默认端口省略）
build_url() {
    local scheme="$1"
    local host="$2"
    local port="$3"

    # https 默认 443，http 默认 80 时省略端口
    if { [ "$scheme" = "https" ] && [ "$port" = "443" ]; } || \
       { [ "$scheme" = "http" ] && [ "$port" = "80" ]; }; then
        echo "${scheme}://${host}"
    else
        echo "${scheme}://${host}:${port}"
    fi
}

collect_ports() {
    log_step "配置服务端口..."
    echo ""

    case "$STARTUP_MODE" in
        docker)
            PORT_FRONTEND=$(prompt_port "前端端口" "$PORT_FRONTEND")
            PORT_BACKEND=$(prompt_port "后端端口" "$PORT_BACKEND")
            PORT_POSTGRES=$(prompt_port "PostgreSQL 端口" "$PORT_POSTGRES")
            PORT_REDIS=$(prompt_port "Redis 端口" "$PORT_REDIS")
            prompt_host_addr
            ;;
        frontend)
            PORT_FRONTEND=$(prompt_port "前端端口" "$PORT_FRONTEND")
            prompt_frontend_remote
            ;;
        backend)
            PORT_BACKEND=$(prompt_port "后端端口" "$PORT_BACKEND")
            prompt_backend_remote
            ;;
        both)
            PORT_FRONTEND=$(prompt_port "前端端口" "$PORT_FRONTEND")
            PORT_BACKEND=$(prompt_port "后端端口" "$PORT_BACKEND")
            prompt_both_remote
            ;;
    esac

    echo ""
    log_success "端口配置完成"
}

# 前端模式：询问后端是否在远程
prompt_frontend_remote() {
    echo ""
    printf "后端 API 是否在远程服务器上？(y/N): "
    read -r remote_choice
    if [[ $remote_choice =~ ^[Yy]$ ]]; then
        BACKEND_ADDR=$(prompt_remote_service "后端 IP 或域名" "$BACKEND_ADDR")
        PORT_BACKEND=$(prompt_port "后端端口" "$PORT_BACKEND")
        echo ""
        echo "  后端协议："
        echo "  (1) http   (2) https"
        printf "请选择 [1-2] (默认 1): "
        read -r sc
        [ "$sc" = "2" ] && URL_SCHEME="https"
    fi
}

# 后端模式：询问前端/DB/Redis 是否在远程
prompt_backend_remote() {
    echo ""
    printf "是否连接远程数据库/Redis/前端？(y/N): "
    read -r remote_choice
    if [[ $remote_choice =~ ^[Yy]$ ]]; then
        echo ""
        log_step "配置远程服务地址..."
        DB_ADDR=$(prompt_remote_service "PostgreSQL 地址" "$DB_ADDR")
        PORT_POSTGRES=$(prompt_port "PostgreSQL 端口" "$PORT_POSTGRES")
        REDIS_ADDR=$(prompt_remote_service "Redis 地址" "$REDIS_ADDR")
        PORT_REDIS=$(prompt_port "Redis 端口" "$PORT_REDIS")
        FRONTEND_ADDR=$(prompt_remote_service "前端地址 (用于 CORS)" "$FRONTEND_ADDR")
        PORT_FRONTEND=$(prompt_port "前端端口" "$PORT_FRONTEND")
    fi
}

# both 模式：询问对外暴露地址
prompt_both_remote() {
    echo ""
    printf "是否通过非 localhost 地址对外提供服务？(y/N): "
    read -r remote_choice
    if [[ $remote_choice =~ ^[Yy]$ ]]; then
        HOST_ADDR=$(prompt_remote_service "对外 IP 或域名" "$HOST_ADDR")
        FRONTEND_ADDR="$HOST_ADDR"
        BACKEND_ADDR="$HOST_ADDR"
        echo ""
        echo "  协议："
        echo "  (1) http   (2) https"
        printf "请选择 [1-2] (默认 1): "
        read -r sc
        [ "$sc" = "2" ] && URL_SCHEME="https"
    fi
}

# =============================================================================
# 环境文件更新
# =============================================================================

update_deploy_env() {
    local env_file="$DEPLOY_DIR/.env"

    if [ ! -f "$env_file" ]; then
        log_warning "deploy/.env 不存在，跳过端口更新"
        return 0
    fi

    log_step "更新 deploy/.env 端口配置..."

    # 按模式只更新用户实际选择过的端口，避免覆盖未询问的端口
    case "$STARTUP_MODE" in
        docker)
            local backend_url frontend_url
            backend_url=$(build_url "$URL_SCHEME" "$HOST_ADDR" "$PORT_BACKEND")
            frontend_url=$(build_url "$URL_SCHEME" "$HOST_ADDR" "$PORT_FRONTEND")

            sed_inplace "s|^BACKEND_PORT_HOST=.*|BACKEND_PORT_HOST=$PORT_BACKEND|" "$env_file"
            sed_inplace "s|^FRONTEND_PORT_HOST=.*|FRONTEND_PORT_HOST=$PORT_FRONTEND|" "$env_file"
            sed_inplace "s|^POSTGRES_PORT_HOST=.*|POSTGRES_PORT_HOST=$PORT_POSTGRES|" "$env_file"
            sed_inplace "s|^REDIS_PORT_HOST=.*|REDIS_PORT_HOST=$PORT_REDIS|" "$env_file"
            sed_inplace "s|^BACKEND_URL=.*|BACKEND_URL=$backend_url|" "$env_file"
            sed_inplace "s|^FRONTEND_URL=.*|FRONTEND_URL=$frontend_url|" "$env_file"
            ;;
        frontend)
            # 前端本地跑，始终 http://localhost
            sed_inplace "s|^FRONTEND_PORT_HOST=.*|FRONTEND_PORT_HOST=$PORT_FRONTEND|" "$env_file"
            sed_inplace "s|^FRONTEND_URL=.*|FRONTEND_URL=http://localhost:$PORT_FRONTEND|" "$env_file"
            ;;
        backend)
            # 后端本地跑，始终 http://localhost
            sed_inplace "s|^BACKEND_PORT_HOST=.*|BACKEND_PORT_HOST=$PORT_BACKEND|" "$env_file"
            sed_inplace "s|^BACKEND_URL=.*|BACKEND_URL=http://localhost:$PORT_BACKEND|" "$env_file"
            ;;
        both)
            local be_url_both_env fe_url_both_env
            be_url_both_env=$(build_url "$URL_SCHEME" "$BACKEND_ADDR" "$PORT_BACKEND")
            fe_url_both_env=$(build_url "$URL_SCHEME" "$FRONTEND_ADDR" "$PORT_FRONTEND")
            sed_inplace "s|^BACKEND_PORT_HOST=.*|BACKEND_PORT_HOST=$PORT_BACKEND|" "$env_file"
            sed_inplace "s|^FRONTEND_PORT_HOST=.*|FRONTEND_PORT_HOST=$PORT_FRONTEND|" "$env_file"
            sed_inplace "s|^BACKEND_URL=.*|BACKEND_URL=$be_url_both_env|" "$env_file"
            sed_inplace "s|^FRONTEND_URL=.*|FRONTEND_URL=$fe_url_both_env|" "$env_file"
            ;;
    esac

    log_success "deploy/.env 已更新"

    # 非 localhost 部署时，同步 CSP 额外域名到 frontend/.env
    update_frontend_csp
}

# 远程 IP/域名部署时，将后端地址写入前端 CSP 白名单
# 确保浏览器允许前端向后端 IP 发起 HTTP/WS 请求
update_frontend_csp() {
    # 确定后端实际地址：Docker 模式用 HOST_ADDR，其他模式用 BACKEND_ADDR
    local target_addr
    case "$STARTUP_MODE" in
        docker) target_addr="$HOST_ADDR" ;;
        *)      target_addr="$BACKEND_ADDR" ;;
    esac

    # localhost 不需要额外 CSP 配置
    if [ "$target_addr" = "localhost" ]; then
        return 0
    fi

    local fe_env="$PROJECT_ROOT/frontend/.env"
    if [ ! -f "$fe_env" ]; then
        return 0
    fi

    # 构造 CSP connect-src：覆盖 http/https/ws/wss + 端口通配
    local csp_connect
    if [ "$URL_SCHEME" = "https" ]; then
        csp_connect="https://${target_addr}:* wss://${target_addr}:*"
    else
        csp_connect="http://${target_addr}:* https://${target_addr}:* ws://${target_addr}:* wss://${target_addr}:*"
    fi

    log_step "更新 frontend/.env CSP 配置 (${target_addr})..."

    if grep -q "^NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA=" "$fe_env"; then
        sed_inplace "s|^NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA=.*|NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA=\"$csp_connect\"|" "$fe_env"
    else
        echo "NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA=\"$csp_connect\"" >> "$fe_env"
    fi

    if grep -q "^NEXT_PUBLIC_CSP_FRAME_SRC_EXTRA=" "$fe_env"; then
        sed_inplace "s|^NEXT_PUBLIC_CSP_FRAME_SRC_EXTRA=.*|NEXT_PUBLIC_CSP_FRAME_SRC_EXTRA=\"$csp_connect\"|" "$fe_env"
    else
        echo "NEXT_PUBLIC_CSP_FRAME_SRC_EXTRA=\"$csp_connect\"" >> "$fe_env"
    fi

    log_success "frontend/.env CSP 已更新"
}

# 从 deploy/.env 同步未被用户交互选择的端口到脚本变量
# 仅同步用户未通过远程地址提示手动设置的端口
sync_ports_from_env() {
    case "$STARTUP_MODE" in
        docker)
            ;;
        frontend)
            # 仅当后端地址仍为 localhost（用户未选远程后端）时，从 .env 同步
            if [ "$BACKEND_ADDR" = "localhost" ]; then
                PORT_BACKEND="${BACKEND_PORT_HOST:-$PORT_BACKEND}"
            fi
            ;;
        backend)
            # 仅同步用户未通过远程提示手动设置的端口
            if [ "$FRONTEND_ADDR" = "localhost" ]; then
                PORT_FRONTEND="${FRONTEND_PORT_HOST:-$PORT_FRONTEND}"
            fi
            if [ "$DB_ADDR" = "localhost" ]; then
                PORT_POSTGRES="${POSTGRES_PORT_HOST:-$PORT_POSTGRES}"
            fi
            if [ "$REDIS_ADDR" = "localhost" ]; then
                PORT_REDIS="${REDIS_PORT_HOST:-$PORT_REDIS}"
            fi
            ;;
        both)
            PORT_POSTGRES="${POSTGRES_PORT_HOST:-$PORT_POSTGRES}"
            PORT_REDIS="${REDIS_PORT_HOST:-$PORT_REDIS}"
            ;;
    esac
}

# 统一的环境初始化流程：init/load .env → 更新端口 → 重新加载 → 同步变量
setup_env() {
    if [ "$SKIP_ENV" = false ]; then
        init_env_files
        echo ""
    else
        load_deploy_env
    fi

    update_deploy_env
    load_deploy_env
    sync_ports_from_env
}

# =============================================================================
# 依赖检查
# =============================================================================

check_local_deps() {
    local need_backend="$1"
    local need_frontend="$2"

    if [ "$need_backend" = true ]; then
        if ! command -v uv >/dev/null 2>&1; then
            log_error "未找到 uv，请先安装: https://docs.astral.sh/uv/"
            exit 1
        fi
        if ! command -v python3 >/dev/null 2>&1; then
            log_error "未找到 python3"
            exit 1
        fi
    fi

    if [ "$need_frontend" = true ]; then
        if ! command -v bun >/dev/null 2>&1; then
            log_error "未找到 bun，请先安装: https://bun.sh"
            exit 1
        fi
    fi
}

# =============================================================================
# 后端可达性检查（仅 warning）
# =============================================================================

check_backend_reachable() {
    local host="${1:-localhost}"
    local url
    url=$(build_url "$URL_SCHEME" "$host" "$PORT_BACKEND")

    if command -v curl >/dev/null 2>&1; then
        if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "$url/docs" 2>/dev/null | grep -q '200'; then
            log_success "后端可达: $url"
            return 0
        fi
    fi
    if command -v nc >/dev/null 2>&1; then
        if nc -z "$host" "$PORT_BACKEND" 2>/dev/null; then
            log_success "后端端口 $host:$PORT_BACKEND 已监听"
            return 0
        fi
    fi
    log_warning "未检测到后端服务，部分功能可能不可用"
    return 0
}

# =============================================================================
# OpenClaw 配置（仅 Docker 模式）
# =============================================================================

check_openclaw_config() {
    log_step "检查 OpenClaw 配置..."
    local backend_env="$PROJECT_ROOT/backend/.env"

    if [ ! -f "$backend_env" ]; then
        return 0
    fi

    # 检查并配置 OpenClaw 平台底座 (AI_GATEWAY_*)
    if grep -q "^AI_GATEWAY_BASE_URL=" "$backend_env"; then
        log_success "OpenClaw 平台网关配置已存在"
    else
        log_info "OpenClaw 平台需要一个 AI Gateway 作为底座。"
        printf "${YELLOW}是否配置 OpenClaw 平台网关 (AI_GATEWAY_*)? (y/N): ${NC}"
        read -r config_platform
        if [[ $config_platform =~ ^[Yy]$ ]]; then
            printf "请输入 AI_GATEWAY_BASE_URL: "
            read -r gw_url
            printf "请输入 AI_GATEWAY_API_KEY: "
            read -r gw_key
            printf "请输入 AI_GATEWAY_MODEL: "
            read -r gw_model
            printf "请输入 AI_GATEWAY_PROVIDER (openai/anthropic, 默认 openai): "
            read -r gw_provider
            gw_provider=${gw_provider:-openai}

            if [ -n "$gw_url" ]; then
                {
                    echo "AI_GATEWAY_BASE_URL=$gw_url"
                    echo "AI_GATEWAY_API_KEY=$gw_key"
                    echo "AI_GATEWAY_MODEL=$gw_model"
                    echo "AI_GATEWAY_PROVIDER=$gw_provider"
                } >> "$backend_env"
                log_success "平台网关配置已写入"
            fi
        fi
    fi

    # 检查并配置容器内工具 (ANTHROPIC_*)
    if grep -q "^ANTHROPIC_BASE_URL=" "$backend_env"; then
        log_success "Claude Code 等工具配置已存在"
    else
        log_info "OpenClaw 内部集成了 Claude Code，它通常需要独立的 Anthropic 变量。"
        printf "${YELLOW}是否配置内部工具 (ANTHROPIC_*)? (y/N): ${NC}"
        read -r config_tools
        if [[ $config_tools =~ ^[Yy]$ ]]; then
            local sync_done=false
            if grep -q "^AI_GATEWAY_BASE_URL=" "$backend_env"; then
                printf "${CYAN}是否直接使用刚才配置的平台网关作为工具配置? (y/N): ${NC}"
                read -r use_platform
                if [[ $use_platform =~ ^[Yy]$ ]]; then
                    local p_url p_key p_model
                    p_url=$(grep "^AI_GATEWAY_BASE_URL=" "$backend_env" | cut -d'=' -f2)
                    p_key=$(grep "^AI_GATEWAY_API_KEY=" "$backend_env" | cut -d'=' -f2)
                    p_model=$(grep "^AI_GATEWAY_MODEL=" "$backend_env" | cut -d'=' -f2)

                    {
                        echo "ANTHROPIC_BASE_URL=$p_url"
                        echo "ANTHROPIC_AUTH_TOKEN=$p_key"
                        echo "ANTHROPIC_MODEL=$p_model"
                    } >> "$backend_env"
                    log_success "已同步平台网关配置到内部工具"
                    sync_done=true
                fi
            fi

            if [ "$sync_done" = false ]; then
                printf "请输入 ANTHROPIC_BASE_URL: "
                read -r tool_url
                printf "请输入 ANTHROPIC_AUTH_TOKEN: "
                read -r tool_token
                printf "请输入 ANTHROPIC_MODEL: "
                read -r tool_model

                if [ -n "$tool_url" ]; then
                    {
                        echo "ANTHROPIC_BASE_URL=$tool_url"
                        echo "ANTHROPIC_AUTH_TOKEN=$tool_token"
                        echo "ANTHROPIC_MODEL=$tool_model"
                    } >> "$backend_env"
                    log_success "内部工具配置已写入"
                fi
            fi
        fi
    fi
}

# =============================================================================
# 数据库初始化（Docker 模式）
# =============================================================================

init_database() {
    log_step "初始化数据库..."

    cd "$DEPLOY_DIR" || { log_error "无法进入 deploy 目录: $DEPLOY_DIR"; return 1; }

    log_info "启动数据库服务..."
    if ! $DOCKER_COMPOSE_CMD up -d db; then
        log_error "启动数据库服务失败"
        return 1
    fi

    log_info "等待数据库就绪..."
    local max_attempts=30
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if $DOCKER_COMPOSE_CMD exec -T db pg_isready -U postgres &>/dev/null; then
            log_success "数据库已就绪"
            break
        fi
        attempt=$((attempt + 1))
        if [ $((attempt % 5)) -eq 0 ]; then
            log_info "仍在等待数据库就绪... ($attempt/$max_attempts)"
        fi
        sleep 2
    done

    if [ $attempt -eq $max_attempts ]; then
        log_error "数据库健康检查超时"
        $DOCKER_COMPOSE_CMD ps db || true
        return 1
    fi

    log_info "运行数据库初始化..."
    if $DOCKER_COMPOSE_CMD --profile init run --rm db-init; then
        log_success "数据库初始化完成"
    else
        log_error "数据库初始化失败"
        return 1
    fi
}

# =============================================================================
# 后台进程清理
# =============================================================================

cleanup_background() {
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        log_info "停止后端服务 (PID: $BACKEND_PID)..."
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
}

# =============================================================================
# 服务信息展示
# =============================================================================

show_service_info() {
    echo ""
    echo "=========================================="
    echo "  服务信息"
    echo "=========================================="
    echo ""

    case "$STARTUP_MODE" in
        docker)
            local fe_url be_url
            fe_url=$(build_url "$URL_SCHEME" "$HOST_ADDR" "$PORT_FRONTEND")
            be_url=$(build_url "$URL_SCHEME" "$HOST_ADDR" "$PORT_BACKEND")
            echo "访问地址:"
            echo "  前端: $fe_url"
            echo "  后端 API: $be_url"
            echo "  API 文档: $be_url/docs"
            echo ""
            echo "常用命令:"
            echo "  查看日志: $DOCKER_COMPOSE_CMD logs -f [service]"
            echo "  停止服务: $DOCKER_COMPOSE_CMD down"
            echo "  重启服务: $DOCKER_COMPOSE_CMD restart [service]"
            echo "  查看状态: $DOCKER_COMPOSE_CMD ps"
            ;;
        frontend)
            local be_url_fe
            be_url_fe=$(build_url "$URL_SCHEME" "$BACKEND_ADDR" "$PORT_BACKEND")
            echo "访问地址:"
            echo "  前端: http://localhost:$PORT_FRONTEND"
            echo "  后端 API: $be_url_fe"
            echo ""
            echo "按 Ctrl+C 停止前端服务"
            ;;
        backend)
            local fe_url_be
            fe_url_be=$(build_url "$URL_SCHEME" "$FRONTEND_ADDR" "$PORT_FRONTEND")
            echo "访问地址:"
            echo "  后端 API: http://localhost:$PORT_BACKEND"
            echo "  API 文档: http://localhost:$PORT_BACKEND/docs"
            echo "  数据库: $DB_ADDR:$PORT_POSTGRES"
            echo "  Redis: $REDIS_ADDR:$PORT_REDIS"
            echo "  CORS 允许: $fe_url_be"
            echo ""
            echo "按 Ctrl+C 停止后端服务"
            ;;
        both)
            local fe_url_both be_url_both
            fe_url_both=$(build_url "$URL_SCHEME" "$FRONTEND_ADDR" "$PORT_FRONTEND")
            be_url_both=$(build_url "$URL_SCHEME" "$BACKEND_ADDR" "$PORT_BACKEND")
            echo "访问地址:"
            echo "  前端: $fe_url_both"
            echo "  后端 API: $be_url_both"
            echo "  API 文档: $be_url_both/docs"
            echo ""
            echo "按 Ctrl+C 停止所有服务"
            ;;
    esac
    echo ""
}

# =============================================================================
# 启动模式实现
# =============================================================================

start_mode_docker() {
    log_step "Docker Compose 全栈启动..."
    echo ""

    check_docker_running || exit 1
    detect_docker_compose || exit 1

    setup_env
    echo ""

    if [ "$SKIP_ENV" = false ]; then
        check_tavily_api_key
        echo ""
        check_openclaw_config
        echo ""
    fi

    if [ "$SKIP_DB_INIT" = false ]; then
        if ! init_database; then
            log_error "数据库初始化失败"
            exit 1
        fi
        echo ""
    else
        log_info "跳过数据库初始化"
        echo ""
    fi

    log_step "启动 Docker Compose 服务..."
    cd "$DEPLOY_DIR" || { log_error "无法进入 deploy 目录"; exit 1; }

    # 检查是否已有服务在运行
    if $DOCKER_COMPOSE_CMD ps 2>/dev/null | grep -q "Up"; then
        log_warning "检测到已有服务在运行"
        printf "是否重启服务？(y/N): "
        read -r
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "停止现有服务..."
            $DOCKER_COMPOSE_CMD down
        else
            log_info "使用现有服务"
            show_service_info
            return 0
        fi
    fi

    if ! $DOCKER_COMPOSE_CMD up -d; then
        log_error "启动服务失败"
        exit 1
    fi

    log_info "等待服务启动..."
    sleep 5
    $DOCKER_COMPOSE_CMD ps

    show_service_info
    log_success "Docker Compose 全栈启动完成！"
    log_warning "首次启动时后端构建可能需要 2-3 分钟，服务完全就绪前访问可能会失败"
    log_info "查看实时启动进度: $DOCKER_COMPOSE_CMD logs -f backend"

    # 远程服务器部署提示
    if [ "$HOST_ADDR" != "localhost" ]; then
        echo ""
        echo "=========================================="
        echo "  远程部署安全提示"
        echo "=========================================="
        echo ""
        echo "  当前部署地址: ${URL_SCHEME}://${HOST_ADDR}"
        echo ""
        echo "  建议："
        echo "  1. 使用 Nginx/Caddy 做反向代理和 HTTPS 终止"
        echo "  2. 仅暴露 80/443 端口到公网"
        echo "  3. 修改 backend/.env 中的 SECRET_KEY 和 CREDENTIAL_ENCRYPTION_KEY"
        echo "  4. 设置 DEBUG=false"
        echo "  5. 通过防火墙限制 PostgreSQL/Redis/MCP 端口"
        echo ""
        echo "  详细指南: deploy/PRODUCTION_IP_GUIDE.md"
        echo ""
    fi
}

start_mode_frontend() {
    log_step "本地前端启动..."
    echo ""

    check_local_deps false true

    setup_env

    local backend_url
    backend_url=$(build_url "$URL_SCHEME" "$BACKEND_ADDR" "$PORT_BACKEND")

    check_backend_reachable "$BACKEND_ADDR"
    echo ""

    export NEXT_PUBLIC_API_URL="$backend_url"

    log_step "安装前端依赖..."
    cd "$PROJECT_ROOT/frontend" || { log_error "前端目录不存在: $PROJECT_ROOT/frontend"; exit 1; }
    bun install
    log_success "依赖已就绪"
    echo ""

    show_service_info

    log_step "启动前端 (port $PORT_FRONTEND)..."
    PORT="$PORT_FRONTEND" bun run dev
}

start_mode_backend() {
    log_step "本地后端启动..."
    echo ""

    check_local_deps true false
    echo ""

    # 远程 DB/Redis 时不需要本地 Docker
    if [ "$DB_ADDR" = "localhost" ]; then
        check_docker_running || exit 1
        detect_docker_compose || exit 1
    fi

    setup_env

    if [ "$DB_ADDR" = "localhost" ]; then
        # 本地中间件：检查 Docker 中的数据库
        log_step "检查中间件（数据库）是否就绪..."
        cd "$DEPLOY_DIR" || { log_error "无法进入 deploy 目录"; exit 1; }
        if ! wait_for_db_service "docker-compose-middleware.yml" "db" 10; then
            log_error "数据库未就绪，请先启动中间件："
            echo "  ./deploy/scripts/start-middleware.sh  或  ./deploy/scripts/dev-local.sh"
            exit 1
        fi
        log_success "数据库已就绪"
        echo ""
    fi

    if [ ! -f "$PROJECT_ROOT/backend/.env" ]; then
        log_error "backend/.env 不存在，请先运行不带 --skip-env 或从 backend/env.example 复制"
        exit 1
    fi

    local frontend_url
    frontend_url=$(build_url "$URL_SCHEME" "$FRONTEND_ADDR" "$PORT_FRONTEND")

    export POSTGRES_HOST="$DB_ADDR"
    export POSTGRES_PORT="$PORT_POSTGRES"
    export POSTGRES_PORT_HOST="$PORT_POSTGRES"
    export REDIS_URL="redis://$REDIS_ADDR:$PORT_REDIS/0"
    export FRONTEND_URL="$frontend_url"
    export CORS_ORIGINS="[\"$frontend_url\"]"

    log_step "安装后端依赖..."
    cd "$PROJECT_ROOT/backend" || { log_error "后端目录不存在: $PROJECT_ROOT/backend"; exit 1; }
    if [ ! -d ".venv" ]; then
        log_info "创建虚拟环境..."
        uv venv
    fi
    uv sync
    log_success "依赖已就绪"
    echo ""

    log_step "执行数据库迁移..."
    uv run alembic upgrade head
    log_success "迁移完成"
    echo ""

    show_service_info

    log_step "启动后端 (uvicorn --reload, port $PORT_BACKEND)..."
    uv run uvicorn app.main:app --reload --host 0.0.0.0 --port "$PORT_BACKEND"
}

start_mode_both() {
    log_step "本地前端 + 后端启动..."
    echo ""

    check_docker_running || exit 1
    detect_docker_compose || exit 1
    check_local_deps true true
    echo ""

    setup_env

    # 启动中间件
    log_step "启动中间件 (PostgreSQL + Redis)..."
    cd "$DEPLOY_DIR" || { log_error "无法进入 deploy 目录"; exit 1; }
    $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml up -d db redis
    echo ""

    log_info "等待数据库就绪..."
    if ! wait_for_db_service "docker-compose-middleware.yml" "db" 30; then
        log_error "数据库健康检查超时"
        exit 1
    fi
    log_success "数据库已就绪"
    echo ""

    # 数据库初始化
    if [ "$SKIP_DB_INIT" = false ]; then
        log_info "运行数据库初始化..."
        $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml --profile init run --rm db-init 2>/dev/null || {
            log_warning "数据库初始化跳过（可能已初始化或 db-init 服务不存在）"
        }
        echo ""
    fi

    if [ ! -f "$PROJECT_ROOT/backend/.env" ]; then
        log_error "backend/.env 不存在"
        exit 1
    fi

    # 注入环境变量
    local frontend_url backend_url
    frontend_url=$(build_url "$URL_SCHEME" "$FRONTEND_ADDR" "$PORT_FRONTEND")
    backend_url=$(build_url "$URL_SCHEME" "$BACKEND_ADDR" "$PORT_BACKEND")

    export POSTGRES_HOST="$DB_ADDR"
    export POSTGRES_PORT="$PORT_POSTGRES"
    export POSTGRES_PORT_HOST="$PORT_POSTGRES"
    export REDIS_URL="redis://$REDIS_ADDR:$PORT_REDIS/0"
    export FRONTEND_URL="$frontend_url"
    export CORS_ORIGINS="[\"$frontend_url\"]"
    export NEXT_PUBLIC_API_URL="$backend_url"

    # 安装后端依赖 + 迁移
    log_step "安装后端依赖..."
    cd "$PROJECT_ROOT/backend" || { log_error "后端目录不存在: $PROJECT_ROOT/backend"; exit 1; }
    if [ ! -d ".venv" ]; then
        uv venv
    fi
    uv sync
    log_success "后端依赖已就绪"

    log_step "执行数据库迁移..."
    uv run alembic upgrade head
    log_success "迁移完成"
    echo ""

    # 注册清理 trap（覆盖全局 ERR trap，确保清理后端进程）
    trap 'cleanup_background; log_error "脚本在第 $LINENO 行异常退出 (退出码 $?)"' ERR
    trap cleanup_background EXIT INT TERM

    # 后端后台启动
    log_step "启动后端 (后台, port $PORT_BACKEND)..."
    uv run uvicorn app.main:app --reload --host 0.0.0.0 --port "$PORT_BACKEND" &
    BACKEND_PID=$!

    # 等待后端启动
    sleep 3
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        log_error "后端启动失败"
        exit 1
    fi
    log_success "后端已启动 (PID: $BACKEND_PID)"
    echo ""

    # 安装前端依赖
    log_step "安装前端依赖..."
    cd "$PROJECT_ROOT/frontend" || { log_error "前端目录不存在: $PROJECT_ROOT/frontend"; exit 1; }
    bun install
    log_success "前端依赖已就绪"
    echo ""

    show_service_info

    # 前端前台启动（Ctrl+C 触发 trap 清理后端）
    log_step "启动前端 (前台, port $PORT_FRONTEND)..."
    log_info "按 Ctrl+C 停止所有服务"
    echo ""
    PORT="$PORT_FRONTEND" bun run dev
}

# =============================================================================
# 主函数
# =============================================================================

main() {
    parse_args "$@"
    detect_os

    echo "=========================================="
    echo "  JoySafeter - 快速启动"
    echo "=========================================="

    show_mode_menu
    echo ""
    collect_ports
    echo ""

    case "$STARTUP_MODE" in
        docker)   start_mode_docker ;;
        frontend) start_mode_frontend ;;
        backend)  start_mode_backend ;;
        both)     start_mode_both ;;
    esac
}

main "$@"
