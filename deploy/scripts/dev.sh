#!/bin/bash
# 开发场景启动脚本
# 使用 docker-compose.yml，支持代码挂载和热重载

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
        log_error "deploy/.env 文件不存在"
        echo "请先运行安装脚本: cd $DEPLOY_DIR && ./install.sh"
        exit 1
    fi

    if [ ! -f "$DEPLOY_DIR/../backend/.env" ]; then
        log_error "backend/.env 文件不存在"
        echo "请先运行安装脚本: cd $DEPLOY_DIR && ./install.sh"
        exit 1
    fi
}

# 启动服务
start_services() {
    log_info "启动开发环境服务..."

    cd "$DEPLOY_DIR"

    # 确保中间件已启动
    log_info "检查中间件服务..."
    if ! docker-compose -f docker-compose-middleware.yml ps | grep -q "Up"; then
        log_info "启动中间件..."
        "$DEPLOY_DIR/scripts/start-middleware.sh"
    fi

    # 启动完整服务
    log_info "启动完整服务（开发模式）..."
    docker-compose up -d --build

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
    echo "  查看日志: docker-compose logs -f [service]"
    echo "  停止服务: docker-compose down"
    echo "  重启服务: docker-compose restart [service]"
    echo "  查看状态: docker-compose ps"
    echo ""
}

# 主函数
main() {
    echo "=========================================="
    echo "  开发环境启动"
    echo "=========================================="
    echo ""

    check_config

    start_services

    show_info

    log_success "开发环境已就绪！"
}

# 运行主函数
main "$@"
