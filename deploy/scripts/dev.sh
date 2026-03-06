#!/bin/bash
# 开发场景启动脚本
# 使用 docker-compose.yml，支持代码挂载和热重载

set -e

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

# 参数
SKIP_ENV=false
SKIP_DB_INIT=false
NO_BUILD=false

show_usage() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -h, --help          显示帮助信息
  --skip-env          跳过 .env 文件初始化
  --skip-db-init      跳过数据库初始化（db-init）
  --no-build          启动时不执行镜像构建（跳过 --build）

说明:
  - 开发场景使用 deploy/docker-compose.yml
  - 会自动检测 docker compose / docker-compose
  - 默认会执行一次 db-init（可用 --skip-db-init 跳过）

示例:
  $0
  $0 --skip-env
  $0 --skip-db-init
  $0 --no-build
EOF
}

init_database() {
    log_step "初始化数据库..."
    cd "$DEPLOY_DIR"

    log_info "启动数据库服务..."
    $DOCKER_COMPOSE_CMD up -d db

    log_info "等待数据库就绪..."
    if ! wait_for_db_service "docker-compose.yml" "db" 30; then
        log_error "数据库健康检查超时"
        $DOCKER_COMPOSE_CMD ps db || true
        return 1
    fi

    log_info "运行数据库初始化..."
    $DOCKER_COMPOSE_CMD --profile init run --rm db-init
    log_success "数据库初始化完成"
}

start_services() {
    log_step "启动开发环境服务..."
    cd "$DEPLOY_DIR"

    if [ "$NO_BUILD" = true ]; then
        $DOCKER_COMPOSE_CMD up -d
    else
        $DOCKER_COMPOSE_CMD up -d --build
    fi

    log_success "开发环境服务启动完成"
}

# 显示服务信息
show_info() {
    echo ""
    echo "=========================================="
    echo "  开发环境服务信息"
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
    echo "开发特性:"
    echo "  ✅ 代码热重载（修改代码后自动重启）"
    echo "  ✅ 代码挂载（可直接编辑代码）"
    echo "  ✅ 详细日志输出"
    echo ""
    echo "常用命令:"
    echo "  查看日志: $DOCKER_COMPOSE_CMD logs -f [service]"
    echo "  停止服务: $DOCKER_COMPOSE_CMD down"
    echo "  重启服务: $DOCKER_COMPOSE_CMD restart [service]"
    echo "  查看状态: $DOCKER_COMPOSE_CMD ps"
    echo ""
}

# 主函数
main() {
    # 解析参数
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
            --no-build)
                NO_BUILD=true
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
    echo "  开发环境启动"
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

    if [ "$SKIP_DB_INIT" = false ]; then
        init_database
        echo ""
    else
        log_info "跳过数据库初始化"
        echo ""
    fi

    start_services

    show_info

    log_success "开发环境已就绪！"
}

# 运行主函数
main "$@"
