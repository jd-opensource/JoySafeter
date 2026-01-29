#!/bin/bash
# 环境检查工具
# 检查 Docker、端口、配置文件等前置条件

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

# 检查结果
ERRORS=0
WARNINGS=0

# 日志函数
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
    WARNINGS=$((WARNINGS + 1))
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
    ERRORS=$((ERRORS + 1))
}

# 检查命令是否存在
check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# 检查端口是否被占用
check_port() {
    local port=$1
    local service=$2

    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 || \
       netstat -an 2>/dev/null | grep -q ":$port.*LISTEN" || \
       (command -v ss >/dev/null && ss -tuln | grep -q ":$port "); then
        log_warning "$service 端口 $port 已被占用"
        return 1
    else
        log_success "$service 端口 $port 可用"
        return 0
    fi
}

# 检查 Docker
check_docker() {
    log_info "检查 Docker..."

    if ! check_command docker; then
        log_error "Docker 未安装"
        echo "  安装方法: https://docs.docker.com/get-docker/"
        return 1
    fi

    local docker_version=$(docker --version 2>/dev/null | cut -d' ' -f3 | cut -d',' -f1)
    log_success "Docker 已安装 (版本: $docker_version)"

    # 检查 Docker 是否运行
    if ! docker info &> /dev/null; then
        log_error "Docker 未运行，请启动 Docker"
        return 1
    fi

    log_success "Docker 正在运行"
    return 0
}

# 检查 Docker Compose
check_docker_compose() {
    log_info "检查 Docker Compose..."

    # 检查 docker compose (v2) 或 docker-compose (v1)
    if docker compose version &> /dev/null; then
        local compose_version=$(docker compose version 2>/dev/null | cut -d' ' -f4)
        log_success "Docker Compose 已安装 (版本: $compose_version)"
        return 0
    elif check_command docker-compose; then
        local compose_version=$(docker-compose --version 2>/dev/null | cut -d' ' -f4 | cut -d',' -f1)
        log_success "Docker Compose 已安装 (版本: $compose_version)"
        return 0
    else
        log_error "Docker Compose 未安装"
        echo "  安装方法: https://docs.docker.com/compose/install/"
        return 1
    fi
}

# 检查端口占用
check_ports() {
    log_info "检查端口占用情况..."

    # 读取 .env 文件获取端口配置（如果存在）
    local env_file="$DEPLOY_DIR/.env"
    local backend_port=8000
    local frontend_port=3000
    local postgres_port=5432
    local redis_port=6379

    if [ -f "$env_file" ]; then
        # 从 .env 文件读取端口配置
        source "$env_file" 2>/dev/null || true
        backend_port=${BACKEND_PORT_HOST:-8000}
        frontend_port=${FRONTEND_PORT_HOST:-3000}
        postgres_port=${POSTGRES_PORT_HOST:-5432}
        redis_port=${REDIS_PORT_HOST:-6379}
    fi

    check_port "$backend_port" "后端服务"
    check_port "$frontend_port" "前端服务"
    check_port "$postgres_port" "PostgreSQL"
    check_port "$redis_port" "Redis"
}

# 检查配置文件
check_config_files() {
    log_info "检查配置文件..."

    # 检查 deploy/.env
    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        log_warning "deploy/.env 文件不存在"
        if [ -f "$DEPLOY_DIR/.env.example" ]; then
            echo "  提示: 运行 'cp $DEPLOY_DIR/.env.example $DEPLOY_DIR/.env' 创建配置文件"
        fi
    else
        log_success "deploy/.env 文件存在"
    fi

    # 检查 backend/.env
    if [ ! -f "$PROJECT_ROOT/backend/.env" ]; then
        log_warning "backend/.env 文件不存在"
        if [ -f "$PROJECT_ROOT/backend/env.example" ]; then
            echo "  提示: 运行 'cp $PROJECT_ROOT/backend/env.example $PROJECT_ROOT/backend/.env' 创建配置文件"
        fi
    else
        log_success "backend/.env 文件存在"
    fi

    # 检查 frontend/.env (可选)
    if [ ! -f "$PROJECT_ROOT/frontend/.env" ] && [ ! -f "$PROJECT_ROOT/frontend/.env.local" ]; then
        log_info "frontend/.env 文件不存在（可选配置）"
    else
        log_success "frontend/.env 文件存在"
    fi
}

