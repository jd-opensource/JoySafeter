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
REGISTRY="${DOCKER_REGISTRY:-}"
BACKEND_IMAGE="${BACKEND_IMAGE:-joysafeter-backend}"
FRONTEND_IMAGE="${FRONTEND_IMAGE:-joysafeter-frontend}"
ORCHESTRATOR_RS_IMAGE="${ORCHESTRATOR_RS_IMAGE:-joysafeter-orchestrator-rs}"
EGRESS_CONTROLLER_IMAGE="${EGRESS_CONTROLLER_IMAGE:-joysafeter-egress-controller}"
SKILLSPECTOR_IMAGE="${SKILLSPECTOR_IMAGE:-joysafeter-skillspector}"
CLAUDECODE_IMAGE="${CLAUDECODE_IMAGE:-joysafeter-claudecode}"
CODEX_IMAGE="${CODEX_IMAGE:-joysafeter-codex}"
NATIVE_IMAGE="${NATIVE_IMAGE:-joysafeter-native}"
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
platform_from_arch() {
    local arch="$1"
    case "$arch" in
        x86_64|amd64)
            echo "linux/amd64"
            ;;
        arm64|aarch64)
            echo "linux/arm64"
            ;;
        armv7l|arm/v7)
            echo "linux/arm/v7"
            ;;
        *)
            echo "linux/amd64" # 默认回退
            ;;
    esac
}

get_host_platform() {
    platform_from_arch "$(uname -m)"
}

get_docker_platform() {
    local arch
    arch=$(docker info --format '{{.Architecture}}' 2>/dev/null || true)
    if [ -n "$arch" ]; then
        platform_from_arch "$arch"
        return
    fi
    get_host_platform
}

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
# 是否禁用 Docker 构建缓存（默认使用缓存）
NO_CACHE="${NO_CACHE:-false}"
# pip/uv 镜像源配置（默认使用清华大学镜像源）
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple}"
UV_INDEX_URL="${UV_INDEX_URL:-https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple}"
# Cargo source replacement（不仅替换索引，也替换 crate 下载端点）
CARGO_REGISTRY_MIRROR="${CARGO_REGISTRY_MIRROR:-sparse+https://rsproxy.cn/index/}"
# Rust 镜像从 BASE_IMAGE_REGISTRY 派生
RUST_IMAGE="${RUST_IMAGE:-${BASE_IMAGE_REGISTRY}rust:1-bookworm}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:-${BASE_IMAGE_REGISTRY}debian:bookworm-slim}"
SKILLSPECTOR_REPO_URL="${SKILLSPECTOR_REPO_URL:-https://github.com/NVIDIA/SkillSpector.git}"
DEFAULT_SKILLSPECTOR_SOURCE_PATH="$PROJECT_ROOT/.deps/SkillSpector"

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
    printf "${BLUE}ℹ️  %s${NC}\n" "$1"
}

log_success() {
    printf "${GREEN}✅ %s${NC}\n" "$1"
}

log_warning() {
    printf "${YELLOW}⚠️  %s${NC}\n" "$1" >&2
}

log_error() {
    printf "${RED}❌ %s${NC}\n" "$1" >&2
}

# 显示使用说明
show_usage() {
    cat << EOF
使用方法: $0 [命令] [选项]

命令:
  doctor             本地部署环境预检（不启动容器）
  local              本地 Docker Compose 一键部署（自动按 Docker CPU 架构选择平台）
  build              构建核心部署镜像（backend, frontend, orchestrator-rs, egress-controller, skillspector）
  push               构建并推送多架构镜像到仓库
  pull               拉取镜像，并把拉取到的镜像名同步到 deploy/.env
  down               停止并移除本地 Compose 服务（保留数据卷）
  logs               跟随查看服务日志（可跟服务名，如 logs api worker）
  restart            重启本地 Compose 服务（可跟服务名）
  status             查看本地 Compose 服务状态
  k8s <子命令>       Kubernetes(k3s) 部署方式：deploy/verify/status/logs/down（详见 $0 k8s help）

选项:
  -h, --help             显示帮助信息
  -r, --registry REGISTRY 镜像仓库地址（默认: 空，本地镜像）
  -t, --tag TAG          镜像标签（默认: latest）
  --platform PLATFORMS   目标平台架构，多个用逗号分隔（默认: linux/amd64,linux/arm64）
  --arch ARCH            简化的架构选项，可多次使用
                         支持: amd64, arm64, armv7
  --api-url URL          （已废弃）前端 API 地址现在通过容器环境变量运行时注入
  --backend-only         只处理后端镜像
  --frontend-only        只处理前端镜像
  --orchestrator-only    只处理 Rust orchestrator 镜像
  --egress-controller-only 只处理 Envoy egress-controller 镜像
  --skillspector-only    只处理 SkillSpector 镜像
  --runtime-only         只处理 agent 运行镜像（claudecode, codex, native）
  --claudecode-only      只处理 Claude Code 运行镜像
  --codex-only           只处理 Codex 运行镜像
  --native-only          只处理 Native 运行镜像
  --all                  构建所有镜像（核心部署镜像 + agent runtime 镜像）
  --no-cache             禁用 Docker 构建缓存（默认使用缓存）
  --mirror MIRROR        使用国内镜像源加速（aliyun, tencent, huawei, daocloud）
                         同时设置 BASE_IMAGE_REGISTRY 和 DOCKER_MIRROR
  --pip-mirror MIRROR    使用国内 pip 镜像源（aliyun, tencent, huawei, jd）

环境变量:
  DOCKER_REGISTRY        镜像仓库地址（默认: 空，本地镜像）
  BACKEND_IMAGE          后端镜像名称（默认: joysafeter-backend）
  FRONTEND_IMAGE         前端镜像名称（默认: joysafeter-frontend）
  ORCHESTRATOR_RS_IMAGE  Rust orchestrator 镜像名称（默认: joysafeter-orchestrator-rs）
  EGRESS_CONTROLLER_IMAGE Envoy egress-controller 镜像名称（默认: joysafeter-egress-controller）
  SKILLSPECTOR_IMAGE     SkillSpector 镜像名称（默认: joysafeter-skillspector）
  CLAUDECODE_IMAGE       Claude Code 运行镜像名称（默认: joysafeter-claudecode）
  CODEX_IMAGE            Codex 运行镜像名称（默认: joysafeter-codex）
  NATIVE_IMAGE           Native 运行镜像名称（默认: joysafeter-native）
  IMAGE_TAG              镜像标签（默认: latest）
  BUILD_PLATFORMS        目标平台架构（默认: linux/amd64,linux/arm64）
  PIP_INDEX_URL          pip 镜像源（默认: https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple）
  UV_INDEX_URL           uv 镜像源（默认: https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple）
  RUST_IMAGE             Rust 编译镜像（默认: 从 BASE_IMAGE_REGISTRY 派生）
  BASE_IMAGE_REGISTRY    官方库镜像前缀（默认: public.ecr.aws/docker/library/）
  DOCKER_MIRROR          第三方镜像代理前缀（默认: docker.m.daocloud.io）
  SKILLSPECTOR_SOURCE_PATH SkillSpector 源码路径（local 默认: ../.deps/SkillSpector）
  SKILLSPECTOR_REPO_URL    SkillSpector 缺失时克隆的仓库地址
  NO_CACHE               是否禁用构建缓存（默认: false，使用缓存）

示例:
  # 只做本地部署环境预检
  $0 doctor

  # 按 Docker daemon CPU 架构自动部署本地完整栈
  $0 local

  # 强制按 amd64 或 arm64 部署
  $0 local --arch amd64
  $0 local --arch arm64

  # 构建核心部署镜像
  $0 build

  # 只构建后端多架构镜像
  $0 build --backend-only

  # 只构建前端多架构镜像
  $0 build --frontend-only

  # 构建核心部署镜像 + agent runtime 镜像
  $0 build --all

  # 构建远程 amd64 服务器需要的全部镜像
  $0 build --all --arch amd64

  # 构建并推送到仓库
  $0 push

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

  # Kubernetes(k3s) 部署：先构建镜像，再部署，最后端到端真实验证
  $0 build --all
  $0 k8s deploy
  $0 k8s verify
  $0 k8s status
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

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        log_error "docker compose / docker-compose 均不可用"
        suggest_compose_install
        exit 1
    fi
}

suggest_compose_install() {
    local host_os
    host_os="$(uname -s 2>/dev/null || echo unknown)"

    case "$host_os" in
        Darwin)
            log_error "macOS 安装方法:"
            if command -v brew >/dev/null 2>&1; then
                log_error "  brew install docker-compose"
                local brew_prefix
                brew_prefix="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
                log_error "  安装后需在 ~/.docker/config.json 中添加:"
                log_error "    \"cliPluginsExtraDirs\": [\"${brew_prefix}/lib/docker/cli-plugins\"]"
            else
                log_error "  方式 1: 安装 Docker Desktop for Mac（自带 compose 插件）"
                log_error "  方式 2: 手动安装插件:"
                log_error "    mkdir -p ~/.docker/cli-plugins"
                local arch_suffix
                arch_suffix="$(uname -m | sed 's/x86_64/x86_64/; s/arm64/aarch64/')"
                log_error "    curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-darwin-${arch_suffix} -o ~/.docker/cli-plugins/docker-compose"
                log_error "    chmod +x ~/.docker/cli-plugins/docker-compose"
            fi
            ;;
        Linux)
            log_error "Linux 安装方法:"
            if command -v apt-get >/dev/null 2>&1; then
                log_error "  sudo apt-get update && sudo apt-get install -y docker-compose-plugin"
            elif command -v dnf >/dev/null 2>&1; then
                log_error "  sudo dnf install -y docker-compose-plugin"
            elif command -v yum >/dev/null 2>&1; then
                log_error "  sudo yum install -y docker-compose-plugin"
            elif command -v pacman >/dev/null 2>&1; then
                log_error "  sudo pacman -S docker-compose"
            else
                log_error "  通过包管理器安装 docker-compose-plugin，或手动安装:"
            fi
            log_error "  或手动安装插件:"
            log_error "    mkdir -p ~/.docker/cli-plugins"
            local arch_suffix
            arch_suffix="$(uname -m | sed 's/x86_64/x86_64/; s/aarch64/aarch64/; s/armv7l/armv7/')"
            log_error "    curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${arch_suffix} -o ~/.docker/cli-plugins/docker-compose"
            log_error "    chmod +x ~/.docker/cli-plugins/docker-compose"
            ;;
        *)
            log_error "请参考 https://docs.docker.com/compose/install/ 安装 Docker Compose"
            ;;
    esac
}

