#!/bin/bash
# 本地开发：仅启动前端（后端可选，建议先启动以使用完整功能）
# 使用方式：从项目根目录执行 ./deploy/scripts/dev-frontend.sh，或 cd deploy/scripts && ./dev-frontend.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

FRONTEND_DIR="$PROJECT_ROOT/frontend"
SKIP_ENV=false
SKIP_BACKEND_CHECK=false

show_usage() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -h, --help              显示帮助信息
  --skip-env              跳过 .env 文件初始化
  --skip-backend-check    不检查后端是否可达

说明:
  - 仅启动本地前端 dev 服务器
  - 建议先启动后端 ./deploy/scripts/dev-backend.sh 以使用完整 API
EOF
}

# 检查后端是否可达（TCP 或 HTTP），失败仅 warning
check_backend_reachable() {
    local host="localhost"
    local port="${BACKEND_PORT_HOST:-8000}"
    local url="${BACKEND_URL:-http://localhost:8000}"
    url="${url%/}"

    if command -v curl >/dev/null 2>&1; then
        if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "$url/docs" 2>/dev/null | grep -q '200'; then
            log_success "后端可达: $url"
            return 0
        fi
    fi
    if command -v nc >/dev/null 2>&1; then
        if nc -z "$host" "$port" 2>/dev/null; then
            log_success "后端端口 $host:$port 已监听"
            return 0
        fi
    fi
    log_warning "未检测到后端服务，部分功能可能不可用。请先启动: ./deploy/scripts/dev-backend.sh"
    return 0
}

main() {
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
            --skip-backend-check)
                SKIP_BACKEND_CHECK=true
                shift
                ;;
            *)
                log_error "未知选项: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    echo "=========================================="
    echo "  本地前端开发启动"
    echo "=========================================="
    echo ""

    if [ "$SKIP_ENV" = false ]; then
        init_env_files
        echo ""
    else
        load_deploy_env
    fi

    if [ "$SKIP_BACKEND_CHECK" = false ]; then
        check_backend_reachable
        echo ""
    fi

    # 前端请求后端的地址（去掉末尾斜杠）
    local backend_url="${BACKEND_URL:-http://localhost:8000}"
    backend_url="${backend_url%/}"
    export NEXT_PUBLIC_API_URL="$backend_url"

    log_step "检测包管理器并安装依赖..."
    cd "$FRONTEND_DIR"

    local pkg_mgr=""
    if command -v bun >/dev/null 2>&1; then
        pkg_mgr="bun"
    elif command -v pnpm >/dev/null 2>&1; then
        pkg_mgr="pnpm"
    elif command -v npm >/dev/null 2>&1; then
        pkg_mgr="npm"
    else
        log_error "未找到 bun、pnpm 或 npm，请先安装 Node.js 及任一包管理器"
        exit 1
    fi

    log_info "使用: $pkg_mgr"
    $pkg_mgr install
    log_success "依赖已就绪"
    echo ""

    local frontend_port="${FRONTEND_PORT_HOST:-3000}"
    log_step "启动前端 (port $frontend_port)..."
    log_info "按 Ctrl+C 停止"
    echo ""
    PORT="$frontend_port" $pkg_mgr run dev
}

main "$@"
