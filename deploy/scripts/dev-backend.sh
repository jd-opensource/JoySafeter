#!/bin/bash
# 本地开发：仅启动后端（中间件需已通过 start-middleware.sh 或 dev-local.sh 启动）
# 使用方式：从项目根目录执行 ./deploy/scripts/dev-backend.sh，或 cd deploy/scripts && ./dev-backend.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

BACKEND_DIR="$PROJECT_ROOT/backend"
SKIP_ENV=false
SKIP_DB_CHECK=false

show_usage() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -h, --help          显示帮助信息
  --skip-env          跳过 .env 文件初始化
  --skip-db-check     跳过数据库就绪检查（中间件未启动时使用会失败）

说明:
  - 仅启动本地后端，依赖 Docker 中的 PostgreSQL、Redis 已就绪
  - 请先执行 ./deploy/scripts/start-middleware.sh 或 ./deploy/scripts/dev-local.sh
EOF
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
            --skip-db-check)
                SKIP_DB_CHECK=true
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
    echo "  本地后端开发启动"
    echo "=========================================="
    echo ""

    check_docker_running
    detect_docker_compose
    echo ""

    if [ "$SKIP_ENV" = false ]; then
        init_env_files
        echo ""
    else
        load_deploy_env
    fi

    if [ "$SKIP_DB_CHECK" = false ]; then
        log_step "检查中间件（数据库）是否就绪..."
        cd "$DEPLOY_DIR"
        if ! wait_for_db_service "docker-compose-middleware.yml" "db" 30; then
            log_error "数据库未就绪，请先启动中间件："
            echo "  ./deploy/scripts/start-middleware.sh  或  ./deploy/scripts/dev-local.sh"
            exit 1
        fi
        log_success "数据库已就绪"
        cd - >/dev/null
        echo ""
    fi

    if [ ! -f "$BACKEND_DIR/.env" ]; then
        log_error "backend/.env 不存在，请先运行不带 --skip-env 或从 backend/env.example 复制"
        exit 1
    fi

    # 注入本地开发环境变量（连接 Docker 映射的宿主机端口）
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT_HOST="${POSTGRES_PORT_HOST:-5432}"
    export POSTGRES_PORT="${POSTGRES_PORT_HOST:-5432}"
    export REDIS_URL="redis://localhost:${REDIS_PORT_HOST:-6379}/0"
    # 与 deploy/.env 一致，并同步到 CORS，避免通过 IP 或非默认端口访问前端时 CORS 报错
    _frontend_url="${FRONTEND_URL:-http://localhost:3000}"
    export FRONTEND_URL="$_frontend_url"
    # 使用 JSON 数组格式，避免 pydantic 解析 CORS_ORIGINS 时报错
    export CORS_ORIGINS="[\"$_frontend_url\"]"

    log_step "进入后端目录并安装依赖..."
    cd "$BACKEND_DIR"

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

    local backend_port="${BACKEND_PORT_HOST:-8000}"
    log_step "启动后端 (uvicorn --reload, port $backend_port)..."
    log_info "按 Ctrl+C 停止"
    echo ""
    uv run uvicorn app.main:app --reload --host 0.0.0.0 --port "$backend_port"
}

main "$@"
