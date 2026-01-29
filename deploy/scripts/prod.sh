#!/bin/bash
# 生产场景启动脚本
# 使用 docker-compose.prod.yml，使用预构建镜像

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

    # 确保中间件已启动
    log_info "检查中间件服务..."
    if ! docker-compose -f docker-compose-middleware.yml ps | grep -q "Up"; then
        log_info "启动中间件..."
        "$DEPLOY_DIR/scripts/start-middleware.sh"
    fi

    # 启动生产服务
    log_info "启动生产服务..."
    docker-compose -f docker-compose.prod.yml up -d

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
    echo "  查看日志: docker-compose -f docker-compose.prod.yml logs -f"
    echo "  停止服务: docker-compose -f docker-compose.prod.yml down"
    echo "  重启服务: docker-compose -f docker-compose.prod.yml restart"
    echo "  查看状态: docker-compose -f docker-compose.prod.yml ps"
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
    echo "=========================================="
    echo "  生产环境启动"
    echo "=========================================="
    echo ""

    check_config
    echo ""

    pull_images
    echo ""

    start_services
    echo ""

    show_info

    log_success "生产环境已就绪！"
}

# 运行主函数
main "$@"
