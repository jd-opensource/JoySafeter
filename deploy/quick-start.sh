#!/bin/bash
# 快速启动脚本
# 一键启动完整服务（开发模式）

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Docker Compose 命令变量（将在检测后设置）
DOCKER_COMPOSE_CMD=""

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

log_step() {
    echo -e "${CYAN}▶ $1${NC}"
}

# 显示使用说明
show_usage() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -h, --help          显示帮助信息
  --skip-env          跳过 .env 文件初始化
  --skip-db-init      跳过数据库初始化

说明:
  此脚本会：
  1. 检测 Docker 和 Docker Compose 环境
  2. 初始化 .env 文件（如果不存在）
  3. 初始化数据库
  4. 启动 Docker Compose 服务

示例:
  # 完整流程（推荐）
  $0

  # 跳过 .env 文件初始化
  $0 --skip-env

  # 跳过数据库初始化
  $0 --skip-db-init
EOF
}

# 检测 Docker 和 Docker Compose 环境
check_docker_environment() {
    log_step "检测 Docker 和 Docker Compose 环境..."
    
    # 检测 Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装"
        echo "  安装方法: https://docs.docker.com/get-docker/"
        return 1
    fi
    
    local docker_version=$(docker --version 2>/dev/null | cut -d' ' -f3 | cut -d',' -f1)
    log_success "Docker 已安装 (版本: $docker_version)"
    
    # 检测 Docker Compose (优先检测 v2)
    if docker compose version &> /dev/null; then
        local compose_version=$(docker compose version 2>/dev/null | cut -d' ' -f4)
        log_success "Docker Compose 已安装 (版本: $compose_version)"
        DOCKER_COMPOSE_CMD="docker compose"
        return 0
    elif command -v docker-compose &> /dev/null; then
        local compose_version=$(docker-compose --version 2>/dev/null | cut -d' ' -f4 | cut -d',' -f1)
        log_success "Docker Compose 已安装 (版本: $compose_version)"
        DOCKER_COMPOSE_CMD="docker-compose"
        return 0
    else
        log_error "Docker Compose 未安装"
        echo "  安装方法: https://docs.docker.com/compose/install/"
        return 1
    fi
}

# 初始化 .env 文件
init_env_files() {
    log_step "初始化 .env 文件..."
    
    local missing=0
    
    # 检查并初始化 deploy/.env
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        log_warning "deploy/.env 不存在，将从示例文件创建"
        if [ -f "$SCRIPT_DIR/.env.example" ]; then
            cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
            log_success "已创建 deploy/.env"
        else
            log_warning "deploy/.env.example 不存在，跳过"
            missing=$((missing + 1))
        fi
    else
        log_info "deploy/.env 已存在"
    fi
    
    # 检查并初始化 backend/.env
    if [ ! -f "$PROJECT_ROOT/backend/.env" ]; then
        log_warning "backend/.env 不存在，将从示例文件创建"
        if [ -f "$PROJECT_ROOT/backend/env.example" ]; then
            cp "$PROJECT_ROOT/backend/env.example" "$PROJECT_ROOT/backend/.env"
            log_success "已创建 backend/.env"
        else
            log_warning "backend/env.example 不存在，跳过"
            missing=$((missing + 1))
        fi
    else
        log_info "backend/.env 已存在"
    fi
    
    # 检查并初始化 frontend/.env（如果示例文件存在）
    if [ ! -f "$PROJECT_ROOT/frontend/.env" ]; then
        if [ -f "$PROJECT_ROOT/frontend/env.example" ]; then
            log_warning "frontend/.env 不存在，将从示例文件创建"
            cp "$PROJECT_ROOT/frontend/env.example" "$PROJECT_ROOT/frontend/.env"
            log_success "已创建 frontend/.env"
        else
            log_info "frontend/env.example 不存在，跳过 frontend/.env 初始化"
        fi
    else
        log_info "frontend/.env 已存在"
    fi
    
    if [ $missing -gt 0 ]; then
        log_warning "部分配置文件缺失，但将继续执行"
    else
        log_success ".env 文件初始化完成"
    fi
}