suggest_buildx_install() {
    local host_os
    host_os="$(uname -s 2>/dev/null || echo unknown)"

    case "$host_os" in
        Darwin)
            log_error "macOS 安装方法:"
            if command -v brew >/dev/null 2>&1; then
                log_error "  brew install docker-buildx"
                local brew_prefix
                brew_prefix="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
                log_error "  安装后需在 ~/.docker/config.json 中添加:"
                log_error "    \"cliPluginsExtraDirs\": [\"${brew_prefix}/lib/docker/cli-plugins\"]"
            else
                log_error "  方式 1: 安装 Docker Desktop for Mac（自带 buildx 插件）"
                log_error "  方式 2: 手动安装插件:"
                log_error "    mkdir -p ~/.docker/cli-plugins"
                local arch_suffix
                arch_suffix="$(uname -m | sed 's/x86_64/amd64/; s/arm64/arm64/')"
                log_error "    curl -SL https://github.com/docker/buildx/releases/latest/download/buildx-v\$(curl -s https://api.github.com/repos/docker/buildx/releases/latest | grep tag_name | cut -d'\"' -f4 | tr -d v).darwin-${arch_suffix} -o ~/.docker/cli-plugins/docker-buildx"
                log_error "    chmod +x ~/.docker/cli-plugins/docker-buildx"
            fi
            ;;
        Linux)
            log_error "Linux 安装方法:"
            if command -v apt-get >/dev/null 2>&1; then
                log_error "  sudo apt-get update && sudo apt-get install -y docker-buildx-plugin"
            elif command -v dnf >/dev/null 2>&1; then
                log_error "  sudo dnf install -y docker-buildx-plugin"
            elif command -v yum >/dev/null 2>&1; then
                log_error "  sudo yum install -y docker-buildx-plugin"
            elif command -v pacman >/dev/null 2>&1; then
                log_error "  sudo pacman -S docker-buildx"
            else
                log_error "  通过包管理器安装 docker-buildx-plugin，或手动安装:"
            fi
            log_error "  或手动安装插件:"
            log_error "    mkdir -p ~/.docker/cli-plugins"
            local arch_suffix
            arch_suffix="$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/; s/armv7l/arm-v7/')"
            log_error "    curl -SL https://github.com/docker/buildx/releases/latest/download/buildx-v\$(curl -s https://api.github.com/repos/docker/buildx/releases/latest | grep tag_name | cut -d'\"' -f4 | tr -d v).linux-${arch_suffix} -o ~/.docker/cli-plugins/docker-buildx"
            log_error "    chmod +x ~/.docker/cli-plugins/docker-buildx"
            ;;
        *)
            log_error "请参考 https://docs.docker.com/build/install-buildx/ 安装 Docker Buildx"
            ;;
    esac
}

ensure_env_file() {
    local target="$1"
    local source="$2"
    if [ ! -f "$target" ]; then
        cp "$source" "$target"
        log_info "已创建 $target"
    fi
}

set_env_value() {
    local file="$1"
    local key="$2"
    local value="$3"
    local tmp="${file}.tmp"

    if grep -q "^${key}=" "$file" 2>/dev/null; then
        awk -v key="$key" -v value="$value" '
            BEGIN { done = 0 }
            $0 ~ "^" key "=" {
                print key "=" value
                done = 1
                next
            }
            { print }
            END {
                if (!done) {
                    print key "=" value
                }
            }
        ' "$file" > "$tmp"
        mv "$tmp" "$file"
    else
        printf "\n%s=%s\n" "$key" "$value" >> "$file"
    fi
}

