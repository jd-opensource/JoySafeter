#!/bin/bash
#
# 脚本公共函数库（供 deploy/scripts 下的脚本 source）
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 路径
COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$COMMON_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"

# Docker Compose 命令（v2: docker compose / v1: docker-compose）
DOCKER_COMPOSE_CMD=""

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

check_command() {
  command -v "$1" >/dev/null 2>&1
}

check_docker_running() {
  if ! check_command docker; then
    log_error "Docker 未安装"
    echo "  安装方法: https://docs.docker.com/get-docker/"
    return 1
  fi

  if ! docker info >/dev/null 2>&1; then
    log_error "Docker 未运行，请启动 Docker"
    return 1
  fi

  return 0
}

detect_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
    return 0
  fi

  if check_command docker-compose; then
    DOCKER_COMPOSE_CMD="docker-compose"
    return 0
  fi

  log_error "Docker Compose 未安装（需要 docker compose 或 docker-compose）"
  echo "  安装方法: https://docs.docker.com/compose/install/"
  return 1
}

load_deploy_env() {
  # 将 deploy/.env 中的变量导出到当前进程，供后续脚本与 docker compose 使用
  if [ -f "$DEPLOY_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$DEPLOY_DIR/.env" 2>/dev/null || true
    set +a
  fi
}

init_env_files() {
  log_step "初始化 .env 文件..."

  local missing=0

  # deploy/.env
  if [ ! -f "$DEPLOY_DIR/.env" ]; then
    log_warning "deploy/.env 不存在，将从示例文件创建"
    if [ -f "$DEPLOY_DIR/.env.example" ]; then
      cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
      log_success "已创建 deploy/.env"
    else
      log_warning "deploy/.env.example 不存在，跳过"
      missing=$((missing + 1))
    fi
  else
    log_info "deploy/.env 已存在"
  fi

  # backend/.env
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

  # frontend/.env（可选，但 docker-compose.yml 会引用该文件）
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

  if [ "$missing" -gt 0 ]; then
    log_warning "部分配置文件缺失，但将继续执行"
  else
    log_success ".env 文件初始化完成"
  fi

  # 初始化完成后加载 deploy/.env 到当前进程
  load_deploy_env
}

check_tavily_api_key() {
  log_step "检查 TAVILY_API_KEY..."
  local backend_env="$PROJECT_ROOT/backend/.env"

  if [ ! -f "$backend_env" ]; then
    log_warning "backend/.env 不存在，跳过检查"
    return 0
  fi

  if grep -q "^TAVILY_API_KEY=[^[:space:]]" "$backend_env"; then
    log_success "TAVILY_API_KEY 已在 backend/.env 中配置"
    return 0
  fi

  local tavily_key=""
  if [ -n "${TAVILY_API_KEY:-}" ]; then
    log_info "检测到系统环境变量 TAVILY_API_KEY，准备写入 backend/.env"
    tavily_key="$TAVILY_API_KEY"
  else
    log_warning "未在 backend/.env 中发现有效的 TAVILY_API_KEY"
    printf "请输入 TAVILY_API_KEY (回车跳过): "
    read -r tavily_key
  fi

  if [ -n "$tavily_key" ]; then
    grep -v "^TAVILY_API_KEY=" "$backend_env" > "${backend_env}.tmp" || true
    mv "${backend_env}.tmp" "$backend_env"
    echo "TAVILY_API_KEY=$tavily_key" >> "$backend_env"
    log_success "TAVILY_API_KEY 已写入 backend/.env"
  else
    log_info "跳过 TAVILY_API_KEY 设置"
  fi
}

wait_for_db_service() {
  local compose_file="$1"   # e.g. docker-compose.yml
  local service_name="${2:-db}"
  local max_attempts="${3:-30}"

  local attempt=0
  while [ "$attempt" -lt "$max_attempts" ]; do
    if $DOCKER_COMPOSE_CMD -f "$compose_file" exec -T "$service_name" pg_isready -U postgres >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 2
  done

  return 1
}
