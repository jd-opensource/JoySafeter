#!/bin/bash
# 本地开发启动脚本
# 仅启动中间件容器，后端和前端在本地运行

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
PROJECT_ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

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

    # 确保数据库配置正确（本地开发使用 localhost）
    if grep -q "POSTGRES_HOST=db" "$BACKEND_DIR/.env"; then
        log_info "更新数据库配置为本地连接..."
        # 使用 sed 或直接修改
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' 's/POSTGRES_HOST=db/POSTGRES_HOST=localhost/' "$BACKEND_DIR/.env"
        else
            sed -i 's/POSTGRES_HOST=db/POSTGRES_HOST=localhost/' "$BACKEND_DIR/.env"
        fi
        log_success "数据库配置已更新为 localhost"
    fi

    if [ ! -f "$FRONTEND_DIR/.env.local" ] && [ ! -f "$FRONTEND_DIR/.env" ]; then
        log_warning "frontend/.env.local 文件不存在（可选）"
    fi
}

# 启动中间件
start_middleware() {
    log_info "启动中间件服务（PostgreSQL + Redis）..."

    "$DEPLOY_DIR/scripts/start-middleware.sh"
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
    fi

    echo ""
    echo "中间件服务:"
    echo "  PostgreSQL: localhost:$postgres_port"
    echo "  Redis: localhost:$redis_port"
    echo ""
    echo "下一步操作:"
    echo ""
    echo "1. 启动后端服务:"
    echo "   cd $BACKEND_DIR"
    echo "   uv venv && source .venv/bin/activate"
    echo "   uv sync"
    echo "   alembic upgrade head"
    echo "   uv run uvicorn app.main:app --reload --port $backend_port"
    echo ""
    echo "2. 启动前端服务（新终端）:"
    echo "   cd $FRONTEND_DIR"
    echo "   bun install  # 或 npm install / pnpm install"
    echo "   bun run dev   # 或 npm run dev / pnpm dev"
    echo ""
    echo "访问地址:"
    echo "  前端: http://localhost:$frontend_port"
    echo "  后端 API: http://localhost:$backend_port"
    echo "  API 文档: http://localhost:$backend_port/docs"
    echo ""
    echo "常用命令:"
    echo "  查看中间件日志: docker-compose -f docker-compose-middleware.yml logs -f"
    echo "  停止中间件: docker-compose -f docker-compose-middleware.yml down"
    echo "  进入数据库: docker-compose -f docker-compose-middleware.yml exec db psql -U postgres"
    echo ""
}

# 主函数
main() {
    echo "=========================================="
    echo "  本地开发环境启动"
    echo "=========================================="
    echo ""

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
