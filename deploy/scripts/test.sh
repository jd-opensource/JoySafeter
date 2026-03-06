#!/bin/bash
# 测试场景启动脚本
# 快速测试环境，最小化配置

set -e

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

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
  - 先启动中间件（PostgreSQL + Redis [+可选 MCP]）
  - 再使用 deploy/docker-compose.yml 启动完整服务（快速验证/功能测试）
EOF
}

# 检查配置文件
check_config() {
    if [ "$SKIP_ENV" = false ]; then
        init_env_files
        echo ""
        check_tavily_api_key
        echo ""
    else
        log_info "跳过 .env 文件初始化"
        load_deploy_env
        echo ""
    fi

    # 若跳过 env 初始化，仍需确保 backend/.env 存在（供中间件与容器读取）
    if [ ! -f "$PROJECT_ROOT/backend/.env" ]; then
        log_warning "backend/.env 文件不存在，将从示例文件创建"
        if [ -f "$PROJECT_ROOT/backend/env.example" ]; then
            cp "$PROJECT_ROOT/backend/env.example" "$PROJECT_ROOT/backend/.env"
            log_success "已创建 backend/.env"
        else
            log_error "backend/env.example 不存在"
            exit 1
        fi
    fi
}

# 启动服务
start_services() {
    cd "$DEPLOY_DIR"

    # 启动中间件
    log_info "启动中间件..."
    middleware_args=()
    if [ "$SKIP_ENV" = true ]; then
        middleware_args+=(--skip-env)
    fi
    if [ "$SKIP_DB_INIT" = true ]; then
        middleware_args+=(--skip-db-init)
    fi
    if [ "$SKIP_MCP" = true ]; then
        middleware_args+=(--skip-mcp)
    fi
    "$DEPLOY_DIR/scripts/start-middleware.sh" "${middleware_args[@]}"

    # 启动完整服务（使用开发配置，但快速启动）
    log_info "启动测试服务..."
    $DOCKER_COMPOSE_CMD up -d

    log_success "测试环境服务启动完成"
}

# 显示服务信息
show_info() {
    echo ""
    echo "=========================================="
    echo "  测试环境服务信息"
    echo "=========================================="

    # 读取端口配置
    local backend_port=8000
    local frontend_port=3000

    if [ -f "$DEPLOY_DIR/.env" ]; then
        source "$DEPLOY_DIR/.env" 2>/dev/null || true
        backend_port=${BACKEND_PORT_HOST:-8000}
        frontend_port=${FRONTEND_PORT_HOST:-3000}
    fi

    echo ""
    echo "访问地址:"
    echo "  前端: http://localhost:$frontend_port"
    echo "  后端 API: http://localhost:$backend_port"
    echo "  API 文档: http://localhost:$backend_port/docs"
    echo ""
    echo "测试环境特性:"
    echo "  ✅ 快速启动"
    echo "  ✅ 使用 deploy/.env.example 默认配置"
    echo "  ✅ 适合功能测试"
    echo ""
    echo "常用命令:"
    echo "  查看日志: $DOCKER_COMPOSE_CMD logs -f"
    echo "  停止服务: $DOCKER_COMPOSE_CMD down"
    echo "  清理数据: $DOCKER_COMPOSE_CMD down -v"
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
    echo "  测试环境启动"
    echo "=========================================="
    echo ""

    check_docker_running
    detect_docker_compose

    check_config

    start_services

    show_info

    log_success "测试环境已就绪！"
}

# 运行主函数
main "$@"