# 检查示例文件
check_example_files() {
    log_info "检查示例配置文件..."

    local missing=0

    if [ ! -f "$DEPLOY_DIR/.env.example" ]; then
        log_warning "deploy/.env.example 文件不存在"
        missing=$((missing + 1))
    else
        log_success "deploy/.env.example 文件存在"
    fi

    if [ ! -f "$PROJECT_ROOT/backend/env.example" ]; then
        log_warning "backend/env.example 文件不存在"
        missing=$((missing + 1))
    else
        log_success "backend/env.example 文件存在"
    fi

    return $missing
}

# 检查 Docker Compose 文件
check_docker_compose_files() {
    log_info "检查 Docker Compose 配置文件..."

    local missing=0

    if [ ! -f "$DEPLOY_DIR/docker-compose.yml" ]; then
        log_error "docker-compose.yml 文件不存在"
        missing=$((missing + 1))
    else
        log_success "docker-compose.yml 文件存在"
    fi

    if [ ! -f "$DEPLOY_DIR/docker-compose-middleware.yml" ]; then
        log_warning "docker-compose-middleware.yml 文件不存在（可选）"
    else
        log_success "docker-compose-middleware.yml 文件存在"
    fi

    if [ ! -f "$DEPLOY_DIR/docker-compose.prod.yml" ]; then
        log_warning "docker-compose.prod.yml 文件不存在（可选）"
    else
        log_success "docker-compose.prod.yml 文件存在"
    fi

    return $missing
}

# 检查磁盘空间（可选）
check_disk_space() {
    log_info "检查磁盘空间..."

    # 检查可用空间（至少需要 5GB）
    local min_space_gb=5
    local available_space_gb=0

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        available_space_gb=$(df -g "$DEPLOY_DIR" | tail -1 | awk '{print $4}')
    else
        # Linux
        available_space_gb=$(df -BG "$DEPLOY_DIR" | tail -1 | awk '{print $4}' | sed 's/G//')
    fi

    if [ "$available_space_gb" -lt "$min_space_gb" ]; then
        log_warning "可用磁盘空间不足 (${available_space_gb}GB < ${min_space_gb}GB)"
        echo "  建议: 清理磁盘空间或使用更大的磁盘"
    else
        log_success "磁盘空间充足 (${available_space_gb}GB 可用)"
    fi
}

# 主函数
main() {
    echo "=========================================="
    echo "  环境检查工具"
    echo "=========================================="
    echo ""
    log_info "项目根目录: $PROJECT_ROOT"
    log_info "部署目录: $DEPLOY_DIR"
    echo ""

    # 执行检查
    check_docker
    echo ""

    check_docker_compose
    echo ""

    check_ports
    echo ""

    check_config_files
    echo ""

    check_example_files
    echo ""

    check_docker_compose_files
    echo ""

    check_disk_space
    echo ""

    # 总结
    echo "=========================================="
    echo "  检查结果"
    echo "=========================================="

    if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
        log_success "所有检查通过！"
        echo ""
        echo "可以开始部署服务了："
        echo "  cd $DEPLOY_DIR"
        echo "  ./scripts/start-middleware.sh  # 启动中间件"
        echo "  docker-compose up -d            # 启动完整服务"
        exit 0
    elif [ $ERRORS -eq 0 ]; then
        log_warning "检查完成，有 $WARNINGS 个警告"
        echo ""
        echo "可以继续部署，但建议先处理警告项"
        exit 0
    else
        log_error "检查失败，有 $ERRORS 个错误和 $WARNINGS 个警告"
        echo ""
        echo "请先解决错误项后再继续部署"
        exit 1
    fi
}

# 运行主函数
main "$@"
