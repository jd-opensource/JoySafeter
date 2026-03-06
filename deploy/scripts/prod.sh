#!/bin/bash
# 生产场景启动脚本
# 使用 docker-compose.prod.yml，使用预构建镜像

set -e

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

SKIP_ENV=false
SKIP_DB_INIT=false
SKIP_PULL=false
SKIP_MCP=false

show_usage() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -h, --help          显示帮助信息
  --skip-env          跳过 .env 文件初始化
  --skip-db-init      跳过数据库初始化（db-init）
  --skip-pull         跳过镜像拉取
  --skip-mcp          不启动 MCP 服务（默认会启动）
EOF
}

# 检查配置文件
check_config() {
    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        log_error "deploy/.env 文件不存在"
        echo "请先运行安装脚本: cd $DEPLOY_DIR && ./install.sh --mode prod"
        exit 1
    fi

    if [ ! -f "$DEPLOY_DIR/../backend/.env" ]; then
        log_error "backend/.env 文件不存在"
        echo "请先运行安装脚本: cd $DEPLOY_DIR && ./install.sh --mode prod"
        exit 1
    fi

    # 检查生产环境配置
    log_info "检查生产环境配置..."

    # 检查 SECRET_KEY
    if grep -q "CHANGE-THIS-IN-PRODUCTION" "$DEPLOY_DIR/../backend/.env"; then
        log_warning "⚠️  警告: SECRET_KEY 仍使用默认值，生产环境不安全！"
        echo "请修改 backend/.env 中的 SECRET_KEY 为强随机字符串"
    fi

    # 检查 DEBUG 模式
    if grep -q "DEBUG=true" "$DEPLOY_DIR/../backend/.env"; then
        log_warning "⚠️  警告: DEBUG 模式已启用，生产环境建议关闭"
    fi
}

# 初始化数据库
init_database() {
    log_step "初始化数据库..."
    cd "$DEPLOY_DIR"

    log_info "启动数据库服务..."
    $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml up -d db

    log_info "等待数据库就绪..."
    if ! wait_for_db_service "docker-compose.prod.yml" "db" 30; then
        log_error "数据库健康检查超时"
        $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml ps db || true
        return 1
    fi

    log_info "运行数据库初始化..."
    $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml --profile init run --rm db-init
    log_success "数据库初始化完成"
}

# 拉取镜像
pull_images() {
    log_info "拉取生产镜像..."

    cd "$DEPLOY_DIR"

    # 读取镜像配置
    local registry="${DOCKER_REGISTRY:-docker.io/jdopensource}"
    local tag="${IMAGE_TAG:-latest}"

    if [ -f "$DEPLOY_DIR/.env" ]; then
        source "$DEPLOY_DIR/.env" 2>/dev/null || true
        registry=${DOCKER_REGISTRY:-$registry}
        tag=${IMAGE_TAG:-$tag}
    fi

    log_info "镜像仓库: $registry"
    log_info "镜像标签: $tag"

    # 使用 deploy.sh 拉取镜像
    if [ -f "$DEPLOY_DIR/deploy.sh" ]; then
        "$DEPLOY_DIR/deploy.sh" pull --registry "$registry" --tag "$tag" || {
            log_warning "镜像拉取失败，将使用本地镜像或构建新镜像"
        }
    else
        log_warning "deploy.sh 不存在，跳过镜像拉取"
    fi
}

# 启动服务
start_services() {
    log_info "启动生产环境服务..."

    cd "$DEPLOY_DIR"
    log_info "启动生产服务..."
    if [ "$SKIP_MCP" = true ]; then
        $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml up -d
    else
        $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml --profile mcpserver up -d
    fi

    log_success "生产环境服务启动完成"
}

# 显示服务信息
show_info() {
    echo ""
    echo "=========================================="
    echo "  生产环境服务信息"
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
    echo "生产环境特性:"
    echo "  ✅ 使用预构建镜像（快速启动）"
    echo "  ✅ 优化配置（性能优化）"
    echo "  ✅ 生产级日志"
    echo ""
    echo "常用命令:"
    echo "  查看日志: $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml logs -f"
    echo "  停止服务: $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml down"
    echo "  重启服务: $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml restart"
    echo "  查看状态: $DOCKER_COMPOSE_CMD -f docker-compose.prod.yml ps"
    echo ""
    echo "安全建议:"
    echo "  ⚠️  确保已修改 SECRET_KEY"
    echo "  ⚠️  确保已关闭 DEBUG 模式"
    echo "  ⚠️  配置 HTTPS 反向代理"
    echo "  ⚠️  配置防火墙规则"
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
            --skip-pull)
                SKIP_PULL=true
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
    echo "  生产环境启动"
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

    check_config
    echo ""

    if [ "$SKIP_PULL" = false ]; then
        pull_images
        echo ""
    else
        log_info "跳过镜像拉取"
        echo ""
    fi
    echo ""

    if [ "$SKIP_DB_INIT" = false ]; then
        init_database
        echo ""
    else
        log_info "跳过数据库初始化"
        echo ""
    fi

    start_services
    echo ""

    show_info

    log_success "生产环境已就绪！"
}

# 运行主函数
main "$@"
