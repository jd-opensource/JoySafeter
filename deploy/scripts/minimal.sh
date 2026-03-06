#!/bin/bash
# 最小化场景启动脚本
# 仅启动中间件（数据库+Redis）

set -e

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

SKIP_ENV=false
SKIP_DB_INIT=false
WITH_MCP=false

show_usage() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -h, --help          显示帮助信息
  --skip-env          跳过 .env 文件初始化
  --skip-db-init      跳过数据库初始化（db-init）
  --with-mcp          同时启动 MCP 服务（mcpserver）

说明:
  - 最小化场景默认仅启动 PostgreSQL + Redis
  - 如需 MCP 服务，请加 --with-mcp
EOF
}

start_services() {
    log_step "启动最小化环境（仅中间件）..."
    cd "$DEPLOY_DIR"

    log_info "启动 PostgreSQL + Redis..."
    $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml up -d db redis

    log_info "等待数据库就绪..."
    if ! wait_for_db_service "docker-compose-middleware.yml" "db" 30; then
        log_error "数据库健康检查超时"
        $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml ps db || true
        return 1
    fi

    if [ "$SKIP_DB_INIT" = false ]; then
        log_info "运行数据库初始化..."
        $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml --profile init run --rm db-init
        log_success "数据库初始化完成"
    else
        log_info "跳过数据库初始化"
    fi

    if [ "$WITH_MCP" = true ]; then
        log_info "启动 MCP 服务..."
        $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml up -d mcpserver
        log_success "MCP 服务已启动"
    fi

    log_success "最小化环境启动完成"
}

# 显示服务信息
show_info() {
    echo ""
    echo "=========================================="
    echo "  最小化环境服务信息"
    echo "=========================================="

    # 读取端口配置
    local postgres_port=5432
    local redis_port=6379

    if [ -f "$DEPLOY_DIR/.env" ]; then
        source "$DEPLOY_DIR/.env" 2>/dev/null || true
        postgres_port=${POSTGRES_PORT_HOST:-5432}
        redis_port=${REDIS_PORT_HOST:-6379}
    fi

    echo ""
    echo "服务信息:"
    echo "  PostgreSQL: localhost:$postgres_port"
    echo "  Redis: localhost:$redis_port"
    echo ""
    echo "已启动服务:"
    echo "  ✅ PostgreSQL 数据库"
    echo "  ✅ Redis 缓存"
    if [ "$SKIP_DB_INIT" = false ]; then
        echo "  ✅ 数据库已初始化"
    else
        echo "  ⚠️  数据库未初始化（使用 --skip-db-init 跳过）"
    fi
    echo ""
    echo "适用场景:"
    echo "  • 本地开发（后端和前端在本地运行）"
    echo "  • 仅需要数据库和缓存服务"
    echo "  • 测试数据库连接"
    echo ""
    echo "常用命令:"
    echo "  查看日志: $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml logs -f"
    echo "  停止服务: $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml down"
    echo "  进入数据库: $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml exec db psql -U postgres"
    echo "  进入 Redis: $DOCKER_COMPOSE_CMD -f docker-compose-middleware.yml exec redis redis-cli"
    echo ""
    echo "下一步:"
    echo "  启动完整服务: ./scripts/dev.sh"
    echo "  或使用本地开发: ./scripts/dev-local.sh"
    if [ "$WITH_MCP" = false ]; then
        echo "  如需 MCP: $0 --with-mcp"
    fi
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
            --with-mcp)
                WITH_MCP=true
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
    echo "  最小化环境启动"
    echo "=========================================="
    echo ""

    check_docker_running
    detect_docker_compose

    if [ "$SKIP_ENV" = false ]; then
        init_env_files
        echo ""
        check_tavily_api_key
        echo ""
    else
        log_info "跳过 .env 文件初始化"
        echo ""
    fi

    start_services

    show_info

    log_success "最小化环境已就绪！"
}

# 运行主函数
main "$@"
