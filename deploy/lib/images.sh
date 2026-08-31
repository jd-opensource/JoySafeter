# shellcheck shell=bash
init_buildx() {
    if [ "$USE_BUILDX" = true ]; then
        log_info "检查 Docker Buildx..."

        if ! docker buildx version &> /dev/null; then
            log_warning "Docker Buildx 不可用，回退到传统构建方式（SkillSpector 等需要 Buildx 的镜像将无法构建）"
            suggest_buildx_install
            USE_BUILDX=false
            return
        fi

        # 组装 builder 创建参数；指定 BUILDKIT_IMAGE 时用它启动 buildkit 容器，
        # 避免无法访问 docker.io 的网络下回退拉取 docker.io/moby/buildkit 而超时
        local create_opts=(--name multiarch --driver docker-container --driver-opt network=host)
        if [ -n "$BUILDKIT_IMAGE" ]; then
            create_opts+=(--driver-opt "image=$BUILDKIT_IMAGE")
        fi

        if ! docker buildx inspect multiarch >/dev/null 2>&1; then
            log_info "创建 multiarch builder..."
            [ -n "$BUILDKIT_IMAGE" ] && log_info "使用 BuildKit 镜像: $BUILDKIT_IMAGE"
            docker buildx create "${create_opts[@]}" --use 2>/dev/null || \
            docker buildx use multiarch 2>/dev/null || true
        elif [ -n "$BUILDKIT_IMAGE" ] && \
             ! docker buildx inspect multiarch 2>/dev/null | grep -qF "image=\"$BUILDKIT_IMAGE\""; then
            # 已存在 builder 但未使用指定的 BUILDKIT_IMAGE：重建，否则启动仍会回退到 docker.io
            log_warning "现有 multiarch builder 未使用指定的 BuildKit 镜像，重建中..."
            log_info "使用 BuildKit 镜像: $BUILDKIT_IMAGE"
            docker buildx rm multiarch 2>/dev/null || true
            docker buildx create "${create_opts[@]}" --use 2>/dev/null || \
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

docker_arch_for_platform() {
    case "$1" in
        linux/amd64) printf '%s\n' amd64 ;;
        linux/arm64) printf '%s\n' arm64 ;;
        linux/arm/v7) printf '%s\n' arm ;;
        *)
            log_error "无法验证未知目标平台的镜像架构: $1"
            return 1
            ;;
    esac
}

