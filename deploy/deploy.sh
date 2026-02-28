#!/bin/bash
# JoySafeter - 镜像构建和推送脚本
# 支持：构建多架构镜像、推送镜像、拉取镜像
#
# 所有 Dockerfile 统一位于 deploy/docker/ 目录

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 项目根目录
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 切换到项目根目录
cd "$PROJECT_ROOT"

# 默认配置
REGISTRY="${DOCKER_REGISTRY:-docker.io/jdopensource}"
BACKEND_IMAGE="${BACKEND_IMAGE:-joysafeter-backend}"
FRONTEND_IMAGE="${FRONTEND_IMAGE:-joysafeter-frontend}"
MCP_IMAGE="${MCP_IMAGE:-joysafeter-mcp}"
INIT_IMAGE="${INIT_IMAGE:-joysafeter-init}"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-joysafeter-openclaw}"
TAG="${IMAGE_TAG:-latest}"
# 默认多平台构建：amd64 + arm64
PLATFORMS="${BUILD_PLATFORMS:-linux/amd64,linux/arm64}"
USE_BUILDX="${USE_BUILDX:-true}"
BASE_IMAGE_REGISTRY="${BASE_IMAGE_REGISTRY:-}"
FRONTEND_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
# 是否禁用 Docker 构建缓存（默认使用缓存）
NO_CACHE="${NO_CACHE:-false}"
# pip/uv 镜像源配置（默认使用清华大学镜像源）
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple}"
UV_INDEX_URL="${UV_INDEX_URL:-https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple}"

# 规范化镜像仓库地址
normalize_registry() {
    local registry="$1"
    if [ -z "$registry" ]; then
        echo ""
        return
    fi
    registry="${registry#https://}"
    registry="${registry#http://}"
    echo "$registry"
}

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

# 显示使用说明
show_usage() {
    cat << EOF
使用方法: $0 [命令] [选项]

命令:
  build              构建多架构镜像（默认构建前后端，支持 linux/amd64,linux/arm64）
  push               构建并推送多架构镜像到仓库
  pull               拉取镜像（从仓库拉取最新镜像）

选项:
  -h, --help             显示帮助信息
  -r, --registry REGISTRY 镜像仓库地址（默认: docker.io/jdopensource）
  -t, --tag TAG          镜像标签（默认: latest）
  --platform PLATFORMS   目标平台架构，多个用逗号分隔（默认: linux/amd64,linux/arm64）
  --arch ARCH            简化的架构选项，可多次使用
                         支持: amd64, arm64, armv7
  --api-url URL          前端连接后端的API地址（构建时注入）
  --backend-only         只构建后端镜像
  --frontend-only        只构建前端镜像
  --init-only            只构建初始化镜像
  --openclaw-only        只构建 OpenClaw 镜像
  --all                  构建所有镜像（包括 backend, frontend, init, openclaw）
  --no-cache             禁用 Docker 构建缓存（默认使用缓存）
  --mirror MIRROR        使用国内镜像源加速基础镜像（aliyun, tencent, huawei, docker-cn）
  --pip-mirror MIRROR    使用国内 pip 镜像源（aliyun, tencent, huawei, jd）

环境变量:
  DOCKER_REGISTRY        镜像仓库地址（默认: docker.io/jdopensource）
  BACKEND_IMAGE          后端镜像名称（默认: joysafeter-backend）
  FRONTEND_IMAGE         前端镜像名称（默认: joysafeter-frontend）
  MCP_IMAGE              MCP 服务镜像名称（默认: joysafeter-mcp）
  INIT_IMAGE             初始化镜像名称（默认: joysafeter-init）
  OPENCLAW_IMAGE         OpenClaw 镜像名称（默认: joysafeter-openclaw）
  IMAGE_TAG              镜像标签（默认: latest）
  BUILD_PLATFORMS        目标平台架构（默认: linux/amd64,linux/arm64）
  NEXT_PUBLIC_API_URL    前端API地址（默认: http://localhost:8000）
  PIP_INDEX_URL          pip 镜像源（默认: https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple）
  UV_INDEX_URL           uv 镜像源（默认: https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple）
  BASE_IMAGE_REGISTRY    基础镜像仓库前缀
  NO_CACHE               是否禁用构建缓存（默认: false，使用缓存）

示例:
  # 构建前后端多架构镜像
  $0 build

  # 只构建后端多架构镜像
  $0 build --backend-only

  # 只构建前端多架构镜像
  $0 build --frontend-only

  # 构建所有镜像（包括 init）
  $0 build --all

  # 注意：MCP 服务镜像使用预构建镜像 docker.io/jdopensource/joysafeter-mcp:latest
  # 使用 pull 命令拉取 MCP 镜像

  # 构建并推送到仓库
  $0 push

  # 构建指定架构并推送
  $0 push --arch amd64 --arch arm64

  # 构建时指定前端API地址
  $0 build --api-url http://api.example.com

  # 使用国内镜像源加速构建
  $0 build --mirror huawei --pip-mirror aliyun

  # 禁用缓存构建镜像
  $0 build --no-cache

  # 拉取最新镜像
  $0 pull

  # 拉取指定标签的镜像
  $0 pull --tag v1.0.0
EOF
}