# 初始化数据库
init_database() {
    log_step "初始化数据库..."
    
    cd "$SCRIPT_DIR"
    
    # 先启动数据库服务
    log_info "启动数据库服务..."
    if ! $DOCKER_COMPOSE_CMD up -d db; then
        log_error "启动数据库服务失败"
        return 1
    fi
    
    # 等待数据库健康检查通过
    log_info "等待数据库就绪..."
    local max_attempts=30
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        # 检查数据库容器状态（健康检查可能显示为 "healthy" 或包含 "healthy"）
        local db_status=$($DOCKER_COMPOSE_CMD ps db 2>/dev/null | grep -E "(healthy|Health)" || echo "")
        if echo "$db_status" | grep -qi "healthy"; then
            log_success "数据库已就绪"
            break
        fi
        # 也可以尝试直接检查数据库是否可连接
        if $DOCKER_COMPOSE_CMD exec -T db pg_isready -U postgres &>/dev/null; then
            log_success "数据库已就绪"
            break
        fi
        attempt=$((attempt + 1))
        if [ $((attempt % 5)) -eq 0 ]; then
            log_info "仍在等待数据库就绪... ($attempt/$max_attempts)"
        fi
        sleep 2
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_error "数据库健康检查超时"
        log_info "数据库容器状态:"
        $DOCKER_COMPOSE_CMD ps db
        return 1
    fi
    
    # 运行数据库初始化
    log_info "运行数据库初始化..."
    if $DOCKER_COMPOSE_CMD --profile init run --rm db-init; then
        log_success "数据库初始化完成"
        return 0
    else
        log_error "数据库初始化失败"
        return 1
    fi
}

# 启动 Docker Compose 服务
start_docker_compose() {
    log_step "启动 Docker Compose 服务..."
    
    cd "$SCRIPT_DIR"
    
    # 检查是否已有服务在运行
    if $DOCKER_COMPOSE_CMD ps 2>/dev/null | grep -q "Up"; then
        log_warning "检测到已有服务在运行"
        read -p "是否重启服务？(y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "停止现有服务..."
            $DOCKER_COMPOSE_CMD down
        else
            log_info "使用现有服务"
            return 0
        fi
    fi
    
    log_info "启动 Docker Compose 服务..."
    if ! $DOCKER_COMPOSE_CMD up -d; then
        log_error "启动服务失败"
        return 1
    fi
    
    # 等待服务就绪
    log_info "等待服务就绪..."
    sleep 5
    
    # 检查服务状态
    log_info "检查服务状态..."
    $DOCKER_COMPOSE_CMD ps
    
    log_success "服务启动完成"
}

# 显示服务信息
show_service_info() {
    echo ""
    echo "=========================================="
    echo "  服务信息"
    echo "=========================================="
    
    # 读取端口配置
    local backend_port=8000
    local frontend_port=3000
    
    if [ -f "$SCRIPT_DIR/.env" ]; then
        source "$SCRIPT_DIR/.env" 2>/dev/null || true
        backend_port=${BACKEND_PORT_HOST:-8000}
        frontend_port=${FRONTEND_PORT_HOST:-3000}
    fi
    
    echo ""
    echo "访问地址:"
    echo "  前端: http://localhost:$frontend_port"
    echo "  后端 API: http://localhost:$backend_port"
    echo "  API 文档: http://localhost:$backend_port/docs"
    echo "  ReDoc: http://localhost:$backend_port/redoc"
    echo ""
    echo "常用命令:"
    if [ -n "$DOCKER_COMPOSE_CMD" ]; then
        echo "  查看日志: $DOCKER_COMPOSE_CMD logs -f"
        echo "  停止服务: $DOCKER_COMPOSE_CMD down"
        echo "  重启服务: $DOCKER_COMPOSE_CMD restart"
    else
        echo "  查看日志: docker compose logs -f"
        echo "  停止服务: docker compose down"
        echo "  重启服务: docker compose restart"
    fi
    echo ""
}

# 主函数
main() {
    local SKIP_ENV=false
    local SKIP_DB_INIT=false
    
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
            *)
                log_error "未知选项: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    echo "=========================================="
    echo "  JoySafeter - 快速启动"
    echo "=========================================="
    echo ""
    
    # 1. 检测 Docker 和 Docker Compose 环境
    if ! check_docker_environment; then
        log_error "环境检测失败，请先安装 Docker 和 Docker Compose"
        exit 1
    fi
    echo ""
    
    # 2. 初始化 .env 文件
    if [ "$SKIP_ENV" = false ]; then
        init_env_files
        echo ""
    else
        log_info "跳过 .env 文件初始化"
        echo ""
    fi
    
    # 3. 初始化数据库
    if [ "$SKIP_DB_INIT" = false ]; then
        if ! init_database; then
            log_error "数据库初始化失败"
            exit 1
        fi
        echo ""
    else
        log_info "跳过数据库初始化"
        echo ""
    fi
    
    # 4. 启动 Docker Compose 服务
    if ! start_docker_compose; then
        log_error "服务启动失败"
        exit 1
    fi
    echo ""
    
    # 显示服务信息
    show_service_info
    
    log_success "快速启动完成！"
    echo ""
    if [ -n "$DOCKER_COMPOSE_CMD" ]; then
        log_info "提示: 如果服务启动失败，请查看日志: $DOCKER_COMPOSE_CMD logs"
    else
        log_info "提示: 如果服务启动失败，请查看日志: docker compose logs"
    fi
}

# 运行主函数
main "$@"

