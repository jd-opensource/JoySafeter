#!/bin/bash
# JoySafeter - 镜像构建和推送脚本
# 支持：构建多架构镜像、推送镜像、拉取镜像
#
# 所有 Dockerfile 统一位于 deploy/docker/ 目录

set -euo pipefail

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
REGISTRY="${DOCKER_REGISTRY:-}"
TAG="${IMAGE_TAG:-latest}"
# 构建溯源：烘进 backend 镜像的 GIT_COMMIT_SHA（docker inspect / printenv 可读，供可审计发布）。
# CI 传 github.sha；脚本自建时默认取 git 短 SHA，脏工作树追加 -dirty，取不到则 unknown。
# 允许外部环境变量覆盖（与 CI 一致）。
GIT_COMMIT_SHA="${GIT_COMMIT_SHA:-$(
    if git -C "$PROJECT_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
        sha="$(git -C "$PROJECT_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
        if [ -n "$(git -C "$PROJECT_ROOT" status --porcelain 2>/dev/null)" ]; then
            sha="${sha}-dirty"
        fi
        printf '%s' "$sha"
    else
        printf 'unknown'
    fi
)}"
# 默认多平台构建：amd64 + arm64
DEFAULT_PLATFORMS="linux/amd64,linux/arm64"
PLATFORMS="" # 初始为空，稍后根据命令和系统动态设置
USE_BUILDX="${USE_BUILDX:-true}"
# 镜像源配置（两个变量控制所有拉取）：
#   BASE_IMAGE_REGISTRY — 官方库镜像前缀（python/node/rust/debian/postgres/redis）
#                         默认 public.ecr.aws/docker/library/ （国内直连可达）
#   DOCKER_MIRROR       — 第三方镜像代理前缀（envoy 等非官方库镜像）
#                         默认 docker.m.daocloud.io （DaoCloud 国内 CDN）
BASE_IMAGE_REGISTRY="${BASE_IMAGE_REGISTRY:-public.ecr.aws/docker/library/}"
DOCKER_MIRROR="${DOCKER_MIRROR:-docker.m.daocloud.io}"
APT_MIRROR_BASE="${APT_MIRROR_BASE:-http://mirrors.ustc.edu.cn}"
ALPINE_MIRROR_BASE="${ALPINE_MIRROR_BASE:-https://mirrors.ustc.edu.cn/alpine}"
# BuildKit builder 镜像（multiarch builder 启动 buildx_buildkit_multiarch0 容器时使用）。
# 留空则使用 buildx 默认的 docker.io/moby/buildkit:buildx-stable-1。
# 无法访问 docker.io 的网络下，设为可达的 mirror，例如：
#   BUILDKIT_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/moby/buildkit:buildx-stable-1-linuxarm64
BUILDKIT_IMAGE="${BUILDKIT_IMAGE:-}"
# 是否禁用 Docker 构建缓存（默认使用缓存）
NO_CACHE="${NO_CACHE:-false}"
# pip/uv 镜像源配置（默认使用清华大学镜像源）
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple}"
UV_INDEX_URL="${UV_INDEX_URL:-https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple}"
CARGO_REGISTRIES_CRATES_IO_INDEX="${CARGO_REGISTRIES_CRATES_IO_INDEX:-sparse+https://rsproxy.cn/index/}"
# Rust 镜像从 BASE_IMAGE_REGISTRY 派生
RUST_IMAGE="${RUST_IMAGE:-${BASE_IMAGE_REGISTRY}rust:1-bookworm}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:-${BASE_IMAGE_REGISTRY}debian:bookworm-slim}"
SKILLSPECTOR_REPO_URL="${SKILLSPECTOR_REPO_URL:-https://github.com/NVIDIA/SkillSpector.git}"
DEFAULT_SKILLSPECTOR_SOURCE_PATH="$PROJECT_ROOT/.deps/SkillSpector"
PLAIN_IMAGE="${PLAIN_IMAGE:-false}"

