#!/bin/bash
# 统一安装脚本
# 支持交互式安装向导和命令行参数快速安装

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
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# 安装模式
MODE=""
NON_INTERACTIVE=false
SKIP_CHECKS=false

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
  -h, --help              显示帮助信息
  -m, --mode MODE         安装模式: dev, prod, test, minimal (默认: 交互式选择)
  --non-interactive       非交互式模式（使用默认配置）
  --skip-checks           跳过环境检查

安装模式说明:
  dev      - 开发环境（代码挂载、热重载）
  prod     - 生产环境（使用预构建镜像）
  test     - 测试环境（快速测试配置）
  minimal  - 最小化环境（仅中间件：数据库+Redis）

示例:
  # 交互式安装
  $0

  # 快速安装开发环境
  $0 --mode dev --non-interactive

  # 快速安装生产环境
  $0 --mode prod --non-interactive

  # 跳过环境检查
  $0 --mode dev --skip-checks
EOF
}

# 环境检查
run_environment_check() {
    if [ "$SKIP_CHECKS" = true ]; then
        log_info "跳过环境检查"
        return 0
    fi
    
    log_step "运行环境检查..."
    if "$SCRIPT_DIR/scripts/check-env.sh"; then
        log_success "环境检查通过"
        return 0
    else
        log_error "环境检查失败"
        if [ "$NON_INTERACTIVE" = false ]; then
            read -p "是否继续安装？(y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        else
            log_warning "非交互式模式，继续安装..."
        fi
        return 1
    fi
}

# 创建配置文件
create_config_file() {
    local source_file=$1
    local target_file=$2
    local description=$3
    
    if [ -f "$target_file" ]; then
        log_info "$description 已存在，跳过创建"
        return 0
    fi
    
    if [ ! -f "$source_file" ]; then
        log_error "$source_file 不存在，无法创建 $description"
        return 1
    fi
    
    log_step "创建 $description..."
    cp "$source_file" "$target_file"
    log_success "$description 已创建: $target_file"
    
    if [ "$NON_INTERACTIVE" = false ]; then
        log_info "请根据需要修改配置文件: $target_file"
        read -p "按 Enter 继续..."
    fi
    
    return 0
}

# 创建所有配置文件
create_config_files() {
    log_step "创建配置文件..."
    
    # 创建 deploy/.env
    create_config_file \
        "$SCRIPT_DIR/.env.example" \
        "$SCRIPT_DIR/.env" \
        "Docker Compose 端口映射配置"
    
    # 创建 backend/.env
    create_config_file \
        "$BACKEND_DIR/env.example" \
        "$BACKEND_DIR/.env" \
        "后端应用配置"
    
    # 创建 frontend/.env (可选)
    if [ -f "$FRONTEND_DIR/env.example" ]; then
        create_config_file \
            "$FRONTEND_DIR/env.example" \
            "$FRONTEND_DIR/.env.local" \
            "前端配置（可选）"
    fi
    
    log_success "配置文件创建完成"
}

# 交互式选择安装模式
select_mode() {
    if [ -n "$MODE" ]; then
        return 0
    fi
    
    if [ "$NON_INTERACTIVE" = true ]; then
        MODE="dev"
        log_info "非交互式模式，使用默认模式: $MODE"
        return 0
    fi
    
    echo ""
    echo "请选择安装模式:"
    echo "  1) dev      - 开发环境（代码挂载、热重载）"
    echo "  2) prod     - 生产环境（使用预构建镜像）"
    echo "  3) test     - 测试环境（快速测试配置）"
    echo "  4) minimal  - 最小化环境（仅中间件：数据库+Redis）"
    echo ""
    
    while true; do
        read -p "请输入选项 (1-4): " choice
        case $choice in
            1)
                MODE="dev"
                break
                ;;
            2)
                MODE="prod"
                break
                ;;
            3)
                MODE="test"
                break
                ;;
            4)
                MODE="minimal"
                break
                ;;
            *)
                log_error "无效选项，请输入 1-4"
                ;;
        esac
    done
}

# 验证模式
validate_mode() {
    case $MODE in
        dev|prod|test|minimal)
            return 0
            ;;
        *)
            log_error "无效的安装模式: $MODE"
            echo "支持的模式: dev, prod, test, minimal"
            exit 1
            ;;
    esac
}

# 显示安装摘要
show_summary() {
    echo ""
    echo "=========================================="
    echo "  安装摘要"
    echo "=========================================="
    echo "安装模式: $MODE"
    echo "项目根目录: $PROJECT_ROOT"
    echo "部署目录: $SCRIPT_DIR"
    echo ""
    echo "配置文件:"
    [ -f "$SCRIPT_DIR/.env" ] && echo "  ✅ deploy/.env"
    [ -f "$BACKEND_DIR/.env" ] && echo "  ✅ backend/.env"
    [ -f "$FRONTEND_DIR/.env.local" ] && echo "  ✅ frontend/.env.local"
    echo ""
    echo "下一步操作:"
    case $MODE in
        dev)
            echo "  ./scripts/dev.sh        # 启动开发环境"
            echo "  或"
            echo "  docker-compose up -d   # 启动完整服务"
            ;;
        prod)
            echo "  ./scripts/prod.sh      # 启动生产环境"
            echo "  或"
            echo "  docker-compose -f docker-compose.prod.yml up -d"
            ;;
        test)
            echo "  ./scripts/test.sh      # 启动测试环境"
            ;;
        minimal)
            echo "  ./scripts/minimal.sh   # 启动最小化环境"
            echo "  或"
            echo "  ./scripts/start-middleware.sh  # 启动中间件"
            ;;
    esac
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
            -m|--mode)
                MODE="$2"
                shift 2
                ;;
            --non-interactive)
                NON_INTERACTIVE=true
                shift
                ;;
            --skip-checks)
                SKIP_CHECKS=true
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
    echo "  JoySafeter - 安装向导"
    echo "=========================================="
    echo ""
    
    # 选择模式
    select_mode
    validate_mode
    
    log_info "安装模式: $MODE"
    echo ""
    
    # 环境检查
    run_environment_check
    echo ""
    
    # 创建配置文件
    create_config_files
    echo ""
    
    # 显示摘要
    show_summary
    
    log_success "安装完成！"
    echo ""
    log_info "提示: 请根据实际需求修改配置文件，然后使用相应的启动脚本启动服务"
}

# 运行主函数
main "$@"

