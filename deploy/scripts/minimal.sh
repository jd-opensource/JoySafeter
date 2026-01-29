#!/bin/bash
# 最小化场景启动脚本
# 仅启动中间件（数据库+Redis）

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
    log_info "启动最小化环境（仅中间件）..."

    cd "$DEPLOY_DIR"

    # 启动中间件
    "$DEPLOY_DIR/scripts/start-middleware.sh"

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
    echo "  ✅ 数据库已初始化"
    echo ""
    echo "适用场景:"
    echo "  • 本地开发（后端和前端在本地运行）"
    echo "  • 仅需要数据库和缓存服务"
    echo "  • 测试数据库连接"
    echo ""
    echo "常用命令:"
    echo "  查看日志: docker-compose -f docker-compose-middleware.yml logs -f"
    echo "  停止服务: docker-compose -f docker-compose-middleware.yml down"
    echo "  进入数据库: docker-compose -f docker-compose-middleware.yml exec db psql -U postgres"
    echo "  进入 Redis: docker-compose -f docker-compose-middleware.yml exec redis redis-cli"
    echo ""
    echo "下一步:"
    echo "  启动完整服务: ./scripts/dev.sh"
    echo "  或使用本地开发: ./scripts/dev-local.sh"
    echo ""
}

# 主函数
main() {
    echo "=========================================="
    echo "  最小化环境启动"
    echo "=========================================="
    echo ""

    check_config

    start_services

    show_info

    log_success "最小化环境已就绪！"
}

# 运行主函数
main "$@"