read_env_value() {
    local file="$1"
    local key="$2"
    if [ ! -f "$file" ]; then
        return 0
    fi
    awk -v key="$key" '
        $0 ~ "^" key "=" {
            value = substr($0, index($0, "=") + 1)
            sub(/[[:space:]]+#.*$/, "", value)
            print value
            exit
        }
    ' "$file"
}

# vault 密钥合法性校验：64 位 hex（Rust 兼容）或 base64 解码后为 32 字节。
# 无 openssl 时无法校验，返回成功以避免误报。
vault_key_is_valid() {
    local key="$1"
    if printf '%s' "$key" | grep -Eq '^[0-9a-fA-F]{64}$'; then
        return 0
    fi
    if command -v openssl >/dev/null 2>&1; then
        local decoded_bytes
        decoded_bytes="$(printf '%s' "$key" | openssl base64 -d -A 2>/dev/null | wc -c | tr -d '[:space:]')"
        [ "$decoded_bytes" = "32" ] && return 0
        return 1
    fi
    return 0
}

# 确保 vault 加密密钥在 deploy/.env 与 backend/.env 中【存在且为同一把】。
# compose 的 env_file 顺序是 [backend/.env, deploy/.env]，后者覆盖前者，故
# deploy/.env 为权威真源。解析出唯一有效 key 后同步写入两个文件：
#   - deploy/.env 已有合法真实 key -> 以它为准；
#   - deploy/.env 为空/占位符：若 backend/.env 有合法真实 key 则提升为真源，否则 openssl 生成；
#   - 已有的合法真实 key 绝不静默丢弃（覆盖会让已有 enc: 密文永久无法解密）。
ensure_vault_encryption_key() {
    local deploy_env="$1"
    local backend_env="$2"
    local placeholder="CHANGE_ME_GENERATE_WITH_openssl_rand_base64_32"
    local key_var="JOYSAFETER_VAULT_ENCRYPTION_KEY"

    local deploy_key backend_key
    deploy_key="$(read_env_value "$deploy_env" "$key_var")"
    backend_key="$(read_env_value "$backend_env" "$key_var")"

    local deploy_real=false backend_real=false
    [ -n "$deploy_key" ] && [ "$deploy_key" != "$placeholder" ] && deploy_real=true
    [ -n "$backend_key" ] && [ "$backend_key" != "$placeholder" ] && backend_real=true

    local effective=""
    if [ "$deploy_real" = true ]; then
        if ! vault_key_is_valid "$deploy_key"; then
            log_warning "deploy/.env 的 $key_var 已设置但不是合法 32 字节密钥（64 位 hex 或 base64）；托管密钥会失败，请修正后再部署（本次不改动 backend/.env）"
            return 0
        fi
        effective="$deploy_key"
    elif [ "$backend_real" = true ]; then
        if vault_key_is_valid "$backend_key"; then
            effective="$backend_key"
            log_info "复用 backend/.env 中已有的 $key_var 作为 vault 密钥真源"
        else
            log_warning "backend/.env 的 $key_var 已设置但不是合法 32 字节密钥；将忽略它并生成新密钥"
        fi
    fi

    if [ -z "$effective" ]; then
        if ! command -v openssl >/dev/null 2>&1; then
            log_warning "未检测到 openssl，无法自动生成 $key_var；托管密钥功能将不可用。请手动在 deploy/.env 与 backend/.env 设置同一把（openssl rand -base64 32）"
            return 0
        fi
        effective="$(openssl rand -base64 32)"
        log_success "已自动生成 $key_var（vault 凭证加密密钥）"
        log_warning "该密钥一经启用请勿更改，否则已加密的托管密钥密文将无法解密"
    fi

    if [ "$deploy_key" != "$effective" ]; then
        set_env_value "$deploy_env" "$key_var" "$effective"
    fi
    if [ "$backend_key" != "$effective" ]; then
        if [ "$backend_real" = true ]; then
            log_warning "backend/.env 原有一把不同的 $key_var，已同步为 deploy/.env 的权威密钥（compose 中 deploy/.env 本就覆盖 backend/.env）"
        fi
        set_env_value "$backend_env" "$key_var" "$effective"
    fi
}

compose_path_exists() {
    local path="$1"
    case "$path" in
        /*) [ -e "$path" ] ;;
        *) [ -e "$SCRIPT_DIR/$path" ] ;;
    esac
}

detect_docker_socket_path() {
    # 输出要 bind-mount 进容器的 Docker socket 路径。
    #
    # 关键点：bind-mount 的“源路径”由 Docker DAEMON 解析，而不是当前这台机器。
    # 对 VM 型运行时（macOS/Windows 上的 Docker Desktop / Colima / Lima / Rancher，
    # 以及 Linux 上的 Docker Desktop / Colima），daemon 跑在虚拟机里，它自己的 socket
    # 永远是虚拟机内的 /var/run/docker.sock —— 而不是宿主机侧的转发 socket
    # （如 ~/.colima/<profile>/docker.sock）。宿主机侧的转发 socket 在虚拟机里只是
    # virtiofs/9p 上的一个特殊文件，无法作为 unix socket 挂载，Docker 会退化成 mkdir
    # 从而报 “operation not supported”。
    local host_os endpoint sockpath ctx_name
    host_os="$(uname -s 2>/dev/null || echo unknown)"
    endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
    ctx_name="$(docker context inspect --format '{{.Name}}' 2>/dev/null || true)"
    case "$endpoint" in
        unix://*) sockpath="${endpoint#unix://}" ;;
        *)        sockpath="" ;;  # tcp:// / ssh:// 远程 daemon，或未取到
    esac

    # macOS / Windows：dockerd 一定在虚拟机内，daemon 侧 socket 即 /var/run/docker.sock。
    case "$host_os" in
        Darwin|MINGW*|MSYS*|CYGWIN*)
            printf '%s\n' "/var/run/docker.sock"
            return
            ;;
    esac

    # Linux 上的 VM 型运行时（Colima / Docker Desktop）：daemon 侧 socket 同样是
    # 虚拟机内的 /var/run/docker.sock。用 context 名与转发 socket 路径识别。
    case "$ctx_name" in
        colima*|desktop*)
            printf '%s\n' "/var/run/docker.sock"
            return
            ;;
    esac
    case "$sockpath" in
        */.colima/*|*/.lima/*|*/.docker/*)
            printf '%s\n' "/var/run/docker.sock"
            return
            ;;
    esac

    # 原生 Linux（root 或 rootless）：daemon 在宿主机，context 里的 socket 路径可直接挂载。
    if [ -S "$sockpath" ]; then
        printf '%s\n' "$sockpath"
        return
    fi
    if [ -S "/var/run/docker.sock" ]; then
        printf '%s\n' "/var/run/docker.sock"
        return
    fi
    if [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "$XDG_RUNTIME_DIR/docker.sock" ]; then
        printf '%s\n' "$XDG_RUNTIME_DIR/docker.sock"
        return
    fi
    # 未检测到本地 socket（例如远程 DOCKER_HOST）。不输出，由调用方给出告警。
}

skillspector_source_valid() {
    local path="$1"
    [ -d "$path" ] && [ -f "$path/pyproject.toml" ] && [ -d "$path/src" ]
}

clone_skillspector() {
    local dest="$1"
    check_command git || exit 1
    if [ -d "$dest" ]; then
        rm -rf "$dest"
    fi
    mkdir -p "$(dirname "$dest")"
    log_info "克隆 SkillSpector: $SKILLSPECTOR_REPO_URL -> $dest"
    git clone --depth 1 "$SKILLSPECTOR_REPO_URL" "$dest"
}

ensure_skillspector_source() {
    local deploy_env="$1"
    local configured_path="${SKILLSPECTOR_SOURCE_PATH:-$(read_env_value "$deploy_env" "SKILLSPECTOR_SOURCE_PATH")}"

    if [ -n "$configured_path" ]; then
        local resolved_path
        case "$configured_path" in
            /*) resolved_path="$configured_path" ;;
            *)  resolved_path="$SCRIPT_DIR/$configured_path" ;;
        esac
        if skillspector_source_valid "$resolved_path"; then
            set_env_value "$deploy_env" "SKILLSPECTOR_SOURCE_PATH" "$configured_path"
            log_success "SkillSpector 源码: $configured_path"
            return
        fi
        log_warning "配置的 SkillSpector 路径无效（缺少 pyproject.toml 或 src/）: $resolved_path"
    fi

    if ! skillspector_source_valid "$DEFAULT_SKILLSPECTOR_SOURCE_PATH"; then
        clone_skillspector "$DEFAULT_SKILLSPECTOR_SOURCE_PATH"
    fi

    set_env_value "$deploy_env" "SKILLSPECTOR_SOURCE_PATH" "../.deps/SkillSpector"
    log_success "SkillSpector 源码: ../.deps/SkillSpector"
}

warn_if_port_busy() {
    local name="$1"
    local port="$2"
    if [ -z "$port" ]; then
        return
    fi
    if ! command -v lsof >/dev/null 2>&1; then
        return
    fi
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        log_warning "$name 端口 $port 已被监听；如果不是现有 JoySafeter 容器，启动可能失败"
    fi
}

check_local_ports() {
    local deploy_env="$1"
    warn_if_port_busy "Frontend" "$(read_env_value "$deploy_env" "FRONTEND_PORT_HOST")"
    warn_if_port_busy "Backend API" "$(read_env_value "$deploy_env" "BACKEND_PORT_HOST")"
    warn_if_port_busy "PostgreSQL" "$(read_env_value "$deploy_env" "POSTGRES_PORT_HOST")"
    warn_if_port_busy "Redis" "$(read_env_value "$deploy_env" "REDIS_PORT_HOST")"
    warn_if_port_busy "Rust orchestrator gRPC" "$(read_env_value "$deploy_env" "JOYSAFETER_GRPC_PORT_HOST")"
}

warn_if_sandbox_runtime_image_missing() {
    local deploy_env="$1"
    local sandbox_image="${JOYSAFETER_SANDBOX_IMAGE:-$(read_env_value "$deploy_env" "JOYSAFETER_SANDBOX_IMAGE")}"
    sandbox_image="${sandbox_image:-joysafeter-claudecode:latest}"

    if docker image inspect "$sandbox_image" >/dev/null 2>&1; then
        log_success "Sandbox runtime image: $sandbox_image"
        return
    fi

    log_warning "Sandbox runtime image missing: $sandbox_image; agent task execution will fail until it is built/pulled"
    log_warning "Build it with: ./deploy.sh build --claudecode-only --arch $(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')"
}

validate_local_compose_config() {
    (
        cd "$SCRIPT_DIR"
        DOCKER_DEFAULT_PLATFORM="$PLATFORMS" \
        BASE_IMAGE_REGISTRY="$BASE_IMAGE_REGISTRY" \
        RUST_IMAGE="$RUST_IMAGE" \
        RUNTIME_IMAGE="$RUNTIME_IMAGE" \
        compose --profile local-redis --profile sandbox config >/dev/null
    )
    log_success "Compose 配置预检通过"
}

compose_local_env() {
    DOCKER_DEFAULT_PLATFORM="$PLATFORMS" \
    BASE_IMAGE_REGISTRY="$BASE_IMAGE_REGISTRY" \
    RUST_IMAGE="$RUST_IMAGE" \
    RUNTIME_IMAGE="$RUNTIME_IMAGE" \
    COMPOSE_BAKE="${COMPOSE_BAKE:-false}" \
    compose "$@"
}

sync_local_core_image_env() {
    local deploy_env="$1"
    local normalized_registry
    normalized_registry="$(normalize_registry "$REGISTRY")"

    if [ -n "$normalized_registry" ]; then
        set_env_value "$deploy_env" "BACKEND_FULL_IMAGE" "${normalized_registry}/${BACKEND_IMAGE}:${TAG}"
        set_env_value "$deploy_env" "FRONTEND_FULL_IMAGE" "${normalized_registry}/${FRONTEND_IMAGE}:${TAG}"
        set_env_value "$deploy_env" "ORCHESTRATOR_RS_FULL_IMAGE" "${normalized_registry}/${ORCHESTRATOR_RS_IMAGE}:${TAG}"
        set_env_value "$deploy_env" "EGRESS_CONTROLLER_FULL_IMAGE" "${normalized_registry}/${EGRESS_CONTROLLER_IMAGE}:${TAG}"
        set_env_value "$deploy_env" "SKILLSPECTOR_FULL_IMAGE" "${normalized_registry}/${SKILLSPECTOR_IMAGE}:${TAG}"
    else
        set_env_value "$deploy_env" "BACKEND_FULL_IMAGE" "${BACKEND_IMAGE}:${TAG}"
        set_env_value "$deploy_env" "FRONTEND_FULL_IMAGE" "${FRONTEND_IMAGE}:${TAG}"
        set_env_value "$deploy_env" "ORCHESTRATOR_RS_FULL_IMAGE" "${ORCHESTRATOR_RS_IMAGE}:${TAG}"
        set_env_value "$deploy_env" "EGRESS_CONTROLLER_FULL_IMAGE" "${EGRESS_CONTROLLER_IMAGE}:${TAG}"
        set_env_value "$deploy_env" "SKILLSPECTOR_FULL_IMAGE" "${SKILLSPECTOR_IMAGE}:${TAG}"
    fi
}

build_local_compose_images() {
    local deploy_env="$SCRIPT_DIR/.env"

    log_info "构建本地 Compose 核心服务镜像..."
    (
        PUSH=false
        BACKEND_ONLY=false
        FRONTEND_ONLY=false
        ORCHESTRATOR_ONLY=false
        SKILLSPECTOR_ONLY=false
        RUNTIME_ONLY=false
        CLAUDECODE_ONLY=false
        CODEX_ONLY=false
        NATIVE_ONLY=false
        BUILD_ALL=false
        BUILD_BACKEND=true
        BUILD_FRONTEND=true
        BUILD_ORCHESTRATOR=true
        BUILD_SKILLSPECTOR=true
        BUILD_CLAUDECODE=false
        BUILD_CODEX=false
        BUILD_NATIVE=false
        build_all_images
    )

    sync_local_core_image_env "$deploy_env"
}

wait_for_local_redis() {
    local timeout_seconds="${LOCAL_REDIS_READY_TIMEOUT_SECONDS:-60}"
    local elapsed=0

    log_info "等待本地 Redis 就绪..."
    while [ "$elapsed" -lt "$timeout_seconds" ]; do
        if compose_local_env --profile local-redis --profile sandbox exec -T redis redis-cli ping 2>/dev/null | grep -q '^PONG$'; then
            log_success "本地 Redis 已就绪"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_error "本地 Redis 在 ${timeout_seconds}s 内未就绪；请检查 docker compose logs redis"
    exit 1
}

run_local_migrations() {
    (
        cd "$SCRIPT_DIR"
        log_info "启动数据库、Redis、SkillSpector 基础服务..."
        compose_local_env --profile local-redis --profile sandbox up -d --no-build postgres redis skillspector

        wait_for_local_redis

        log_info "运行数据库迁移..."
        compose_local_env --profile local-redis --profile sandbox --profile init run --rm db-init
    )
    log_success "数据库迁移完成"
}

require_single_platform() {
    if echo "$PLATFORMS" | grep -q ","; then
        log_error "本地 Compose 部署一次只能使用单一平台；请使用 --arch amd64 或 --arch arm64"
        exit 1
    fi
}

configure_local_compose_env() {
    local deploy_env="$SCRIPT_DIR/.env"

    ensure_env_file "$deploy_env" "$SCRIPT_DIR/.env.example"
    ensure_env_file "$PROJECT_ROOT/backend/.env" "$PROJECT_ROOT/backend/env.example"
    ensure_env_file "$PROJECT_ROOT/frontend/.env" "$PROJECT_ROOT/frontend/env.example"

    ensure_vault_encryption_key "$deploy_env" "$PROJECT_ROOT/backend/.env"

    set_env_value "$deploy_env" "BASE_IMAGE_REGISTRY" "$BASE_IMAGE_REGISTRY"
    set_env_value "$deploy_env" "RUST_IMAGE" "$RUST_IMAGE"
    set_env_value "$deploy_env" "RUNTIME_IMAGE" "$RUNTIME_IMAGE"
    set_env_value "$deploy_env" "DB_IMAGE" "${DB_IMAGE:-${BASE_IMAGE_REGISTRY}postgres:15}"
    set_env_value "$deploy_env" "REDIS_IMAGE" "${REDIS_IMAGE:-${BASE_IMAGE_REGISTRY}redis:alpine3.22}"
    set_env_value "$deploy_env" "JOYSAFETER_ENVOY_IMAGE" "${JOYSAFETER_ENVOY_IMAGE:-${DOCKER_MIRROR}/envoyproxy/envoy:v1.39.0@sha256:d59f7f5fa10cff6d5892b6c5e7df5c9297ddfb2c3683e33fbfb82da24de4fa66}"
    set_env_value "$deploy_env" "DOCKER_DEFAULT_PLATFORM" "$PLATFORMS"

    ensure_skillspector_source "$deploy_env"

    # detect_docker_socket_path 返回的是“容器内挂载源”，即 daemon 侧路径。VM 型运行时
    # 会返回虚拟机内的 /var/run/docker.sock，它在宿主机上并不存在，所以这里不能再用
    # 宿主机 `[ -S ... ]` 去校验（那正是旧代码在 Colima/Docker Desktop 上失败的原因）。
    local docker_socket="${DOCKER_SOCKET_PATH:-$(detect_docker_socket_path)}"
    if [ -n "$docker_socket" ]; then
        set_env_value "$deploy_env" "DOCKER_SOCKET_PATH" "$docker_socket"
        log_success "Docker socket (容器内挂载源): $docker_socket"
    else
        log_warning "未能自动定位 Docker socket；如 orchestrator-rs 无法创建 sandbox，请设置 deploy/.env 的 DOCKER_SOCKET_PATH"
    fi
}

run_local_compose() {
    require_single_platform
    configure_local_compose_env
    check_local_ports "$SCRIPT_DIR/.env"
    warn_if_sandbox_runtime_image_missing "$SCRIPT_DIR/.env"
    validate_local_compose_config

    log_info "Docker daemon 平台: $PLATFORMS"
    log_info "基础镜像源: $BASE_IMAGE_REGISTRY"
    log_info "第三方镜像代理: $DOCKER_MIRROR"

    build_local_compose_images
    run_local_migrations

    (
        cd "$SCRIPT_DIR"
        log_info "启动本地 Compose 服务..."
        compose_local_env --profile local-redis --profile sandbox up -d --no-build
    )
}

run_local_doctor() {
    require_single_platform
    configure_local_compose_env
    check_local_ports "$SCRIPT_DIR/.env"
    warn_if_sandbox_runtime_image_missing "$SCRIPT_DIR/.env"
    validate_local_compose_config

    log_success "本地部署环境预检完成"
    echo ""
    echo "下一步:"
    echo "  cd deploy"
    echo "  ./deploy.sh local"
}

# ---- 生命周期管理命令 ----
# 统一在 SCRIPT_DIR 下、带本地部署的 profile 集合执行 compose 子命令，
# 保证 down/logs/restart/status 覆盖 redis 与 sandbox 面等 profile 服务，
# 并复用与 local 一致的 env（deploy/.env + LOCAL_* 镜像变量）。
compose_lifecycle() {
    (
        cd "$SCRIPT_DIR"
        compose_local_env --profile local-redis --profile sandbox "$@"
    )
}

run_down() {
    log_info "停止并移除 JoySafeter 本地 Compose 服务（保留数据卷）..."
    compose_lifecycle down "$@"
    log_success "服务已停止；命名数据卷已保留。如需连数据一起清除，请手动执行：cd deploy && docker compose down -v"
}

run_logs() {
    if [ "$#" -gt 0 ]; then
        log_info "跟随服务日志: $*（Ctrl-C 退出）"
    else
        log_info "跟随全部服务日志（Ctrl-C 退出）"
    fi
    compose_lifecycle logs -f "$@"
}

run_restart() {
    if [ "$#" -gt 0 ]; then
        log_info "重启服务: $*"
    else
        log_info "重启全部 JoySafeter 本地 Compose 服务..."
    fi
    compose_lifecycle restart "$@"
    log_success "服务已重启"
}

run_status() {
    compose_lifecycle ps "$@"
}

# ---- Kubernetes (k3s) 部署命令 ----
# deploy.sh 的 k8s 子命令是 K8sProvider 部署方式的统一入口，复用 deploy/k8s/ 下
# 已构建的清单与脚本，避免重复实现：
#   deploy   应用 base 清单、等待滚动、校验 orchestrator sandbox RBAC（委托 k3s-smoke.sh，非破坏性）
#   verify   端到端真实验证：API→worker→orchestrator→k8s Pod→runner（委托 k3s-task-smoke.sh）
#   status   查看 control/sandboxes 两个命名空间的 Pod/Service/NetworkPolicy
#   logs     跟随某个 control-plane Deployment 日志（默认 orchestrator）
#   down     删除 JoySafeter 命名空间（破坏性，需输入 yes 确认）
K8S_DIR="$SCRIPT_DIR/k8s"
KUBECTL_BIN="${KUBECTL:-kubectl}"
K8S_CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
K8S_SANDBOX_NS="${JOYSAFETER_K8S_NAMESPACE:-joysafeter-sandboxes}"

# base 清单固定引用 :latest（含 ConfigMap 里的 JOYSAFETER_IMAGE_* 与各 Deployment），
# 因此本地镜像集也固定用 :latest，与 k3s-smoke.sh 保持一致。
K8S_CORE_IMAGES=(
    "joysafeter-backend:latest"
    "joysafeter-frontend:latest"
    "joysafeter-orchestrator-rs:latest"
    "joysafeter-egress-controller:latest"
    "joysafeter-skillspector:latest"
)
K8S_RUNTIME_IMAGES=(
    "joysafeter-claudecode:latest"
    "joysafeter-codex:latest"
    "joysafeter-native:latest"
)

k8s_usage() {
    cat << EOF
使用方法: $0 k8s <子命令> [选项]

k8s 子命令:
  deploy     应用清单并等待滚动就绪（幂等、非破坏性），自动按集群类型导入本地镜像
  verify     端到端真实验证：创建 user/agent/task，等待 sandbox Pod Ready 并校验 runner 握手
  status     查看 control/sandboxes 命名空间的 Pod、Service、NetworkPolicy
  logs [名]  跟随 control-plane Deployment 日志（默认 joysafeter-orchestrator）
  down       删除 JoySafeter 命名空间（破坏性，需输入 yes 确认）

前置条件:
  - kubectl 已指向目标 k3s 集群（colima / kind / k3d / 生产 k3s 均可）
  - 已构建部署镜像：$0 build --all
  - 集群类型的镜像可达性由 deploy 自动处理（kind: kind load；colima: 共享 Docker 运行时；k3d: 由 k3s-smoke.sh 导入）

示例:
  $0 k8s deploy            # 应用/更新 k8s 栈
  $0 k8s verify            # 端到端真实验证
  $0 k8s status
  $0 k8s logs worker
EOF
}

require_k8s_context() {
    check_command "$KUBECTL_BIN" || {
        log_error "未找到 kubectl；k8s 部署需要 kubectl 指向目标 k3s 集群"
        exit 1
    }
    if ! "$KUBECTL_BIN" cluster-info >/dev/null 2>&1; then
        log_error "kubectl 无法连接集群（context=$("$KUBECTL_BIN" config current-context 2>/dev/null || echo none)）。请先创建/选择 k3s 集群。"
        exit 1
    fi
}

# 打印 "类型:名称"：kind:<cluster> / colima: / k3d:<cluster> / other:<context>
k8s_detect_cluster() {
    local ctx
    ctx="$("$KUBECTL_BIN" config current-context 2>/dev/null || echo "")"
    case "$ctx" in
        kind-*) echo "kind:${ctx#kind-}" ;;
        k3d-*)  echo "k3d:${ctx#k3d-}" ;;
        colima) echo "colima:" ;;
        *)      echo "other:${ctx}" ;;
    esac
}

k8s_warn_missing_core_images() {
    local missing=false img
    for img in "${K8S_CORE_IMAGES[@]}"; do
        if ! docker image inspect "$img" >/dev/null 2>&1; then
            log_warning "本地缺少部署镜像: $img"
            missing=true
        fi
    done
    if [ "$missing" = true ]; then
        log_warning "请先构建镜像：cd $(basename "$SCRIPT_DIR") && ./deploy.sh build --all"
    fi
}

# 按集群类型确保本地镜像对集群可见。
# colima docker+k3s 共享 Docker 运行时，镜像可被 k3s 直接使用（IfNotPresent），无需导入；
# kind 使用独立 containerd，必须 kind load；k3d 的导入交给 k3s-smoke.sh（避免重复实现）。
k8s_load_images() {
    local detected type name img
    detected="$(k8s_detect_cluster)"
    type="${detected%%:*}"
    name="${detected#*:}"
    case "$type" in
        kind)
            if ! command -v kind >/dev/null 2>&1; then
                log_warning "检测到 kind 集群但未找到 kind 命令，跳过镜像导入；请确保节点能拉取所需镜像"
                return
            fi
            for img in "${K8S_CORE_IMAGES[@]}" "${K8S_RUNTIME_IMAGES[@]}"; do
                if docker image inspect "$img" >/dev/null 2>&1; then
                    log_info "导入镜像到 kind 集群($name): $img"
                    kind load docker-image "$img" --name "$name"
                else
                    log_warning "本地缺少镜像，跳过导入: $img"
                fi
            done
            ;;
        colima)
            log_info "colima docker+k3s 共享 Docker 运行时，镜像可被 k3s 直接使用（imagePullPolicy: IfNotPresent），无需导入"
            ;;
        k3d)
            log_info "k3d 集群镜像导入由 k3s-smoke.sh 处理"
            ;;
        *)
            log_warning "未识别的集群类型（context=$name），跳过本地镜像导入；请确保集群可拉取所需镜像"
            ;;
    esac
}

k8s_deploy() {
    require_k8s_context
    log_info "当前 Kubernetes context: $("$KUBECTL_BIN" config current-context)"
    k8s_warn_missing_core_images
    k8s_load_images
    log_info "应用 JoySafeter k8s 清单并等待滚动就绪（委托 k3s-smoke.sh，非破坏性）..."
    KUBECTL="$KUBECTL_BIN" "$K8S_DIR/k3s-smoke.sh"
}

k8s_verify() {
    require_k8s_context
    log_info "端到端真实验证：API→worker→orchestrator→k8s Pod→runner（委托 k3s-task-smoke.sh）..."
    KUBECTL="$KUBECTL_BIN" "$K8S_DIR/k3s-task-smoke.sh" "$@"
}

k8s_status() {
    require_k8s_context
    log_info "control-plane 命名空间: $K8S_CONTROL_NS"
    "$KUBECTL_BIN" -n "$K8S_CONTROL_NS" get pods,svc
    echo ""
    log_info "sandbox 命名空间: $K8S_SANDBOX_NS"
    "$KUBECTL_BIN" -n "$K8S_SANDBOX_NS" get pods -l app.kubernetes.io/name=joysafeter-sandbox 2>/dev/null \
        || log_info "（当前无活动 sandbox Pod）"
    "$KUBECTL_BIN" -n "$K8S_SANDBOX_NS" get networkpolicy 2>/dev/null || true
}

k8s_logs() {
    require_k8s_context
    local target="${1:-joysafeter-orchestrator}"
    log_info "跟随 $K8S_CONTROL_NS/deployment/$target 日志（Ctrl-C 退出）"
    "$KUBECTL_BIN" -n "$K8S_CONTROL_NS" logs -f "deployment/$target" --all-containers=true
}

k8s_down() {
    require_k8s_context
    log_warning "这将删除命名空间 $K8S_CONTROL_NS 与 $K8S_SANDBOX_NS 及其中所有 Pod/Service/PVC/数据（不可恢复）。"
    printf "确认删除？输入 yes 继续: "
    local reply
    read -r reply
    if [ "$reply" != "yes" ]; then
        log_info "已取消。"
        return
    fi
    "$KUBECTL_BIN" delete namespace "$K8S_SANDBOX_NS" "$K8S_CONTROL_NS" --ignore-not-found
    log_success "命名空间已删除。"
}

run_k8s() {
    local sub="${1:-}"
    if [ "$#" -gt 0 ]; then
        shift
    fi
    case "$sub" in
        deploy|up|apply)  k8s_deploy "$@" ;;
        verify|smoke|test) k8s_verify "$@" ;;
        status|ps)        k8s_status "$@" ;;
        logs)             k8s_logs "$@" ;;
        down|delete)      k8s_down "$@" ;;
        ""|help|-h|--help) k8s_usage ;;
        *)
            log_error "未知 k8s 子命令: $sub"
            k8s_usage
            exit 1
            ;;
    esac
}

# 初始化 Docker Buildx
init_buildx() {
    if [ "$USE_BUILDX" = true ]; then
        log_info "检查 Docker Buildx..."

        if ! docker buildx version &> /dev/null; then
            log_warning "Docker Buildx 不可用，回退到传统构建方式（SkillSpector 等需要 Buildx 的镜像将无法构建）"
            suggest_buildx_install
            USE_BUILDX=false
            return
        fi

        if ! docker buildx ls | grep -q "multiarch"; then
            log_info "创建 multiarch builder..."
            docker buildx create --name multiarch --driver docker-container --driver-opt network=host --use 2>/dev/null || \
            docker buildx use multiarch 2>/dev/null || true
        else
            log_info "使用现有的 multiarch builder"
            docker buildx use multiarch 2>/dev/null || true
        fi

        docker buildx inspect --bootstrap &> /dev/null || true

        # 修复 BuildKit 容器的 DNS 解析问题
        # Colima VM 的 systemd-resolved stub (127.0.0.53) 会导致 BuildKit daemon
        # fallback 到公共 DNS (8.8.8.8)，在公司网络下可能被屏蔽，造成 auth.docker.io 超时
        # 解决方案：将 Docker Hub 相关域名的 IP 直接写入 BuildKit 容器的 /etc/hosts
        if docker ps --format '{{.Names}}' | grep -q "buildx_buildkit_multiarch0"; then
            log_info "注入 Docker Hub hosts 解析到 BuildKit 容器..."

            # 用宿主机 DNS 解析 Docker Hub 相关域名
            local dns_server=""
            if [[ "$OSTYPE" == "darwin"* ]]; then
                dns_server=$(scutil --dns | grep 'nameserver\[0\]' | head -1 | awk '{print $3}')
            else
                dns_server=$(grep '^nameserver' /etc/resolv.conf | grep -v '127.0.0' | head -1 | awk '{print $2}')
            fi
            dns_server="${dns_server:-8.8.8.8}"

            local domains="auth.docker.io registry-1.docker.io production.cloudflare.docker.com"
            for domain in $domains; do
                # 检查是否已存在该域名的 hosts 条目
                if docker exec buildx_buildkit_multiarch0 grep -q "$domain" /etc/hosts 2>/dev/null; then
                    continue
                fi

                local ip
                ip=$(dig +short "$domain" @"$dns_server" A 2>/dev/null | grep -E '^[0-9]+\.' | head -1)
                if [ -z "$ip" ]; then
                    ip=$(nslookup "$domain" "$dns_server" 2>/dev/null | awk '/^Address: / && !/127\.0\.0/ && !/'"$dns_server"'/ {print $2}' | head -1)
                fi
                if [ -n "$ip" ]; then
                    docker exec buildx_buildkit_multiarch0 sh -c "echo '$ip $domain' >> /etc/hosts" 2>/dev/null || true
                    log_info "已添加 hosts: $ip $domain"
                fi
            done

            log_success "Docker Hub hosts 解析已注入"
        fi
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
    shift 4
    local extra_build_args=("$@")

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

    # 前端镜像：NEXT_PUBLIC_* 通过 next-runtime-env 在容器启动时注入，无需 build-arg
    if [ "$service" = "前端" ]; then
        # 使用标准多架构 Node 镜像
        local node_version="20-alpine"
        build_args+=("--build-arg" "NODE_VERSION=${node_version}")
        log_info "前端使用 Node 版本: ${node_version}"
    fi

    # 后端镜像使用标准多架构基础镜像
    if [ "$service" = "后端" ]; then
        local python_version="3.12-slim-bookworm"
        build_args+=("--build-arg" "PYTHON_VERSION=${python_version}")
        log_info "后端使用 Python 版本: ${python_version}"
        build_args+=("--build-arg" "GIT_COMMIT_SHA=${GIT_COMMIT_SHA}")
        log_info "后端构建溯源 GIT_COMMIT_SHA: ${GIT_COMMIT_SHA}"
    fi

    if [ "$service" = "Rust Orchestrator" ]; then
        build_args+=("--build-arg" "RUST_IMAGE=${RUST_IMAGE}")
        build_args+=("--build-arg" "RUNTIME_IMAGE=${RUNTIME_IMAGE}")
        build_args+=("--build-arg" "CARGO_REGISTRY_MIRROR=${CARGO_REGISTRY_MIRROR}")
        log_info "Rust builder 镜像: ${RUST_IMAGE}"
        log_info "Rust runtime 镜像: ${RUNTIME_IMAGE}"
        log_info "Cargo registry mirror: ${CARGO_REGISTRY_MIRROR:-disabled}"
    fi

    # 推送前再次检查 BuildKit 容器 DNS 连通性
    if [ "$USE_BUILDX" = true ] && [ "$PUSH" = true ]; then
        if docker ps --format '{{.Names}}' | grep -q "buildx_buildkit_multiarch0"; then
            log_info "推送前检查 BuildKit 容器 DNS 连通性..."
            if ! docker exec buildx_buildkit_multiarch0 sh -c \
                "wget --timeout=5 -q -O /dev/null 'https://auth.docker.io/token?service=registry.docker.io'" 2>/dev/null; then
                log_warning "BuildKit 容器无法访问 auth.docker.io，注入 hosts 解析..."

                # 用宿主机 DNS 解析 Docker Hub 相关域名
                local dns_server=""
                if [[ "$OSTYPE" == "darwin"* ]]; then
                    dns_server=$(scutil --dns | grep 'nameserver\[0\]' | head -1 | awk '{print $3}')
                else
                    dns_server=$(grep '^nameserver' /etc/resolv.conf | grep -v '127.0.0' | head -1 | awk '{print $2}')
                fi
                dns_server="${dns_server:-8.8.8.8}"

                local domains="auth.docker.io registry-1.docker.io production.cloudflare.docker.com"
                local hosts_entries=""
                for domain in $domains; do
                    local ip
                    ip=$(dig +short "$domain" @"$dns_server" A 2>/dev/null | grep -E '^[0-9]+\.' | head -1)
                    if [ -z "$ip" ]; then
                        ip=$(nslookup "$domain" "$dns_server" 2>/dev/null | awk '/^Address: / && !/127\.0\.0/ && !/'"$dns_server"'/ {print $2}' | head -1)
                    fi
                    if [ -n "$ip" ]; then
                        # 检查是否已存在该域名的 hosts 条目
                        if ! docker exec buildx_buildkit_multiarch0 grep -q "$domain" /etc/hosts 2>/dev/null; then
                            hosts_entries="${hosts_entries}${ip} ${domain}\n"
                        fi
                    fi
                done

                if [ -n "$hosts_entries" ]; then
                    docker exec buildx_buildkit_multiarch0 sh -c "printf '${hosts_entries}' >> /etc/hosts"
                    log_success "已注入 Docker Hub hosts 解析"
                    docker exec buildx_buildkit_multiarch0 sh -c "cat /etc/hosts" 2>/dev/null | grep -E "docker" || true
                fi
            else
                log_success "BuildKit 容器 DNS 连通性正常"
            fi
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
            "${extra_build_args[@]}" \
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
                "${extra_build_args[@]}" \
                --load \
                "$context"
        else
            docker buildx build \
                --platform "$PLATFORMS" \
                --file "$dockerfile" \
                --tag "$image_name" \
                "${buildx_args[@]}" \
                "${extra_build_args[@]}" \
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
            --platform "$PLATFORMS" \
            -f "$dockerfile" \
            "${build_args_final[@]}" \
            "${extra_build_args[@]}" \
            -t "$image_name" \
            "$context"
    fi

    log_success "$service 镜像构建完成: $image_name"
}

resolve_skillspector_source_path() {
    local configured="${SKILLSPECTOR_SOURCE_PATH:-}"
    if [ -z "$configured" ] && [ -f "$SCRIPT_DIR/.env" ]; then
        configured="$(read_env_value "$SCRIPT_DIR/.env" "SKILLSPECTOR_SOURCE_PATH")"
    fi

    if [ -n "$configured" ]; then
        if [[ "$configured" = /* ]]; then
            echo "$configured"
        elif [ -d "$SCRIPT_DIR/$configured" ]; then
            (cd "$SCRIPT_DIR" && cd "$configured" && pwd)
        else
            (cd "$PROJECT_ROOT" && cd "$configured" 2>/dev/null && pwd) || echo "$SCRIPT_DIR/$configured"
        fi
        return
    fi

    echo "$DEFAULT_SKILLSPECTOR_SOURCE_PATH"
}

ensure_skillspector_source_for_build() {
    local source_path
    source_path="$(resolve_skillspector_source_path)"

    if skillspector_source_valid "$source_path"; then
        echo "$source_path"
        return
    fi

    if [ -n "${SKILLSPECTOR_SOURCE_PATH:-}" ]; then
        log_error "SkillSpector 源码路径无效（缺少 pyproject.toml 或 src/）: $source_path"
        exit 1
    fi

    clone_skillspector "$DEFAULT_SKILLSPECTOR_SOURCE_PATH"
    echo "$DEFAULT_SKILLSPECTOR_SOURCE_PATH"
}

runtime_dockerfile_for() {
    local engine=$1
    local platform=$2
    case "$engine:$platform" in
        claudecode:linux/amd64) echo "$SCRIPT_DIR/docker/claudecode-amd64.Dockerfile" ;;
        claudecode:linux/arm64) echo "$SCRIPT_DIR/docker/claudecode-arm64.Dockerfile" ;;
        codex:linux/amd64) echo "$SCRIPT_DIR/docker/codex-amd64.Dockerfile" ;;
        codex:linux/arm64) echo "$SCRIPT_DIR/docker/codex-arm64.Dockerfile" ;;
        native:linux/amd64) echo "$SCRIPT_DIR/docker/native-amd64.Dockerfile" ;;
        native:linux/arm64) echo "$SCRIPT_DIR/docker/native-arm64.Dockerfile" ;;
        *)
            log_error "未找到 $engine 在 $platform 的 Dockerfile"
            exit 1
            ;;
    esac
}

runtime_runner_target_for() {
    local platform=$1
    case "$platform" in
        linux/amd64)
            echo "x86_64-unknown-linux-gnu"
            ;;
        linux/arm64)
            echo "aarch64-unknown-linux-gnu"
            ;;
        *)
            log_error "runner 暂不支持平台: $platform"
            exit 1
            ;;
    esac
}

ensure_runtime_runner_binary() {
    local platform=$1
    local target
    target=$(runtime_runner_target_for "$platform")
    local output="$PROJECT_ROOT/target/$target/release/joysafeter-runner"

    # Reuse the existing binary only when it is up to date with the sandbox-runner
    # sources. Otherwise stale binaries silently ship (e.g. missing new engine
    # adapters), so rebuild when sources are newer or FORCE_RUNNER_REBUILD=1.
    if [ -x "$output" ] && [ "${FORCE_RUNNER_REBUILD:-0}" != "1" ]; then
        local newer_src
        newer_src=$(find "$PROJECT_ROOT/sandbox-runner" -type f \
            \( -name '*.rs' -o -name 'Cargo.toml' -o -name 'Cargo.lock' \) \
            -newer "$output" -print -quit 2>/dev/null)
        if [ -z "$newer_src" ]; then
            log_success "runner 二进制已是最新: $output"
            return
        fi
        log_info "检测到 sandbox-runner 源码更新，重新编译 runner"
    fi

    log_info "编译 runner 二进制: $target"
    docker run --rm \
        --platform "$platform" \
        -v "$PROJECT_ROOT:/workspace" \
        -w /workspace/sandbox-runner \
        "$RUST_IMAGE" \
        bash -lc "export PATH=/usr/local/cargo/bin:\$PATH && apt-get update && apt-get install -y --no-install-recommends protobuf-compiler pkg-config && if command -v rustup >/dev/null 2>&1; then rustup target add $target; fi && cargo build --release --target $target -p joysafeter-runner && mkdir -p /workspace/target/$target/release && cp target/$target/release/joysafeter-runner /workspace/target/$target/release/joysafeter-runner"
    chmod +x "$output"
    log_success "runner 二进制编译完成: $output"
}

build_runtime_image() {
    local service=$1
    local engine=$2
    local image_name=$3

    if echo "$PLATFORMS" | grep -q ","; then
        if [ "$PUSH" != true ]; then
            log_error "agent 运行镜像本地构建一次只支持单架构；请指定 --arch amd64/--arch arm64"
            exit 1
        fi
        log_error "agent 运行镜像多架构 push 暂未自动合并 manifest，请分别按架构构建后手动发布"
        exit 1
    fi

    ensure_runtime_runner_binary "$PLATFORMS"

    local dockerfile
    dockerfile=$(runtime_dockerfile_for "$engine" "$PLATFORMS")
    build_image "$service" "$dockerfile" "$PROJECT_ROOT" "$image_name"
}

# 构建所有镜像
build_all_images() {
    local BUILD_BACKEND=${BUILD_BACKEND:-true}
    local BUILD_FRONTEND=${BUILD_FRONTEND:-true}
    local BUILD_ORCHESTRATOR=${BUILD_ORCHESTRATOR:-true}
    local BUILD_EGRESS_CONTROLLER=${BUILD_EGRESS_CONTROLLER:-true}
    local BUILD_SKILLSPECTOR=${BUILD_SKILLSPECTOR:-true}
    local BUILD_CLAUDECODE=${BUILD_CLAUDECODE:-false}
    local BUILD_CODEX=${BUILD_CODEX:-false}
    local BUILD_NATIVE=${BUILD_NATIVE:-false}
    # 检查是否只构建特定服务
    if [ "$BACKEND_ONLY" = true ]; then
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=false
        BUILD_CLAUDECODE=false
        BUILD_CODEX=false
        BUILD_NATIVE=false
    elif [ "$FRONTEND_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=false
        BUILD_CLAUDECODE=false
        BUILD_CODEX=false
        BUILD_NATIVE=false
    elif [ "$ORCHESTRATOR_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=true
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=false
        BUILD_CLAUDECODE=false
        BUILD_CODEX=false
        BUILD_NATIVE=false
    elif [ "$EGRESS_CONTROLLER_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=true
        BUILD_SKILLSPECTOR=false
        BUILD_CLAUDECODE=false
        BUILD_CODEX=false
        BUILD_NATIVE=false
    elif [ "$SKILLSPECTOR_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=true
        BUILD_CLAUDECODE=false
        BUILD_CODEX=false
        BUILD_NATIVE=false
    elif [ "$RUNTIME_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=false
        BUILD_CLAUDECODE=true
        BUILD_CODEX=true
        BUILD_NATIVE=true
    elif [ "$CLAUDECODE_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=false
        BUILD_CLAUDECODE=true
        BUILD_CODEX=false
        BUILD_NATIVE=false
    elif [ "$CODEX_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=false
        BUILD_CLAUDECODE=false
        BUILD_CODEX=true
        BUILD_NATIVE=false
    elif [ "$NATIVE_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=false
        BUILD_CLAUDECODE=false
        BUILD_CODEX=false
        BUILD_NATIVE=true
    elif [ "$INIT_ONLY" = true ]; then
        BUILD_BACKEND=false
        BUILD_FRONTEND=false
        BUILD_ORCHESTRATOR=false
        BUILD_EGRESS_CONTROLLER=false
        BUILD_SKILLSPECTOR=false
    elif [ "$BUILD_ALL" = true ]; then
        BUILD_BACKEND=true
        BUILD_FRONTEND=true
        BUILD_ORCHESTRATOR=true
        BUILD_EGRESS_CONTROLLER=true
        BUILD_SKILLSPECTOR=true
        BUILD_CLAUDECODE=true
        BUILD_CODEX=true
        BUILD_NATIVE=true
    fi

    # 规范化镜像仓库地址
    NORMALIZED_REGISTRY=$(normalize_registry "$REGISTRY")

    # 构建镜像名称
    if [ -n "$NORMALIZED_REGISTRY" ]; then
        BACKEND_FULL_IMAGE="${NORMALIZED_REGISTRY}/${BACKEND_IMAGE}:${TAG}"
        FRONTEND_FULL_IMAGE="${NORMALIZED_REGISTRY}/${FRONTEND_IMAGE}:${TAG}"
        ORCHESTRATOR_RS_FULL_IMAGE="${NORMALIZED_REGISTRY}/${ORCHESTRATOR_RS_IMAGE}:${TAG}"
        EGRESS_CONTROLLER_FULL_IMAGE="${NORMALIZED_REGISTRY}/${EGRESS_CONTROLLER_IMAGE}:${TAG}"
        SKILLSPECTOR_FULL_IMAGE="${NORMALIZED_REGISTRY}/${SKILLSPECTOR_IMAGE}:${TAG}"
        CLAUDECODE_FULL_IMAGE="${NORMALIZED_REGISTRY}/${CLAUDECODE_IMAGE}:${TAG}"
        CODEX_FULL_IMAGE="${NORMALIZED_REGISTRY}/${CODEX_IMAGE}:${TAG}"
        NATIVE_FULL_IMAGE="${NORMALIZED_REGISTRY}/${NATIVE_IMAGE}:${TAG}"
    else
        BACKEND_FULL_IMAGE="${BACKEND_IMAGE}:${TAG}"
        FRONTEND_FULL_IMAGE="${FRONTEND_IMAGE}:${TAG}"
        ORCHESTRATOR_RS_FULL_IMAGE="${ORCHESTRATOR_RS_IMAGE}:${TAG}"
        EGRESS_CONTROLLER_FULL_IMAGE="${EGRESS_CONTROLLER_IMAGE}:${TAG}"
        SKILLSPECTOR_FULL_IMAGE="${SKILLSPECTOR_IMAGE}:${TAG}"
        CLAUDECODE_FULL_IMAGE="${CLAUDECODE_IMAGE}:${TAG}"
        CODEX_FULL_IMAGE="${CODEX_IMAGE}:${TAG}"
        NATIVE_FULL_IMAGE="${NATIVE_IMAGE}:${TAG}"
    fi

    if [ "$BUILD_CLAUDECODE" = true ] || [ "$BUILD_CODEX" = true ] || [ "$BUILD_NATIVE" = true ]; then
        if echo "$PLATFORMS" | grep -q ","; then
            if [ "$PUSH" = true ]; then
                log_error "agent runtime 镜像暂不支持多架构 push；请分别使用 --arch amd64 / --arch arm64 构建发布，避免核心镜像先推送后才失败"
            else
                log_error "agent runtime 镜像本地构建一次只支持单架构；请指定 --arch amd64 或 --arch arm64"
            fi
            exit 1
        fi
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

    if [ "$BUILD_ORCHESTRATOR" = true ]; then
        build_image "Rust Orchestrator" \
            "$SCRIPT_DIR/docker/orchestrator-rs.Dockerfile" \
            "$PROJECT_ROOT" \
            "$ORCHESTRATOR_RS_FULL_IMAGE"
        echo ""
    fi

    if [ "$BUILD_EGRESS_CONTROLLER" = true ]; then
        build_image "Envoy Egress Controller" \
            "$PROJECT_ROOT/egress-controller/Dockerfile" \
            "$PROJECT_ROOT/egress-controller" \
            "$EGRESS_CONTROLLER_FULL_IMAGE"
        echo ""
    fi

    if [ "$BUILD_SKILLSPECTOR" = true ]; then
        if [ "$USE_BUILDX" != true ]; then
            log_error "SkillSpector 镜像构建需要 Docker Buildx，以传入 skillspector named build context"
            suggest_buildx_install
            exit 1
        fi
        local skillspector_source_path
        skillspector_source_path="$(ensure_skillspector_source_for_build)"
        build_image "SkillSpector" \
            "$SCRIPT_DIR/docker/skillspector-service.Dockerfile" \
            "$PROJECT_ROOT/backend/joysafeter_skillspector" \
            "$SKILLSPECTOR_FULL_IMAGE" \
            "--build-context" "skillspector=$skillspector_source_path"
        echo ""
    fi

    if [ "$BUILD_CLAUDECODE" = true ]; then
        build_runtime_image "Claude Code 运行镜像" "claudecode" "$CLAUDECODE_FULL_IMAGE"
        echo ""
    fi

    if [ "$BUILD_CODEX" = true ]; then
        build_runtime_image "Codex 运行镜像" "codex" "$CODEX_FULL_IMAGE"
        echo ""
    fi

    if [ "$BUILD_NATIVE" = true ]; then
        build_runtime_image "Native 运行镜像" "native" "$NATIVE_FULL_IMAGE"
        echo ""
    fi


    log_success "所有镜像构建完成！"
    echo ""
    echo "📦 镜像信息:"
    [ "$BUILD_BACKEND" = true ] && echo "   后端: $BACKEND_FULL_IMAGE"
    [ "$BUILD_FRONTEND" = true ] && echo "   前端: $FRONTEND_FULL_IMAGE"
    [ "$BUILD_ORCHESTRATOR" = true ] && echo "   Rust Orchestrator: $ORCHESTRATOR_RS_FULL_IMAGE"
    [ "$BUILD_EGRESS_CONTROLLER" = true ] && echo "   Envoy Egress Controller: $EGRESS_CONTROLLER_FULL_IMAGE"
    [ "$BUILD_SKILLSPECTOR" = true ] && echo "   SkillSpector: $SKILLSPECTOR_FULL_IMAGE"
    [ "$BUILD_CLAUDECODE" = true ] && echo "   Claude Code 运行镜像: $CLAUDECODE_FULL_IMAGE"
    [ "$BUILD_CODEX" = true ] && echo "   Codex 运行镜像: $CODEX_FULL_IMAGE"
    [ "$BUILD_NATIVE" = true ] && echo "   Native 运行镜像: $NATIVE_FULL_IMAGE"
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

    return 0
}

# 拉取镜像
pull_images() {
    local NORMALIZED_REGISTRY=$(normalize_registry "$REGISTRY")
    local PULL_BACKEND=true
    local PULL_FRONTEND=true
    local PULL_ORCHESTRATOR=true
    local PULL_EGRESS_CONTROLLER=true
    local PULL_SKILLSPECTOR=true
    local PULL_CLAUDECODE=false
    local PULL_CODEX=false
    local PULL_NATIVE=false

    if [ "$BACKEND_ONLY" = true ]; then
        PULL_FRONTEND=false
        PULL_ORCHESTRATOR=false
        PULL_EGRESS_CONTROLLER=false
        PULL_SKILLSPECTOR=false
    elif [ "$FRONTEND_ONLY" = true ]; then
        PULL_BACKEND=false
        PULL_ORCHESTRATOR=false
        PULL_EGRESS_CONTROLLER=false
        PULL_SKILLSPECTOR=false
    elif [ "$ORCHESTRATOR_ONLY" = true ]; then
        PULL_BACKEND=false
        PULL_FRONTEND=false
        PULL_EGRESS_CONTROLLER=false
        PULL_SKILLSPECTOR=false
    elif [ "$EGRESS_CONTROLLER_ONLY" = true ]; then
        PULL_BACKEND=false
        PULL_FRONTEND=false
        PULL_ORCHESTRATOR=false
        PULL_EGRESS_CONTROLLER=true
        PULL_SKILLSPECTOR=false
    elif [ "$SKILLSPECTOR_ONLY" = true ]; then
        PULL_BACKEND=false
        PULL_FRONTEND=false
        PULL_ORCHESTRATOR=false
        PULL_EGRESS_CONTROLLER=false
    elif [ "$RUNTIME_ONLY" = true ]; then
        PULL_BACKEND=false
        PULL_FRONTEND=false
        PULL_ORCHESTRATOR=false
        PULL_EGRESS_CONTROLLER=false
        PULL_SKILLSPECTOR=false
        PULL_CLAUDECODE=true
        PULL_CODEX=true
        PULL_NATIVE=true
    elif [ "$CLAUDECODE_ONLY" = true ]; then
        PULL_BACKEND=false
        PULL_FRONTEND=false
        PULL_ORCHESTRATOR=false
        PULL_EGRESS_CONTROLLER=false
        PULL_SKILLSPECTOR=false
        PULL_CLAUDECODE=true
    elif [ "$CODEX_ONLY" = true ]; then
        PULL_BACKEND=false
        PULL_FRONTEND=false
        PULL_ORCHESTRATOR=false
        PULL_EGRESS_CONTROLLER=false
        PULL_SKILLSPECTOR=false
        PULL_CODEX=true
    elif [ "$NATIVE_ONLY" = true ]; then
        PULL_BACKEND=false
        PULL_FRONTEND=false
        PULL_ORCHESTRATOR=false
        PULL_EGRESS_CONTROLLER=false
        PULL_SKILLSPECTOR=false
        PULL_NATIVE=true
    elif [ "$BUILD_ALL" = true ]; then
        PULL_CLAUDECODE=true
        PULL_CODEX=true
        PULL_NATIVE=true
    fi

    if [ -n "$NORMALIZED_REGISTRY" ]; then
        BACKEND_FULL_IMAGE="${NORMALIZED_REGISTRY}/${BACKEND_IMAGE}:${TAG}"
        FRONTEND_FULL_IMAGE="${NORMALIZED_REGISTRY}/${FRONTEND_IMAGE}:${TAG}"
        ORCHESTRATOR_RS_FULL_IMAGE="${NORMALIZED_REGISTRY}/${ORCHESTRATOR_RS_IMAGE}:${TAG}"
        EGRESS_CONTROLLER_FULL_IMAGE="${NORMALIZED_REGISTRY}/${EGRESS_CONTROLLER_IMAGE}:${TAG}"
        SKILLSPECTOR_FULL_IMAGE="${NORMALIZED_REGISTRY}/${SKILLSPECTOR_IMAGE}:${TAG}"
        CLAUDECODE_FULL_IMAGE="${NORMALIZED_REGISTRY}/${CLAUDECODE_IMAGE}:${TAG}"
        CODEX_FULL_IMAGE="${NORMALIZED_REGISTRY}/${CODEX_IMAGE}:${TAG}"
        NATIVE_FULL_IMAGE="${NORMALIZED_REGISTRY}/${NATIVE_IMAGE}:${TAG}"
    else
        BACKEND_FULL_IMAGE="${BACKEND_IMAGE}:${TAG}"
        FRONTEND_FULL_IMAGE="${FRONTEND_IMAGE}:${TAG}"
        ORCHESTRATOR_RS_FULL_IMAGE="${ORCHESTRATOR_RS_IMAGE}:${TAG}"
        EGRESS_CONTROLLER_FULL_IMAGE="${EGRESS_CONTROLLER_IMAGE}:${TAG}"
        SKILLSPECTOR_FULL_IMAGE="${SKILLSPECTOR_IMAGE}:${TAG}"
        CLAUDECODE_FULL_IMAGE="${CLAUDECODE_IMAGE}:${TAG}"
        CODEX_FULL_IMAGE="${CODEX_IMAGE}:${TAG}"
        NATIVE_FULL_IMAGE="${NATIVE_IMAGE}:${TAG}"
    fi

    pull_one_image() {
        local label="$1"
        local image="$2"
        log_info "拉取${label}镜像: $image"
        if docker pull "$image"; then
            log_success "${label}镜像拉取成功"
        else
            log_error "${label}镜像拉取失败"
            exit 1
        fi
    }

    [ "$PULL_BACKEND" = true ] && pull_one_image "后端" "$BACKEND_FULL_IMAGE"
    [ "$PULL_FRONTEND" = true ] && pull_one_image "前端" "$FRONTEND_FULL_IMAGE"
    [ "$PULL_ORCHESTRATOR" = true ] && pull_one_image "Rust Orchestrator" "$ORCHESTRATOR_RS_FULL_IMAGE"
    [ "$PULL_EGRESS_CONTROLLER" = true ] && pull_one_image "Envoy Egress Controller" "$EGRESS_CONTROLLER_FULL_IMAGE"
    [ "$PULL_SKILLSPECTOR" = true ] && pull_one_image "SkillSpector" "$SKILLSPECTOR_FULL_IMAGE"
    [ "$PULL_CLAUDECODE" = true ] && pull_one_image "Claude Code 运行" "$CLAUDECODE_FULL_IMAGE"
    [ "$PULL_CODEX" = true ] && pull_one_image "Codex 运行" "$CODEX_FULL_IMAGE"
    [ "$PULL_NATIVE" = true ] && pull_one_image "Native 运行" "$NATIVE_FULL_IMAGE"

    local deploy_env="$SCRIPT_DIR/.env"
    ensure_env_file "$deploy_env" "$SCRIPT_DIR/.env.example"
    [ "$PULL_BACKEND" = true ] && set_env_value "$deploy_env" "BACKEND_FULL_IMAGE" "$BACKEND_FULL_IMAGE"
    [ "$PULL_FRONTEND" = true ] && set_env_value "$deploy_env" "FRONTEND_FULL_IMAGE" "$FRONTEND_FULL_IMAGE"
    [ "$PULL_ORCHESTRATOR" = true ] && set_env_value "$deploy_env" "ORCHESTRATOR_RS_FULL_IMAGE" "$ORCHESTRATOR_RS_FULL_IMAGE"
    [ "$PULL_EGRESS_CONTROLLER" = true ] && set_env_value "$deploy_env" "EGRESS_CONTROLLER_FULL_IMAGE" "$EGRESS_CONTROLLER_FULL_IMAGE"
    [ "$PULL_SKILLSPECTOR" = true ] && set_env_value "$deploy_env" "SKILLSPECTOR_FULL_IMAGE" "$SKILLSPECTOR_FULL_IMAGE"
    if [ "$PULL_CLAUDECODE" = true ]; then
        set_env_value "$deploy_env" "JOYSAFETER_SANDBOX_IMAGE" "$CLAUDECODE_FULL_IMAGE"
        set_env_value "$deploy_env" "JOYSAFETER_IMAGE_CLAUDE" "$CLAUDECODE_FULL_IMAGE"
    fi
    [ "$PULL_CODEX" = true ] && set_env_value "$deploy_env" "JOYSAFETER_IMAGE_CODEX" "$CODEX_FULL_IMAGE"
    [ "$PULL_NATIVE" = true ] && set_env_value "$deploy_env" "JOYSAFETER_IMAGE_NATIVE" "$NATIVE_FULL_IMAGE"

    log_success "所有镜像拉取完成！"
    log_info "已同步 deploy/.env 中的镜像变量，后续 compose up --no-build 会使用本次拉取的镜像"
    echo ""
    echo "📦 镜像信息:"
    [ "$PULL_BACKEND" = true ] && echo "   后端: $BACKEND_FULL_IMAGE"
    [ "$PULL_FRONTEND" = true ] && echo "   前端: $FRONTEND_FULL_IMAGE"
    [ "$PULL_ORCHESTRATOR" = true ] && echo "   Rust Orchestrator: $ORCHESTRATOR_RS_FULL_IMAGE"
    [ "$PULL_EGRESS_CONTROLLER" = true ] && echo "   Envoy Egress Controller: $EGRESS_CONTROLLER_FULL_IMAGE"
    [ "$PULL_SKILLSPECTOR" = true ] && echo "   SkillSpector: $SKILLSPECTOR_FULL_IMAGE"
    [ "$PULL_CLAUDECODE" = true ] && echo "   Claude Code 运行镜像: $CLAUDECODE_FULL_IMAGE"
    [ "$PULL_CODEX" = true ] && echo "   Codex 运行镜像: $CODEX_FULL_IMAGE"
    [ "$PULL_NATIVE" = true ] && echo "   Native 运行镜像: $NATIVE_FULL_IMAGE"

    return 0
}

# 主函数
main() {
    local COMMAND=""
    local PUSH=false
    local BACKEND_ONLY=false
    local FRONTEND_ONLY=false
    local ORCHESTRATOR_ONLY=false
    local EGRESS_CONTROLLER_ONLY=false
    local SKILLSPECTOR_ONLY=false
    local RUNTIME_ONLY=false
    local CLAUDECODE_ONLY=false
    local CODEX_ONLY=false
    local NATIVE_ONLY=false
    local BUILD_ALL=false
    local ARCH_LIST_STR=""
    local SERVICE_ARGS=()

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
                local platform=$(convert_arch_to_platform "$2")
                if [ -z "$ARCH_LIST_STR" ]; then
                    ARCH_LIST_STR="$platform"
                else
                    ARCH_LIST_STR="$ARCH_LIST_STR,$platform"
                fi
                shift 2
                ;;
            --api-url)
                # 已废弃：NEXT_PUBLIC_* 通过 next-runtime-env 运行时注入，不再需要 build-arg
                log_info "警告: --api-url 已废弃，NEXT_PUBLIC_API_URL 现在通过容器环境变量运行时注入"
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
            --backend-only)
                BACKEND_ONLY=true
                shift
                ;;
            --frontend-only)
                FRONTEND_ONLY=true
                shift
                ;;
            --orchestrator-only)
                ORCHESTRATOR_ONLY=true
                shift
                ;;
            --egress-controller-only)
                EGRESS_CONTROLLER_ONLY=true
                shift
                ;;
            --skillspector-only)
                SKILLSPECTOR_ONLY=true
                shift
                ;;
            --runtime-only)
                RUNTIME_ONLY=true
                shift
                ;;
            --claudecode-only)
                CLAUDECODE_ONLY=true
                shift
                ;;
            --codex-only)
                CODEX_ONLY=true
                shift
                ;;
            --native-only)
                NATIVE_ONLY=true
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
            doctor|local|build|push|pull|down|logs|restart|status|k8s)
                # 仅当尚未确定命令时，才把该 token 当作命令名。
                # 否则它是已选命令的子命令/服务名（例如 `k8s status`、`logs status`），
                # 必须透传，不能覆盖 COMMAND。
                if [ -z "$COMMAND" ]; then
                    COMMAND="$1"
                    shift
                else
                    case "$COMMAND" in
                        down|logs|restart|status|k8s)
                            SERVICE_ARGS+=("$1")
                            shift
                            ;;
                        *)
                            log_error "未知选项: $1"
                            show_usage
                            exit 1
                            ;;
                    esac
                fi
                ;;
            *)
                # 生命周期命令（down/logs/restart/status）后面可跟服务名或原生
                # compose 选项（如 --tail=100），原样透传给 docker compose。
                # k8s 后面跟子命令（deploy/verify/...）及其参数，原样透传给 run_k8s。
                # COMMAND 为空（尚未识别命令）时落入下方 *)，保持未知选项报错。
                case "$COMMAND" in
                    down|logs|restart|status|k8s)
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

    # 如果没有指定平台且没有设置环境变量，根据命令动态决定
    if [ -z "$PLATFORMS" ] && [ -z "$BUILD_PLATFORMS" ] && [ -z "$ARCH_LIST_STR" ]; then
        if [ "$COMMAND" = "push" ]; then
            PLATFORMS="$DEFAULT_PLATFORMS"
            log_info "未指定架构，推送模式默认使用多架构: $PLATFORMS"
        else
            PLATFORMS=$(get_docker_platform)
            log_info "自动检测 Docker 架构: $PLATFORMS"
        fi
    elif [ -z "$PLATFORMS" ]; then
        PLATFORMS="${BUILD_PLATFORMS:-$DEFAULT_PLATFORMS}"
    fi

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
    # k8s 子命令面向 kubectl 集群，不强制要求本机 Docker：
    # 只读子命令（help/status/logs/down）完全不需要 Docker；deploy 仅在按集群类型
    # 导入本地镜像时才用到 Docker，由 k8s_load_images 自行处理并优雅降级。
    # 其余命令（本地 compose / 镜像构建推送拉取）仍要求 Docker 就绪。
    if [ "$COMMAND" != "k8s" ]; then
        log_info "检查前置条件..."
        check_command docker || exit 1
        check_docker_running
        log_success "前置条件检查通过"
        echo ""
    fi

    # 处理简化架构参数
    if [ -n "$ARCH_LIST_STR" ]; then
        PLATFORMS="$ARCH_LIST_STR"
        log_info "使用指定的架构: $PLATFORMS"
    fi

    # 执行命令
    case "$COMMAND" in
        (build)
            build_all_images
            ;;
        (doctor)
            run_local_doctor
            ;;
        (local)
            run_local_compose
            ;;
        (push)
            PUSH=true
            build_all_images
            ;;
        (pull)
            pull_images
            ;;
        (down)
            run_down "${SERVICE_ARGS[@]}"
            ;;
        (logs)
            run_logs "${SERVICE_ARGS[@]}"
            ;;
        (restart)
            run_restart "${SERVICE_ARGS[@]}"
            ;;
        (status)
            run_status "${SERVICE_ARGS[@]}"
            ;;
        (k8s)
            run_k8s "${SERVICE_ARGS[@]}"
            ;;
        (*)
            log_error "未知命令: $COMMAND"
            show_usage
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