# 检查命令是否存在
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 未安装，请先安装 $1"
        return 1
    fi
    return 0
}

# 检查 Docker 是否运行
check_docker_running() {
    if ! docker info &> /dev/null; then
        log_error "Docker 未运行，请先启动 Docker"
        exit 1
    fi
}

# 初始化 Docker Buildx
init_buildx() {
    if [ "$USE_BUILDX" = true ]; then
        log_info "检查 Docker Buildx..."

        if ! docker buildx version &> /dev/null; then
            log_warning "Docker Buildx 不可用，回退到传统构建方式"
            USE_BUILDX=false
            return
        fi

        if ! docker buildx ls | grep -q "multiarch"; then
            log_info "创建 multiarch builder..."
            docker buildx create --name multiarch --driver docker-container --use 2>/dev/null || \
            docker buildx use multiarch 2>/dev/null || true
        else
            log_info "使用现有的 multiarch builder"
            docker buildx use multiarch 2>/dev/null || true
        fi

        docker buildx inspect --bootstrap &> /dev/null || true
    fi
}

# 转换简化架构名称为完整平台名称
convert_arch_to_platform() {
    local arch=$1
    case "$arch" in
        amd64)
            echo "linux/amd64"
            ;;
        arm64)
            echo "linux/arm64"
            ;;
        armv7)
            echo "linux/arm/v7"
            ;;
        *)
            echo "$arch"
            ;;
    esac
}

# 构建镜像
build_image() {
    local service=$1
    local dockerfile=$2
    local context=$3
    local image_name=$4

    log_info "构建 $service 镜像: $image_name"
    log_info "目标平台: $PLATFORMS"
    log_info "Dockerfile: $dockerfile"
    log_info "Context: $context"

    # 构建参数
    local build_args=()
    if [ -n "$BASE_IMAGE_REGISTRY" ]; then
        build_args+=("--build-arg" "BASE_IMAGE_REGISTRY=$BASE_IMAGE_REGISTRY")
        log_info "使用基础镜像源: $BASE_IMAGE_REGISTRY"
    fi

    # 添加 pip/uv 镜像源参数
    if [ -n "$PIP_INDEX_URL" ]; then
        build_args+=("--build-arg" "PIP_INDEX_URL=$PIP_INDEX_URL")
    fi
    if [ -n "$UV_INDEX_URL" ]; then
        build_args+=("--build-arg" "UV_INDEX_URL=$UV_INDEX_URL")
    fi

    # 前端镜像需要传递 NEXT_PUBLIC_API_URL
    if [ "$service" = "前端" ]; then
        if [ -n "$FRONTEND_API_URL" ]; then
            build_args+=("--build-arg" "NEXT_PUBLIC_API_URL=$FRONTEND_API_URL")
            log_info "前端API地址: $FRONTEND_API_URL"
        fi
    fi

    if [ "$USE_BUILDX" = true ] && [ "$PUSH" = true ]; then
        if [ "$NO_CACHE" = true ]; then
            log_info "使用 Docker Buildx 构建多架构镜像并推送（无缓存）..."
        else
            log_info "使用 Docker Buildx 构建多架构镜像并推送（使用缓存）..."
        fi
        local buildx_args=("${build_args[@]}")
        if [ "$NO_CACHE" = true ]; then
            buildx_args+=("--no-cache")
        fi
        docker buildx build \
            --platform "$PLATFORMS" \
            --file "$dockerfile" \
            --tag "$image_name" \
            "${buildx_args[@]}" \
            --push \
            "$context"
    elif [ "$USE_BUILDX" = true ]; then
        if [ "$NO_CACHE" = true ]; then
            log_info "使用 Docker Buildx 构建多架构镜像（本地，无缓存）..."
        else
            log_info "使用 Docker Buildx 构建多架构镜像（本地，使用缓存）..."
        fi
        local buildx_args=("${build_args[@]}")
        if [ "$NO_CACHE" = true ]; then
            buildx_args+=("--no-cache")
        fi
        if echo "$PLATFORMS" | grep -q ","; then
            log_warning "多架构构建需要 --push 选项才能保存所有架构，当前只构建第一个架构"
            FIRST_PLATFORM=$(echo "$PLATFORMS" | cut -d',' -f1)
            docker buildx build \
                --platform "$FIRST_PLATFORM" \
                --file "$dockerfile" \
                --tag "$image_name" \
                "${buildx_args[@]}" \
                --load \
                "$context"
        else
            docker buildx build \
                --platform "$PLATFORMS" \
                --file "$dockerfile" \
                --tag "$image_name" \
                "${buildx_args[@]}" \
                --load \
                "$context"
        fi
    else
        if [ "$NO_CACHE" = true ]; then
            log_info "使用传统方式构建单架构镜像（无缓存）..."
        else
            log_info "使用传统方式构建单架构镜像（使用缓存）..."
        fi
        local build_args_final=("${build_args[@]}")
        if [ "$NO_CACHE" = true ]; then
            build_args_final+=("--no-cache")
        fi
        docker build \
            -f "$dockerfile" \
            "${build_args_final[@]}" \
            -t "$image_name" \
            "$context"
    fi

    log_success "$service 镜像构建完成: $image_name"
}