verify_local_image_platform() {
    local image_name=$1 platform=$2 expected_arch actual_arch
    expected_arch="$(docker_arch_for_platform "$platform")" || return 1
    actual_arch="$(docker image inspect --format '{{.Architecture}}' "$image_name")" || {
        log_error "无法检查构建镜像架构: $image_name"
        return 1
    }
    if [ "$actual_arch" != "$expected_arch" ]; then
        log_error "镜像架构不匹配: $image_name 实际=$actual_arch 期望=$expected_arch ($platform)"
        return 1
    fi
    log_success "镜像架构已验证: $image_name -> $actual_arch"
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
    if [ -n "$APT_MIRROR_BASE" ]; then
        build_args+=("--build-arg" "APT_MIRROR_BASE=$APT_MIRROR_BASE")
        log_info "使用 APT 软件源: $APT_MIRROR_BASE"
    fi
    if [ -n "$ALPINE_MIRROR_BASE" ]; then
        build_args+=("--build-arg" "ALPINE_MIRROR_BASE=$ALPINE_MIRROR_BASE")
        log_info "使用 Alpine 软件源: $ALPINE_MIRROR_BASE"
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
        # 透传目标 target triple，让 orchestrator-rs-binary.Dockerfile COPY 对应
        # 架构的预编译二进制（而非写死 x86_64）；$PLATFORMS 此处已是单一平台。
        build_args+=("--build-arg" "TARGET=$(rust_target_for_platform "$PLATFORMS")")
        log_info "Rust builder 镜像: ${RUST_IMAGE}"
        log_info "Rust runtime 镜像: ${RUNTIME_IMAGE}"
    fi

    # 推送前再次检查 BuildKit 容器 DNS 连通性
    if [ "${PLAIN_IMAGE:-false}" = true ]; then
        local plain_build_args=(${build_args[@]+"${build_args[@]}"})
        if [ "$NO_CACHE" = true ]; then
            plain_build_args+=("--no-cache")
        fi
        docker build \
            --provenance=false \
            --platform "$PLATFORMS" \
            --file "$dockerfile" \
            ${plain_build_args[@]+"${plain_build_args[@]}"} \
            ${extra_build_args[@]+"${extra_build_args[@]}"} \
            --tag "$image_name" \
            "$context"
        docker push "$image_name"
    elif [ "$USE_BUILDX" = true ] && [ "$PUSH" = true ]; then
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
        local buildx_args=(${build_args[@]+"${build_args[@]}"})
        if [ "$NO_CACHE" = true ]; then
            buildx_args+=("--no-cache")
        fi
        docker buildx build \
            --platform "$PLATFORMS" \
            --file "$dockerfile" \
            --tag "$image_name" \
            ${buildx_args[@]+"${buildx_args[@]}"} \
            ${extra_build_args[@]+"${extra_build_args[@]}"} \
            --push \
            "$context"
    elif [ "$USE_BUILDX" = true ]; then
        if [ "$NO_CACHE" = true ]; then
            log_info "使用 Docker Buildx 构建多架构镜像（本地，无缓存）..."
        else
            log_info "使用 Docker Buildx 构建多架构镜像（本地，使用缓存）..."
        fi
        local buildx_args=(${build_args[@]+"${build_args[@]}"})
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
                ${buildx_args[@]+"${buildx_args[@]}"} \
                ${extra_build_args[@]+"${extra_build_args[@]}"} \
                --load \
                "$context"
        else
            docker buildx build \
                --platform "$PLATFORMS" \
                --file "$dockerfile" \
                --tag "$image_name" \
                ${buildx_args[@]+"${buildx_args[@]}"} \
                ${extra_build_args[@]+"${extra_build_args[@]}"} \
                --load \
                "$context"
        fi
    else
        if [ "$NO_CACHE" = true ]; then
            log_info "使用传统方式构建单架构镜像（无缓存）..."
        else
            log_info "使用传统方式构建单架构镜像（使用缓存）..."
        fi
        local build_args_final=(${build_args[@]+"${build_args[@]}"})
        if [ "$NO_CACHE" = true ]; then
            build_args_final+=("--no-cache")
        fi
        docker build \
            --platform "$PLATFORMS" \
            -f "$dockerfile" \
            ${build_args_final[@]+"${build_args_final[@]}"} \
            ${extra_build_args[@]+"${extra_build_args[@]}"} \
            -t "$image_name" \
            "$context"
    fi

    if [ "$PUSH" != true ] || [ "${PLAIN_IMAGE:-false}" = true ]; then
        local loaded_platform="$PLATFORMS"
        case "$loaded_platform" in
            *,*) loaded_platform="${loaded_platform%%,*}" ;;
        esac
        verify_local_image_platform "$image_name" "$loaded_platform"
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

orchestrator_dockerfile_for() {
    local platform=$1 arch record pattern
    case "$platform" in
        linux/amd64) arch=amd64 ;;
        linux/arm64) arch=arm64 ;;
        *)
            log_error "未找到 Rust Orchestrator 在 $platform 的 Dockerfile"
            exit 1
            ;;
    esac
    record="$(image_component_source_record orchestrator)" || return 1
    IFS='|' read -r _ _ _ _ _ _ pattern _ <<< "$record"
    resolve_component_path "${pattern/\{0\}/$arch}"
}

rust_target_for_platform() {
    local platform=$1
    case "$platform" in
        linux/amd64)
            echo "x86_64-unknown-linux-gnu"
            ;;
        linux/arm64)
            echo "aarch64-unknown-linux-gnu"
            ;;
        *)
            log_error "Rust 二进制暂不支持平台: $platform"
            exit 1
            ;;
    esac
}