# Capability modules. Each module owns one deployment boundary and exposes
# functions only; this entrypoint owns argument parsing and command routing.
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/compose.sh
source "$SCRIPT_DIR/lib/compose.sh"
# shellcheck source=lib/development.sh
source "$SCRIPT_DIR/lib/development.sh"
# shellcheck source=lib/images.sh
source "$SCRIPT_DIR/lib/images.sh"
# shellcheck source=lib/verification.sh
source "$SCRIPT_DIR/lib/verification.sh"
# shellcheck source=lib/kubernetes.sh
source "$SCRIPT_DIR/lib/kubernetes.sh"
show_usage() {
    cat << EOF
使用方法: $0 [命令] [选项]

命令:
  doctor             本地部署环境预检（不启动容器）
  local              本地 Docker Compose 一键部署（自动按 Docker CPU 架构选择平台）
  verify             验证本地服务、orchestrator 健康/指标和全部 runtime 镜像
  dev                宿主机运行 API/Worker/Orchestrator/Frontend，依赖使用容器
  build              构建核心部署镜像（backend, frontend, orchestrator-rs, skillspector）
  push               构建并推送多架构镜像到仓库
  pull               拉取镜像，并把拉取到的镜像名同步到 deploy/.env
  registry           查看统一镜像组件 Registry；可输出 GitHub Actions matrix
  down               停止并移除本地 Compose 服务（保留数据卷）
  logs               跟随查看服务日志（可跟服务名，如 logs api worker）
  restart            重启本地 Compose 服务（可跟服务名）
  status             查看本地 Compose 服务状态
  k8s COMMAND        Helm/Kubernetes 部署、验证、扩缩容和 Secret 管理

选项:
  -h, --help             显示帮助信息
  -r, --registry REGISTRY 镜像仓库地址（默认: 空，本地镜像）
  -t, --tag TAG          镜像标签（默认: latest）
  --platform PLATFORMS   目标平台架构，多个用逗号分隔（默认: linux/amd64,linux/arm64）
  --arch ARCH            简化的架构选项，可多次使用
                         支持: amd64, arm64, armv7
  --component NAME       处理指定组件，可重复；$(print_image_component_options)
  --group GROUP          处理组件组，可重复；core/runtime/all（默认: core）
  --profile PROFILE      处理发布集合；$(print_image_profile_options)
  --family FAMILY        registry 的 CI 镜像族；container/orchestrator（默认: all）
  --format FORMAT        registry 输出格式；table/github（默认: table）
  --no-cache             禁用 Docker 构建缓存（默认使用缓存）
  --plain                单架构 push 使用普通 image manifest，并由宿主 Docker 推送
  --mirror MIRROR        使用国内镜像源加速（aliyun, tencent, huawei, daocloud）
                         同时设置 BASE_IMAGE_REGISTRY 和 DOCKER_MIRROR
  --pip-mirror MIRROR    使用国内 pip 镜像源（aliyun, tencent, huawei, jd）

环境变量:
  DOCKER_REGISTRY        镜像仓库地址（默认: 空，本地镜像）
  REGISTRY_SCHEME        Registry 健康检查协议（http/https；默认读取 Docker daemon 配置）
$(print_image_component_environment)
  IMAGE_TAG              镜像标签（默认: latest）
  BUILD_PLATFORMS        目标平台架构（默认: linux/amd64,linux/arm64）
  PIP_INDEX_URL          pip 镜像源（默认: https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple）
  UV_INDEX_URL           uv 镜像源（默认: https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple）
  CARGO_REGISTRIES_CRATES_IO_INDEX
                         runtime Runner 构建使用的 Cargo sparse index
  RUST_IMAGE             Rust 编译镜像（默认: 从 BASE_IMAGE_REGISTRY 派生）
  BASE_IMAGE_REGISTRY    官方库镜像前缀（默认: public.ecr.aws/docker/library/）
  DOCKER_MIRROR          第三方镜像代理前缀（默认: docker.m.daocloud.io）
  APT_MIRROR_BASE        Debian/Ubuntu 软件源根地址（默认: http://mirrors.ustc.edu.cn）
  ALPINE_MIRROR_BASE     Alpine 软件源根地址（默认: https://mirrors.ustc.edu.cn/alpine）
  BUILDKIT_IMAGE         BuildKit builder 镜像（默认: 空=用 buildx 默认 docker.io/moby/buildkit）
  SKILLSPECTOR_SOURCE_PATH SkillSpector 源码路径（local 默认: ../.deps/SkillSpector）
  SKILLSPECTOR_REPO_URL    SkillSpector 缺失时克隆的仓库地址
  NO_CACHE               是否禁用构建缓存（默认: false，使用缓存）

示例:
  # 只做本地部署环境预检
  $0 doctor

  # 按 Docker daemon CPU 架构自动部署本地完整栈
  $0 local

  # 宿主机源码开发模式
  $0 dev

  # 强制按 amd64 或 arm64 部署
  $0 local --arch amd64
  $0 local --arch arm64

  # 构建核心部署镜像
  $0 build

  # 查看 Registry / 生成 CI matrix
  $0 registry
  $0 registry --family container --format github

  # 只构建后端镜像
  $0 build --component backend

  # 同时构建后端和 orchestrator
  $0 build --component backend --component orchestrator

  # 构建四个独立 Runtime 镜像
  $0 build --group runtime

  # 构建远程 amd64 服务器需要的全部镜像
  $0 build --group all --arch amd64

  # 构建并推送到仓库
  $0 push

  # 内部仓库不接受 OCI index 时，推送单架构普通 manifest
  $0 push --group all --arch amd64 --plain

  # 只发布编排面和四个 sandbox runtime
  $0 push --profile sandbox-plane --arch amd64 --plain \
    --registry aisec-repo.jd.com/joysafeter --tag latest

  # 发布除 frontend/backend(API/worker) 外的全部镜像
  $0 push --profile non-app --arch amd64 --plain \
    --registry aisec-repo.jd.com/joysafeter --tag latest

  # 构建指定架构并推送
  $0 push --arch amd64 --arch arm64

  # 构建时指定镜像源
  $0 build --mirror aliyun

  # 使用国内镜像源加速构建
  $0 build --mirror huawei --pip-mirror aliyun

  # 禁用缓存构建镜像
  $0 build --no-cache

  # 拉取最新镜像
  $0 pull

  # 拉取指定标签的镜像
  $0 pull --tag v1.0.0

  # 查看本地栈运行状态
  $0 status

  # 跟随全部服务日志 / 只看某几个服务
  $0 logs
  $0 logs api worker

  # 重启全部服务 / 只重启某个服务
  $0 restart
  $0 restart frontend

  # 停止并移除本地栈（保留数据卷）
  $0 down

  # Helm/Kubernetes
  $0 k8s --help
  $0 k8s deploy --namespace joysafeter --values values.local.yaml
  $0 --registry registry.example.com/joysafeter --tag v1 k8s deploy --sync-images
  $0 k8s verify --namespace joysafeter
EOF
}

