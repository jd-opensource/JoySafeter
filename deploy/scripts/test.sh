#!/bin/bash
# 测试场景启动脚本
# 快速测试环境，最小化配置

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 日志函数
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# 检查配置文件
check_config() {
    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        log_warning "deploy/.env 文件不存在，使用默认配置"
        # 创建最小化配置
        cat > "$DEPLOY_DIR/.env" << EOF
BACKEND_PORT_HOST=8000
FRONTEND_PORT_HOST=3000
POSTGRES_PORT_HOST=5432
REDIS_PORT_HOST=6379
BACKEND_HOST=localhost
FRONTEND_HOSTNAME=localhost
FRONTEND_URL=http://localhost:3000
EOF
        log_success "已创建最小化配置"
    fi

    if [ ! -f "$DEPLOY_DIR/../backend/.env" ]; then
        log_warning "backend/.env 文件不存在，使用默认配置"
        if [ -f "$DEPLOY_DIR/../backend/env.example" ]; then
            cp "$DEPLOY_DIR/../backend/env.example" "$DEPLOY_DIR/../backend/.env"
            log_success "已从示例文件创建配置"
        else
            log_error "backend/env.example 不存在"
            exit 1
        fi
    fi
}

# 启动服务
start_services() {
    log_info "启动测试环境服务..."

    cd "$DEPLOY_DIR"

    # 启动中间件
    log_info "启动中间件..."
    "$DEPLOY_DIR/scripts/start-middleware.sh"

    # 启动完整服务（使用开发配置，但快速启动）
    log_info "启动测试服务..."
    docker-compose up -d

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
    echo "  ✅ 最小化配置"
    echo "  ✅ 适合功能测试"
    echo ""
    echo "常用命令:"
    echo "  查看日志: docker-compose logs -f"
    echo "  停止服务: docker-compose down"
    echo "  清理数据: docker-compose down -v"
    echo ""
}

# 主函数
main() {
    echo "=========================================="
    echo "  测试环境启动"
    echo "=========================================="
    echo ""

    check_config

    start_services

    show_info

    log_success "测试环境已就绪！"
}

# 运行主函数
main "$@"