# 读取 ELF 文件 e_machine 字段（小端偏移 18 的低字节），映射为架构前缀
# （x86_64 / aarch64），与 rust target triple 的前缀（${target%%-*}）比较。
# 用于跨架构复用磁盘上的旧编译产物前做架构校验，避免把 amd64 二进制塞进
# arm64 镜像（反之亦然）导致运行时 rosetta/exec 失败。无法判定时回显 unknown。
elf_binary_arch() {
    local file=$1
    [ -f "$file" ] || { echo "missing"; return; }
    local byte
    byte=$(od -An -tx1 -j 18 -N 1 "$file" 2>/dev/null | tr -d '[:space:]')
    case "$byte" in
        3e) echo "x86_64" ;;
        b7) echo "aarch64" ;;
        *) echo "unknown" ;;
    esac
}

# Cross-compile the orchestrator binary on the host with cargo-zigbuild.
#
# The orchestrator remains host-cross-compiled because its build does not include
# Linux-host-only build scripts. The sandbox runner must not use this path: its
# fuser dependency requires its build script itself to execute on Linux.
#
# Args: <rust_target_triple>
# Output lands in the orchestrator crate's target directory.
zigbuild_orchestrator_binary() {
    local target=$1
    local crate_dir="$PROJECT_ROOT/backend/app/joysafeter_orchestrator_rs"

    for tool in zig cargo-zigbuild protoc; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            log_error "cargo zigbuild 需要 '$tool'，但未找到。请先安装 (brew install zig protobuf && cargo install cargo-zigbuild)"
            exit 1
        fi
    done

    ( cd "$crate_dir" \
        && rustup target add "$target" >/dev/null 2>&1 || true \
        && PROTOC="$(command -v protoc)" cargo zigbuild --release --target "$target" \
            -p joysafeter-orchestrator --features jd-identity )
}

ensure_orchestrator_binary() {
    local platform=$1
    local target
    target=$(rust_target_for_platform "$platform")
    local output="$PROJECT_ROOT/target/$target/release/joysafeter-orchestrator"

    if [ -x "$output" ] && [ "${FORCE_ORCHESTRATOR_REBUILD:-0}" != "1" ]; then
        # 先校验架构：磁盘产物架构必须匹配目标 target，否则强制重编。仅靠
        # find -newer 时间戳不足以发现“旧产物是别的架构”这种跨架构复用。
        local disk_arch expected_arch
        disk_arch=$(elf_binary_arch "$output")
        expected_arch="${target%%-*}"
        if [ "$disk_arch" != "$expected_arch" ]; then
            log_warning "现有 orchestrator-rs 二进制架构为 ${disk_arch}，与目标 ${expected_arch}(${target}) 不符，强制重新编译"
        else
            local newer_src
            newer_src=$(find "$PROJECT_ROOT/backend/app/joysafeter_orchestrator_rs" "$PROJECT_ROOT/proto" -type f \
                \( -name '*.rs' -o -name 'Cargo.toml' -o -name 'Cargo.lock' -o -name '*.proto' \) \
                -newer "$output" -print -quit 2>/dev/null)
            if [ -z "$newer_src" ]; then
                log_success "orchestrator-rs 二进制已是最新: $output"
                return
            fi
            log_info "检测到 orchestrator-rs 源码更新，重新编译二进制"
        fi
    fi

    log_info "编译 orchestrator-rs 二进制: $target (cargo zigbuild, --features jd-identity)"
    zigbuild_orchestrator_binary "$target"
    mkdir -p "$PROJECT_ROOT/target/$target/release"
    cp "$PROJECT_ROOT/backend/app/joysafeter_orchestrator_rs/target/$target/release/joysafeter-orchestrator" "$output"
    chmod +x "$output"
    log_success "orchestrator-rs 二进制编译完成: $output"
}