# 检查命令是否存在
main() {
    local COMMAND=""
    local PUSH=false
    local PLAIN_IMAGE="${PLAIN_IMAGE:-false}"
    local ARCH_LIST_STR=""
    local SERVICE_ARGS=()
    local REGISTRY_FAMILY="all"
    local REGISTRY_FORMAT="table"

    # 解析参数
    while [[ $# -gt 0 ]]; do
        if [ "$COMMAND" = "k8s" ]; then
            SERVICE_ARGS+=("$1")
            shift
            continue
        fi
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
                local platform=$(convert_arch_to_platform "$2")
                if [ -z "$ARCH_LIST_STR" ]; then
                    ARCH_LIST_STR="$platform"
                else
                    ARCH_LIST_STR="$ARCH_LIST_STR,$platform"
                fi
                shift 2
                ;;
            --mirror)
                case "$2" in
                    aliyun)
                        BASE_IMAGE_REGISTRY="registry.cn-hangzhou.aliyuncs.com/library/"
                        DOCKER_MIRROR="registry.cn-hangzhou.aliyuncs.com"
                        ;;
                    tencent)
                        BASE_IMAGE_REGISTRY="ccr.ccs.tencentyun.com/library/"
                        DOCKER_MIRROR="ccr.ccs.tencentyun.com"
                        ;;
                    huawei)
                        BASE_IMAGE_REGISTRY="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/"
                        DOCKER_MIRROR="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io"
                        # 未显式指定时，按架构推导华为云 BuildKit 镜像，避免 buildx 回退拉 docker.io
                        if [ -z "$BUILDKIT_IMAGE" ]; then
                            BUILDKIT_IMAGE="$(huawei_buildkit_image)"
                            log_info "自动推导 BuildKit 镜像: $BUILDKIT_IMAGE"
                        fi
                        ;;
                    daocloud)
                        BASE_IMAGE_REGISTRY="docker.m.daocloud.io/library/"
                        DOCKER_MIRROR="docker.m.daocloud.io"
                        ;;
                    *)
                        BASE_IMAGE_REGISTRY="$2"
                        DOCKER_MIRROR="${2%/}"
                        ;;
                esac
                RUST_IMAGE="${BASE_IMAGE_REGISTRY}rust:1-bookworm"
                RUNTIME_IMAGE="${BASE_IMAGE_REGISTRY}debian:bookworm-slim"
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
            --component)
                select_image_component "$2" || exit 1
                shift 2
                ;;
            --group)
                select_image_group "$2" || exit 1
                shift 2
                ;;
            --profile)
                select_image_profile "$2" || exit 1
                shift 2
                ;;
            --family)
                REGISTRY_FAMILY="$2"
                shift 2
                ;;
            --format)
                REGISTRY_FORMAT="$2"
                shift 2
                ;;
            --no-cache)
                NO_CACHE=true
                shift
                ;;
            --plain)
                PLAIN_IMAGE=true
                shift
                ;;
            doctor|local|dev|build|push|pull|registry|verify|down|logs|restart|status|k8s)
                COMMAND="$1"
                shift
                ;;
            *)
                # 生命周期命令（down/logs/restart/status）后面可跟服务名或原生
                # compose 选项（如 --tail=100），原样透传给 docker compose。
                # COMMAND 为空（尚未识别命令）时落入下方 *)，保持未知选项报错。
                case "$COMMAND" in
                    down|logs|restart|status)
                        SERVICE_ARGS+=("$1")
                        shift
                        ;;
                    *)
                        log_error "未知选项: $1"
                        show_usage
                        exit 1
                        ;;
                esac
                ;;
        esac
    done

    # 如果没有指定命令，显示帮助
    if [ -z "$COMMAND" ]; then
        show_usage
        exit 0
    fi

    case "$COMMAND" in
        doctor|local|build|push|pull|verify|down|logs|restart|status)
            check_command docker || exit 1
            check_docker_running
            if [ -n "$ARCH_LIST_STR" ]; then
                PLATFORMS="$ARCH_LIST_STR"
            elif [ -z "$PLATFORMS" ]; then
                if [ "$COMMAND" = "push" ]; then
                    PLATFORMS="${BUILD_PLATFORMS:-$DEFAULT_PLATFORMS}"
                else
                    PLATFORMS="${BUILD_PLATFORMS:-$(get_docker_platform)}"
                fi
            fi
            ;;
    esac

    if [ "$PLAIN_IMAGE" = true ]; then
        [ "$COMMAND" = push ] || { log_error "--plain 仅适用于 push"; exit 1; }
        [[ "$PLATFORMS" != *,* ]] || { log_error "--plain 只支持单一 --arch/--platform"; exit 1; }
    fi

    # 执行命令
    case "$COMMAND" in
        (build)
            build_selected_images
            ;;
        (doctor)
            run_local_doctor
            ;;
        (local)
            run_local_compose
            ;;
        (dev)
            run_host_development
            ;;
        (push)
            PUSH=true
            build_selected_images
            ;;
        (pull)
            pull_selected_images
            ;;
        (registry)
            print_image_component_registry "$REGISTRY_FAMILY" "$REGISTRY_FORMAT"
            ;;
        (verify)
            run_local_verification
            ;;
        (down)
            if [ "${#SERVICE_ARGS[@]}" -eq 0 ]; then
                run_down
            else
                run_down "${SERVICE_ARGS[@]}"
            fi
            ;;
        (logs)
            if [ "${#SERVICE_ARGS[@]}" -eq 0 ]; then
                run_logs
            else
                run_logs "${SERVICE_ARGS[@]}"
            fi
            ;;
        (restart)
            if [ "${#SERVICE_ARGS[@]}" -eq 0 ]; then
                run_restart
            else
                run_restart "${SERVICE_ARGS[@]}"
            fi
            ;;
        (status)
            if [ "${#SERVICE_ARGS[@]}" -eq 0 ]; then
                run_status
            else
                run_status "${SERVICE_ARGS[@]}"
            fi
            ;;
        (k8s)
            if [ "${#SERVICE_ARGS[@]}" -eq 0 ]; then
                run_kubernetes_command
            else
                run_kubernetes_command "${SERVICE_ARGS[@]}"
            fi
            ;;
        (*)
            log_error "未知命令: $COMMAND"
            show_usage
            exit 1
            ;;
    esac
}

# 运行主函数；测试和工具可以 source 本文件复用纯函数而不触发 CLI。
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
