#!/bin/bash
# 本地开发启动脚本
# 仅启动中间件容器，后端和前端在本地运行

set -e

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

SKIP_ENV=false
SKIP_DB_INIT=false
SKIP_MCP=false

show_usage() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -h, --help          显示帮助信息
  --skip-env          跳过 .env 文件初始化
  --skip-db-init      跳过数据库初始化（db-init）
  --skip-mcp          不启动 MCP 服务（mcpserver）

说明:
  - 仅启动中间件（PostgreSQL + Redis [+可选 MCP]）
  - 后端与前端在本地运行（非容器）
EOF
}

# 检查命令
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 未安装"
        return 1
    fi
    return 0
}

# 检查本地开发环境
check_local_env() {
    log_info "检查本地开发环境..."

    local missing=0

    # 检查 Python
    if ! check_command python3 && ! check_command python; then
        log_error "Python 未安装"
        missing=$((missing + 1))
    else
        local python_cmd=$(command -v python3 || command -v python)
        local python_version=$($python_cmd --version 2>&1 | cut -d' ' -f2)
        log_success "Python 已安装 (版本: $python_version)"
    fi

    # 检查 Node.js
    if ! check_command node; then
        log_error "Node.js 未安装"
        missing=$((missing + 1))
    else
        local node_version=$(node --version)
        log_success "Node.js 已安装 (版本: $node_version)"
    fi

    # 检查 uv (Python 包管理器)
    if ! check_command uv; then
        log_warning "uv 未安装（推荐安装以加速 Python 依赖管理）"
        echo "  安装方法: curl -LsSf https://astral.sh/uv/install.sh | sh"
    else
        log_success "uv 已安装"
    fi

    # 检查 bun/npm/pnpm (Node.js 包管理器)
    if ! check_command bun && ! check_command npm && ! check_command pnpm; then
        log_error "Node.js 包管理器未安装（需要 bun、npm 或 pnpm）"
        missing=$((missing + 1))
    else
        local pkg_mgr=$(command -v bun || command -v pnpm || command -v npm)
        log_success "Node.js 包管理器已安装: $(basename $pkg_mgr)"
    fi

    if [ $missing -gt 0 ]; then
        log_error "本地开发环境检查失败，请先安装缺失的依赖"
        exit 1
    fi

    log_success "本地开发环境检查通过"
}

# 检查配置文件
check_config() {
    log_info "检查配置文件..."

    # deploy/.env（用于端口映射与 URL 变量）
    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        log_warning "deploy/.env 文件不存在"
        if [ -f "$DEPLOY_DIR/.env.example" ]; then
            cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
            log_success "已从示例文件创建 deploy/.env"
        else
            log_warning "deploy/.env.example 不存在，跳过"
        fi
    fi

    if [ ! -f "$BACKEND_DIR/.env" ]; then
        log_warning "backend/.env 文件不存在"
        if [ -f "$BACKEND_DIR/env.example" ]; then
            cp "$BACKEND_DIR/env.example" "$BACKEND_DIR/.env"
            log_success "已从示例文件创建 backend/.env"
        else
            log_error "backend/env.example 不存在"
            exit 1
        fi
    fi

    if [ ! -f "$FRONTEND_DIR/.env.local" ] && [ ! -f "$FRONTEND_DIR/.env" ]; then
        log_warning "frontend/.env.local 文件不存在（可选）"
    fi
}

start_middleware() {
    log_step "启动中间件服务（PostgreSQL + Redis）..."
    cd "$DEPLOY_DIR"

    log_info "启动 PostgreSQL + Redis..."
    $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml up -d db redis

    log_info "等待数据库就绪..."
    if ! wait_for_db_service "docker-compose-middleware.yml" "db" 30; then
        log_error "数据库健康检查超时"
        $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml ps db || true
        exit 1
    fi

    if [ "$SKIP_DB_INIT" = false ]; then
        log_info "运行数据库初始化..."
        $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml --profile init run --rm db-init
        log_success "数据库初始化完成"
    else
        log_info "跳过数据库初始化"
    fi

    if [ "$SKIP_MCP" = false ]; then
        log_info "启动 MCP 服务..."
        $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml up -d mcpserver
        log_success "MCP 服务已启动"
    else
        log_info "跳过 MCP 服务启动"
    fi
}

# 显示启动说明
show_startup_info() {
    echo ""
    echo "=========================================="
    echo "  本地开发环境信息"
    echo "=========================================="

    # 读取端口配置
    local postgres_port=5432
    local redis_port=6379
    local backend_port=8000
    local frontend_port=3000

    if [ -f "$DEPLOY_DIR/.env" ]; then
        source "$DEPLOY_DIR/.env" 2>/dev/null || true
        postgres_port=${POSTGRES_PORT_HOST:-5432}
        redis_port=${REDIS_PORT_HOST:-6379}
        backend_port=${BACKEND_PORT_HOST:-8000}
        frontend_port=${FRONTEND_PORT_HOST:-3000}
    fi

    echo ""
    echo "中间件服务:"
    echo "  PostgreSQL: localhost:$postgres_port"
    echo "  Redis: localhost:$redis_port"
    echo ""
    echo "下一步操作:"
    echo ""
    echo "1. 启动后端（推荐，新终端）:"
    echo "   $PROJECT_ROOT/deploy/scripts/dev-backend.sh"
    echo ""
    echo "2. 启动前端（推荐，新终端）:"
    echo "   $PROJECT_ROOT/deploy/scripts/dev-frontend.sh"
    echo ""
    echo "或手动启动:"
    echo "  后端: cd $BACKEND_DIR && uv venv && source .venv/bin/activate && uv sync && alembic upgrade head && uv run uvicorn app.main:app --reload --port $backend_port"
    echo "  前端: cd $FRONTEND_DIR && bun install && bun run dev   # 或 npm/pnpm"
    echo ""
    echo "访问地址:"
    echo "  前端: http://localhost:$frontend_port"
    echo "  后端 API: http://localhost:$backend_port"
    echo "  API 文档: http://localhost:$backend_port/docs"
    echo ""
    echo "常用命令:"
    echo "  查看中间件日志: $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml logs -f"
    echo "  停止中间件: $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml down"
    echo "  进入数据库: $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml exec db psql -U postgres"
    echo ""
}

# 主函数
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
            --skip-db-init)
                SKIP_DB_INIT=true
                shift
                ;;
            --skip-mcp)
                SKIP_MCP=true
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
    echo "  本地开发环境启动"
    echo "=========================================="
    echo ""

    check_docker_running
    detect_docker_compose
    echo ""

    if [ "$SKIP_ENV" = false ]; then
        init_env_files
        echo ""
        check_tavily_api_key
        echo ""
    else
        log_info "跳过 .env 文件初始化"
        echo ""
        load_deploy_env
    fi

    check_local_env
    echo ""

    check_config
    echo ""

    start_middleware
    echo ""

    show_startup_info

    log_success "本地开发环境已就绪！"
    echo ""
    log_info "提示: 现在可以在本地运行后端和前端服务了"
}

# 运行主函数
main "$@"