build_runtime_image() {
    local service=$1
    local engine=$2
    local image_name=$3
    if [ -z "$engine" ] || [ "$engine" = - ]; then
        log_error "Runtime 组件缺少 Docker target: $service"
        return 1
    fi

    build_image "$service" \
        "$SCRIPT_DIR/docker/runtime.Dockerfile" \
        "$PROJECT_ROOT" \
        "$image_name" \
        --target "$engine" \
        --build-arg "RUST_IMAGE=$RUST_IMAGE" \
        --build-arg "CARGO_REGISTRIES_CRATES_IO_INDEX=$CARGO_REGISTRIES_CRATES_IO_INDEX"
}

# 镜像组件的唯一声明源。CLI、Compose 镜像同步和 CI matrix 均从该文件读取。
IMAGE_COMPONENT_SELECTION=""
IMAGE_COMPONENT_REGISTRY_FILE="$SCRIPT_DIR/image-components.tsv"

image_component_source_registry() {
    [ -f "$IMAGE_COMPONENT_REGISTRY_FILE" ] || {
        log_error "镜像组件 Registry 不存在: $IMAGE_COMPONENT_REGISTRY_FILE"
        return 1
    }
    awk -F '\t' 'BEGIN { OFS="|" } !/^#/ && NF { print $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13 }' \
        "$IMAGE_COMPONENT_REGISTRY_FILE"
}

image_component_source_record() {
    local requested=$1 record
    while IFS= read -r record; do
        case "$record" in
            "$requested|"*) printf '%s\n' "$record"; return 0 ;;
        esac
    done < <(image_component_source_registry)
    return 1
}

