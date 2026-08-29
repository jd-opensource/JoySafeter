# shellcheck shell=bash
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

# 按 Docker daemon 架构推导华为云 mirror 的 BuildKit 镜像
# 注意 ddn-k8s mirror 的 tag 约定不对称：
#   arm64 -> buildx-stable-1-linuxarm64（带架构后缀）
#   amd64 -> buildx-stable-1（plain tag 即 amd64；该 mirror 无 -linuxamd64 tag）
# buildkit 容器运行在 daemon 上，故取 daemon 架构
huawei_buildkit_image() {
    local base="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/moby/buildkit"
    case "$(get_docker_platform)" in
        linux/arm64) echo "$base:buildx-stable-1-linuxarm64" ;;
        *)           echo "$base:buildx-stable-1" ;;
    esac
}
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

unset_env_value() {
    local file="$1"
    local key="$2"
    local tmp="${file}.tmp"

    awk -v key="$key" '$0 !~ "^" key "=" { print }' "$file" > "$tmp"
    mv "$tmp" "$file"
}

validate_local_database_config() {
    local deploy_env="$1"
    local database_url url_rest authority host_port host

    database_url="$(read_env_value "$deploy_env" "DATABASE_URL")"
    database_url="${database_url#"${database_url%%[![:space:]]*}"}"
    database_url="${database_url%"${database_url##*[![:space:]]}"}"
    [ -z "$database_url" ] && return 0

    case "$database_url" in
        postgres://*|postgresql://*|postgresql+asyncpg://*) ;;
        *)
            log_error "本地 Compose 不支持 DATABASE_URL；请统一配置 POSTGRES_HOST、POSTGRES_PORT、POSTGRES_USER、POSTGRES_PASSWORD 和 POSTGRES_DB"
            return 1
            ;;
    esac

    url_rest="${database_url#*://}"
    authority="${url_rest%%/*}"
    host_port="${authority##*@}"
    host="${host_port%%:*}"
    if [ "$host" = "postgres" ]; then
        unset_env_value "$deploy_env" "DATABASE_URL"
        log_warning "检测到旧版内置 PostgreSQL DATABASE_URL，已移除；本地 Compose 统一使用 POSTGRES_* 配置"
        return 0
    fi

    log_error "本地 Compose 不接受外部 DATABASE_URL；请统一改用 POSTGRES_HOST、POSTGRES_PORT、POSTGRES_USER、POSTGRES_PASSWORD 和 POSTGRES_DB"
    return 1
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