# 构建所有镜像
build_all_images() {
    local BUILD_BACKEND=${BUILD_BACKEND:-true}
    local BUILD_FRONTEND=${BUILD_FRONTEND:-true}
    local BUILD_INIT=${BUILD_INIT:-false}
    local BUILD_OPENCLAW=${BUILD_OPENCLAW:-true}

    # 检查是否只构建特定服务
    if [ "$BACKEND_ONLY" = true ]; then
        BUILD_FRONTEND=false
        BUILD_INIT=false
    elif [ "$FRONTEND_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_INIT=false
    elif [ "$INIT_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_INIT=true
        BUILD_OPENCLAW=false
    elif [ "$OPENCLAW_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_INIT=false
        BUILD_OPENCLAW=true
    elif [ "$BUILD_ALL" = true ]; then
        BUILD_BACKEND=true
        BUILD_FRONTEND=true
        BUILD_INIT=true
        BUILD_OPENCLAW=true
    fi

    # 规范化镜像仓库地址
    NORMALIZED_REGISTRY=$(normalize_registry "$REGISTRY")

    # 构建镜像名称
    if [ -n "$NORMALIZED_REGISTRY" ]; then
        BACKEND_FULL_IMAGE="${NORMALIZED_REGISTRY}/${BACKEND_IMAGE}:${TAG}"
        FRONTEND_FULL_IMAGE="${NORMALIZED_REGISTRY}/${FRONTEND_IMAGE}:${TAG}"
        MCP_FULL_IMAGE="${NORMALIZED_REGISTRY}/${MCP_IMAGE}:${TAG}"
        INIT_FULL_IMAGE="${NORMALIZED_REGISTRY}/${INIT_IMAGE}:${TAG}"
        OPENCLAW_FULL_IMAGE="${NORMALIZED_REGISTRY}/${OPENCLAW_IMAGE}:${TAG}"
    else
        BACKEND_FULL_IMAGE="${BACKEND_IMAGE}:${TAG}"
        FRONTEND_FULL_IMAGE="${FRONTEND_IMAGE}:${TAG}"
        MCP_FULL_IMAGE="${MCP_IMAGE}:${TAG}"
        INIT_FULL_IMAGE="${INIT_IMAGE}:${TAG}"
        OPENCLAW_FULL_IMAGE="${OPENCLAW_IMAGE}:${TAG}"
    fi

    # 初始化 Buildx（如果需要）
    if [ "$USE_BUILDX" = true ]; then
        init_buildx
        echo ""
    fi

    # 如果使用 Buildx 且需要推送，必须指定仓库
    if [ "$USE_BUILDX" = true ] && [ "$PUSH" = true ] && [ -z "$REGISTRY" ]; then
        log_error "使用 Buildx 构建多架构镜像并推送时，必须指定镜像仓库（--registry）"
        exit 1
    fi

    # 构建后端镜像
    if [ "$BUILD_BACKEND" = true ]; then
        build_image "后端" \
            "$SCRIPT_DIR/docker/backend.Dockerfile" \
            "$PROJECT_ROOT/backend" \
            "$BACKEND_FULL_IMAGE"
        echo ""
    fi

    # 构建前端镜像
    if [ "$BUILD_FRONTEND" = true ]; then
        build_image "前端" \
            "$SCRIPT_DIR/docker/frontend.Dockerfile" \
            "$PROJECT_ROOT/frontend" \
            "$FRONTEND_FULL_IMAGE"
        echo ""
    fi

    # 注意：MCP 服务镜像使用预构建镜像 docker.io/jdopensource/joysafeter-mcp:latest
    # 如需拉取 MCP 镜像，请使用 pull 命令

    # 构建初始化镜像
    if [ "$BUILD_INIT" = true ]; then
        build_image "初始化" \
            "$SCRIPT_DIR/docker/backend.Dockerfile" \
            "$PROJECT_ROOT/backend" \
            "$INIT_FULL_IMAGE"
        echo ""
    fi

    # 构建 OpenClaw 镜像
    if [ "$BUILD_OPENCLAW" = true ]; then
        build_image "OpenClaw" \
            "$PROJECT_ROOT/deploy/openclaw/Dockerfile" \
            "$PROJECT_ROOT/backend" \
            "$OPENCLAW_FULL_IMAGE"
        echo ""
    fi

    log_success "所有镜像构建完成！"
    echo ""
    echo "📦 镜像信息:"
    [ "$BUILD_BACKEND" = true ] && echo "   后端: $BACKEND_FULL_IMAGE"
    [ "$BUILD_FRONTEND" = true ] && echo "   前端: $FRONTEND_FULL_IMAGE"
    [ "$BUILD_INIT" = true ] && echo "   Init: $INIT_FULL_IMAGE"
    [ "$BUILD_OPENCLAW" = true ] && echo "   OpenClaw: $OPENCLAW_FULL_IMAGE"
    echo "   注意: MCP 服务镜像使用预构建镜像 docker.io/jdopensource/joysafeter-mcp:latest"
    echo ""
    echo "🏗️  构建平台: $PLATFORMS"
    echo ""

    if [ "$PUSH" = true ]; then
        log_success "镜像已推送到仓库"
    else
        log_info "镜像未推送，使用 push 命令推送到仓库"
        if [ "$USE_BUILDX" = true ] && echo "$PLATFORMS" | grep -q ","; then
            log_warning "注意：多架构构建需要 push 命令才能保存所有架构的镜像"
        fi
    fi
}

# 拉取镜像
pull_images() {
    local NORMALIZED_REGISTRY=$(normalize_registry "$REGISTRY")

    if [ -n "$NORMALIZED_REGISTRY" ]; then
        BACKEND_FULL_IMAGE="${NORMALIZED_REGISTRY}/${BACKEND_IMAGE}:${TAG}"
        FRONTEND_FULL_IMAGE="${NORMALIZED_REGISTRY}/${FRONTEND_IMAGE}:${TAG}"
        MCP_FULL_IMAGE="${NORMALIZED_REGISTRY}/${MCP_IMAGE}:${TAG}"
        OPENCLAW_FULL_IMAGE="${NORMALIZED_REGISTRY}/${OPENCLAW_IMAGE}:${TAG}"
    else
        BACKEND_FULL_IMAGE="${BACKEND_IMAGE}:${TAG}"
        FRONTEND_FULL_IMAGE="${FRONTEND_IMAGE}:${TAG}"
        MCP_FULL_IMAGE="${MCP_IMAGE}:${TAG}"
        OPENCLAW_FULL_IMAGE="${OPENCLAW_IMAGE}:${TAG}"
    fi

    log_info "拉取后端镜像: $BACKEND_FULL_IMAGE"
    if docker pull "$BACKEND_FULL_IMAGE"; then
        log_success "后端镜像拉取成功"
    else
        log_error "后端镜像拉取失败"
        exit 1
    fi

    log_info "拉取前端镜像: $FRONTEND_FULL_IMAGE"
    if docker pull "$FRONTEND_FULL_IMAGE"; then
        log_success "前端镜像拉取成功"
    else
        log_error "前端镜像拉取失败"
        exit 1
    fi

    log_info "拉取 MCP 服务镜像: $MCP_FULL_IMAGE"
    if docker pull "$MCP_FULL_IMAGE"; then
        log_success "MCP 服务镜像拉取成功"
    else
        log_error "MCP 服务镜像拉取失败"
        exit 1
    fi

    log_info "拉取 OpenClaw 镜像: $OPENCLAW_FULL_IMAGE"
    if docker pull "$OPENCLAW_FULL_IMAGE"; then
        log_success "OpenClaw 镜像拉取成功"
    else
        log_error "OpenClaw 镜像拉取失败"
        exit 1
    fi

    log_success "所有镜像拉取完成！"
    echo ""
    echo "📦 镜像信息:"
    echo "   后端: $BACKEND_FULL_IMAGE"
    echo "   前端: $FRONTEND_FULL_IMAGE"
    echo "   OpenClaw: $OPENCLAW_FULL_IMAGE"
}

# 主函数
main() {
    local COMMAND=""
    local PUSH=false
    local BACKEND_ONLY=false
    local FRONTEND_ONLY=false
    local INIT_ONLY=false
    local OPENCLAW_ONLY=false
    local BUILD_ALL=false
    local ARCH_LIST=()

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -r|--registry)
                REGISTRY="$2"
                shift 2
                ;;
            -t|--tag)
                TAG="$2"
                shift 2
                ;;
            --platform)
                PLATFORMS="$2"
                shift 2
                ;;
            --arch)
                ARCH_LIST+=("$2")
                shift 2
                ;;
            --api-url)
                FRONTEND_API_URL="$2"
                shift 2
                ;;
            --mirror)
                case "$2" in
                    aliyun)
                        BASE_IMAGE_REGISTRY="registry.cn-hangzhou.aliyuncs.com/library/"
                        ;;
                    tencent)
                        BASE_IMAGE_REGISTRY="ccr.ccs.tencentyun.com/library/"
                        ;;
                    huawei)
                        BASE_IMAGE_REGISTRY="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/"
                        ;;
                    docker-cn)
                        BASE_IMAGE_REGISTRY="docker.mirrors.ustc.edu.cn/library/"
                        ;;
                    *)
                        BASE_IMAGE_REGISTRY="$2"
                        ;;
                esac
                shift 2
                ;;
            --pip-mirror)
                case "$2" in
                    aliyun)
                        PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple"
                        UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple"
                        ;;
                    tencent)
                        PIP_INDEX_URL="https://mirrors.cloud.tencent.com/pypi/simple"
                        UV_INDEX_URL="https://mirrors.cloud.tencent.com/pypi/simple"
                        ;;
                    huawei)
                        PIP_INDEX_URL="https://mirrors.huaweicloud.com/repository/pypi/simple"
                        UV_INDEX_URL="https://mirrors.huaweicloud.com/repository/pypi/simple"
                        ;;
                    jd)
                        PIP_INDEX_URL="https://mirrors.jd.com/pypi/simple"
                        UV_INDEX_URL="https://mirrors.jd.com/pypi/simple"
                        ;;
                    *)
                        PIP_INDEX_URL="$2"
                        UV_INDEX_URL="$2"
                        ;;
                esac
                shift 2
                ;;
            --backend-only)
                BACKEND_ONLY=true
                shift
                ;;
            --frontend-only)
                FRONTEND_ONLY=true
                shift
                ;;
            --init-only)
                INIT_ONLY=true
                shift
                ;;
            --openclaw-only)
                OPENCLAW_ONLY=true
                shift
                ;;
            --all)
                BUILD_ALL=true
                shift
                ;;
            --no-cache)
                NO_CACHE=true
                shift
                ;;
            build|push|pull)
                COMMAND="$1"
                shift
                ;;
            *)
                log_error "未知选项: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    # 如果没有指定命令，显示帮助
    if [ -z "$COMMAND" ]; then
        show_usage
        exit 0
    fi

    echo "=========================================="
    echo "  JoySafeter - 镜像管理"
    echo "=========================================="
    echo ""
    log_info "项目根目录: $PROJECT_ROOT"
    log_info "Dockerfile 目录: $SCRIPT_DIR/docker/"
    log_info "镜像仓库: $REGISTRY"
    log_info "镜像标签: $TAG"
    if [ -n "$BASE_IMAGE_REGISTRY" ]; then
        log_info "基础镜像源: $BASE_IMAGE_REGISTRY"
    fi
    if [ "$PIP_INDEX_URL" != "https://pypi.org/simple" ]; then
        log_info "pip 镜像源: $PIP_INDEX_URL"
    fi
    echo ""

    # 检查前置条件
    log_info "检查前置条件..."
    check_command docker || exit 1
    check_docker_running
    log_success "前置条件检查通过"
    echo ""

    # 处理简化架构参数
    if [ ${#ARCH_LIST[@]} -gt 0 ]; then
        local platforms_list=()
        for arch in "${ARCH_LIST[@]}"; do
            platforms_list+=("$(convert_arch_to_platform "$arch")")
        done
        PLATFORMS=$(IFS=','; echo "${platforms_list[*]}")
        log_info "架构选项转换为: $PLATFORMS"
    fi

    # 执行命令
    case "$COMMAND" in
        build)
            build_all_images
            ;;
        push)
            PUSH=true
            build_all_images
            ;;
        pull)
            pull_images
            ;;
        *)
            log_error "未知命令: $COMMAND"
            show_usage
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