resolve_component_path() {
    case "$1" in
        -) printf '%s\n' - ;;
        /*) printf '%s\n' "$1" ;;
        .) printf '%s\n' "$PROJECT_ROOT" ;;
        *) printf '%s/%s\n' "$PROJECT_ROOT" "$1" ;;
    esac
}

component_image_name() {
    local component=$1 record image_env default_image configured
    record="$(image_component_source_record "$component")" || return 1
    IFS='|' read -r _ _ _ _ image_env default_image _ <<< "$record"
    eval "configured=\${${image_env}:-}"
    printf '%s\n' "${configured:-$default_image}"
}

image_component_registry() {
    local record component group label handler dockerfile context target env_keys image_name
    while IFS= read -r record; do
        IFS='|' read -r component group label handler _ _ dockerfile context target env_keys _ _ _ <<< "$record"
        image_name="$(component_image_name "$component")" || return 1
        dockerfile="$(resolve_component_path "$dockerfile")"
        context="$(resolve_component_path "$context")"
        printf '%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
            "$component" "$group" "$label" "$handler" "$image_name" \
            "$dockerfile" "$context" "$target" "$env_keys"
    done < <(image_component_source_registry)
}

image_component_ci_path() {
    case "$1" in
        -) printf '' ;;
        .) printf '.' ;;
        ./*) printf '%s' "$1" ;;
        *) printf './%s' "$1" ;;
    esac
}

image_component_ci_matrix() {
    local requested_family=$1 first=true record component handler default_image dockerfile context target family build_contexts skillspector
    case "$requested_family" in
        all|container|orchestrator) ;;
        *) log_error "未知 CI 镜像族: $requested_family（可选: all, container, orchestrator）"; return 1 ;;
    esac

    printf '{"include":['
    while IFS= read -r record; do
        IFS='|' read -r component _ _ handler _ default_image dockerfile context target _ family build_contexts _ <<< "$record"
        if [ "$requested_family" != all ] && [ "$family" != "$requested_family" ]; then
            continue
        fi
        [ "$first" = true ] || printf ','
        first=false
        [ "$target" = - ] && target=""
        [ "$build_contexts" = - ] && build_contexts=""
        skillspector=false
        [ "$handler" = skillspector ] && skillspector=true
        printf '{"component":"%s","name":"%s","context":"%s","dockerfile":"%s","target":"%s","skillspector":%s,"build_contexts":"%s"}' \
            "$component" "$default_image" "$(image_component_ci_path "$context")" \
            "$(image_component_ci_path "$dockerfile")" "$target" "$skillspector" "$build_contexts"
    done < <(image_component_source_registry)
    printf ']}\n'
}

print_image_component_registry() {
    local requested_family=$1 format=$2 record component group label handler image_env default_image dockerfile context target env_keys family build_contexts helm_key
    if [ "$format" = github ]; then
        image_component_ci_matrix "$requested_family"
        return
    fi
    [ "$format" = table ] || { log_error "未知 Registry 输出格式: $format（可选: table, github）"; return 1; }
    printf 'COMPONENT\tGROUP\tCI_FAMILY\tHANDLER\tIMAGE\tDOCKERFILE\tTARGET\tHELM_KEY\n'
    while IFS= read -r record; do
        IFS='|' read -r component group label handler image_env default_image dockerfile context target env_keys family build_contexts helm_key <<< "$record"
        if [ "$requested_family" != all ] && [ "$family" != "$requested_family" ]; then
            continue
        fi
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$component" "$group" "$family" "$handler" "$(component_image_name "$component")" "$dockerfile" "$target" "$helm_key"
    done < <(image_component_source_registry)
}

print_image_component_options() {
    image_component_source_registry | cut -d'|' -f1 | paste -sd/ -
}

print_image_component_environment() {
    local record image_env default_image
    while IFS= read -r record; do
        IFS='|' read -r _ _ _ _ image_env default_image _ <<< "$record"
        printf '  %-24s 镜像名称（默认: %s）\n' "$image_env" "$default_image"
    done < <(image_component_source_registry)
}

image_component_record() {
    local requested=$1 record
    while IFS= read -r record; do
        case "$record" in
            "$requested|"*) printf '%s\n' "$record"; return 0 ;;
        esac
    done < <(image_component_registry)
    return 1
}

select_image_component() {
    local component=$1 selected
    if ! image_component_record "$component" >/dev/null; then
        log_error "未知镜像组件: $component"
        log_error "可选组件: $(image_component_registry | cut -d'|' -f1 | tr '\n' ' ')"
        return 1
    fi
    for selected in $IMAGE_COMPONENT_SELECTION; do
        [ "$selected" = "$component" ] && return 0
    done
    IMAGE_COMPONENT_SELECTION="${IMAGE_COMPONENT_SELECTION:+$IMAGE_COMPONENT_SELECTION }$component"
}

select_image_group() {
    local requested_group=$1 component group
    case "$requested_group" in
        core|runtime|all) ;;
        *)
            log_error "未知镜像分组: $requested_group（可选: core, runtime, all）"
            return 1
            ;;
    esac
    while IFS='|' read -r component group _; do
        if [ "$requested_group" = all ] || [ "$group" = "$requested_group" ]; then
            select_image_component "$component"
        fi
    done < <(image_component_registry)
}

selected_image_components() {
    local component
    if [ -z "$IMAGE_COMPONENT_SELECTION" ]; then
        select_image_group core
    fi
    for component in $IMAGE_COMPONENT_SELECTION; do
        printf '%s\n' "$component"
    done
}

component_image_ref() {
    local component=$1 record image_name normalized_registry
    record="$(image_component_record "$component")" || return 1
    IFS='|' read -r _ _ _ _ image_name _ <<< "$record"
    normalized_registry="$(normalize_registry "$REGISTRY")"
    if [ -n "$normalized_registry" ]; then
        printf '%s/%s:%s\n' "$normalized_registry" "$image_name" "$TAG"
    else
        printf '%s:%s\n' "$image_name" "$TAG"
    fi
}

build_component() {
    local component=$1 record group label handler image_name dockerfile context target env_keys image_ref
    record="$(image_component_record "$component")" || return 1
    IFS='|' read -r component group label handler image_name dockerfile context target env_keys <<< "$record"
    image_ref="$(component_image_ref "$component")"

    case "$handler" in
        standard)
            build_image "$label" "$dockerfile" "$context" "$image_ref"
            ;;
        orchestrator)
            if echo "$PLATFORMS" | grep -q ","; then
                log_error "Rust Orchestrator 快速本地二进制打包一次只支持单架构；请指定 --arch amd64/--arch arm64"
                return 1
            fi
            ensure_orchestrator_binary "$PLATFORMS"
            build_image "$label" "$(orchestrator_dockerfile_for "$PLATFORMS")" "$context" "$image_ref"
            ;;
        skillspector)
            if [ "$USE_BUILDX" != true ]; then
                log_error "SkillSpector 镜像构建需要 Docker Buildx，以传入 skillspector named build context"
                suggest_buildx_install
                return 1
            fi
            local skillspector_source_path
            skillspector_source_path="$(ensure_skillspector_source_for_build)"
            build_image "$label" "$dockerfile" "$context" "$image_ref" \
                --build-context "skillspector=$skillspector_source_path"
            ;;
        runtime)
            build_runtime_image "$label" "$target" "$image_ref"
            ;;
        *)
            log_error "镜像组件 '$component' 使用未知构建 handler: $handler"
            return 1
            ;;
    esac
}

sync_component_image_env() {
    local component=$1 deploy_env=$2 record env_keys image_ref env_key old_ifs
    record="$(image_component_record "$component")" || return 1
    IFS='|' read -r _ _ _ _ _ _ _ _ env_keys <<< "$record"
    image_ref="$(component_image_ref "$component")"
    [ "$env_keys" = "-" ] && return 0
    old_ifs=$IFS
    IFS=','
    for env_key in $env_keys; do
        set_env_value "$deploy_env" "$env_key" "$image_ref"
    done
    IFS=$old_ifs
}

sync_selected_image_env() {
    local deploy_env=$1 component
    ensure_env_file "$deploy_env" "$SCRIPT_DIR/.env.example"
    while IFS= read -r component; do
        sync_component_image_env "$component" "$deploy_env"
    done < <(selected_image_components)
}

print_selected_image_refs() {
    local component record label
    while IFS= read -r component; do
        record="$(image_component_record "$component")"
        IFS='|' read -r _ _ label _ <<< "$record"
        printf '   %s: %s\n' "$label" "$(component_image_ref "$component")"
    done < <(selected_image_components)
}

build_selected_images() {
    local component

    if [ "$USE_BUILDX" = true ]; then
        init_buildx
        echo ""
    fi
    if [ "$USE_BUILDX" = true ] && [ "$PUSH" = true ] && [ -z "$REGISTRY" ]; then
        log_error "使用 Buildx 构建多架构镜像并推送时，必须指定镜像仓库（--registry）"
        return 1
    fi

    while IFS= read -r component; do
        build_component "$component"
        echo ""
    done < <(selected_image_components)

    log_success "所选镜像构建完成！"
    echo ""
    echo "📦 镜像信息:"
    print_selected_image_refs
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

pull_component() {
    local component=$1 record label image_ref
    record="$(image_component_record "$component")" || return 1
    IFS='|' read -r _ _ label _ <<< "$record"
    image_ref="$(component_image_ref "$component")"
    log_info "拉取${label}镜像: $image_ref"
    docker pull "$image_ref"
    log_success "${label}镜像拉取成功"
}

pull_selected_images() {
    local component deploy_env="$SCRIPT_DIR/.env"
    while IFS= read -r component; do
        pull_component "$component"
    done < <(selected_image_components)
    sync_selected_image_env "$deploy_env"

    log_success "所选镜像拉取完成！"
    log_info "已同步 deploy/.env 中的镜像变量，后续 compose up --no-build 会使用本次拉取的镜像"
    echo ""
    echo "📦 镜像信息:"
    print_selected_image_refs
}
