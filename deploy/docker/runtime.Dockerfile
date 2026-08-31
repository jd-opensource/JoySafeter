ARG RUST_IMAGE="public.ecr.aws/docker/library/rust:1-bookworm"
ARG BASE_IMAGE_REGISTRY="public.ecr.aws/docker/library/"
FROM ${RUST_IMAGE} AS runner-builder

ARG APT_MIRROR_BASE="http://mirrors.ustc.edu.cn"

ARG CARGO_REGISTRIES_CRATES_IO_INDEX="sparse+https://rsproxy.cn/index/"
ENV CARGO_HTTP_TIMEOUT=600 \
    CARGO_HTTP_MULTIPLEXING=false \
    CARGO_NET_RETRY=10

RUN mkdir -p /usr/local/cargo \
    && printf '%s\n' \
        '[source.crates-io]' \
        'replace-with = "runtime-mirror"' \
        '[source.runtime-mirror]' \
        "registry = \"${CARGO_REGISTRIES_CRATES_IO_INDEX}\"" \
        > /usr/local/cargo/config.toml

RUN for sources in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
        [ -f "$sources" ] || continue; \
        sed -i \
            -e "s|https*://deb.debian.org/debian-security|${APT_MIRROR_BASE}/debian-security|g" \
            -e "s|https*://deb.debian.org/debian|${APT_MIRROR_BASE}/debian|g" \
            "$sources"; \
    done \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libssl-dev \
        pkg-config \
        protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY proto ./proto
COPY shared ./shared
COPY sandbox-runner ./sandbox-runner

WORKDIR /src/sandbox-runner
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/src/sandbox-runner/target \
    cargo build --release -p joysafeter-runner \
    && cp target/release/joysafeter-runner /tmp/joysafeter-runner

FROM ${BASE_IMAGE_REGISTRY}ubuntu:22.04 AS runtime-base

ARG APT_MIRROR_BASE="http://mirrors.ustc.edu.cn"

ARG DEBIAN_FRONTEND=noninteractive

RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
        amd64) \
            sed -i "s|http://archive.ubuntu.com/ubuntu|${APT_MIRROR_BASE}/ubuntu|g" /etc/apt/sources.list; \
            sed -i "s|http://security.ubuntu.com/ubuntu|${APT_MIRROR_BASE}/ubuntu|g" /etc/apt/sources.list \
            ;; \
        arm64) \
            sed -i "s|http://ports.ubuntu.com/ubuntu-ports|${APT_MIRROR_BASE}/ubuntu-ports|g" /etc/apt/sources.list \
            ;; \
        *) \
            echo "unsupported runtime architecture: $arch" >&2; \
            exit 1 \
            ;; \
    esac \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates gnupg lsb-release software-properties-common \
        git curl wget jq \
        tar zip unzip \
        openssh-client tmux screen \
        make cmake \
        ripgrep tree htop \
        vim nano \
        sqlite3 postgresql-client redis-tools \
    && rm -rf /var/lib/apt/lists/*

RUN add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 100 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 100 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 \
    && pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir uv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm config set registry https://registry.npmmirror.com \
    && npm install -g yarn pnpm \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash agent \
    && mkdir -p /workspace /mnt/memory \
    && chown -R agent:agent /workspace /mnt/memory

WORKDIR /workspace

FROM runtime-base AS runtime-with-runner

COPY --from=runner-builder /tmp/joysafeter-runner /usr/local/bin/joysafeter-runner
COPY deploy/docker/runtime-credentials.sh /usr/local/lib/joysafeter/runtime-credentials.sh
RUN chmod +x /usr/local/bin/joysafeter-runner \
    && chmod 755 /usr/local/lib/joysafeter/runtime-credentials.sh

FROM runtime-with-runner AS claudecode

ARG CLAUDE_CODE_VERSION="latest"
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" --registry=https://registry.npmmirror.com --no-audit --no-fund

COPY deploy/docker/runner-entrypoint.sh /usr/local/bin/runner-entrypoint.sh
RUN chmod +x /usr/local/bin/runner-entrypoint.sh

USER agent
ENTRYPOINT ["runner-entrypoint.sh"]

FROM runtime-with-runner AS codex

ARG CODEX_VERSION="latest"
RUN npm install -g "@openai/codex@${CODEX_VERSION}" --registry=https://registry.npmmirror.com --no-audit --no-fund

COPY deploy/docker/codex-entrypoint.sh /usr/local/bin/codex-entrypoint.sh
RUN chmod +x /usr/local/bin/codex-entrypoint.sh

USER agent
ENTRYPOINT ["codex-entrypoint.sh"]

FROM runtime-with-runner AS pi

ARG PI_VERSION="0.83.0"
RUN npm install -g "@earendil-works/pi-coding-agent@${PI_VERSION}" --registry=https://registry.npmmirror.com --no-audit --no-fund

COPY deploy/docker/pi-entrypoint.sh /usr/local/bin/pi-entrypoint.sh
RUN chmod +x /usr/local/bin/pi-entrypoint.sh

USER agent
ENTRYPOINT ["pi-entrypoint.sh"]

FROM runtime-with-runner AS native

ENV CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1

COPY deploy/docker/claude-code-best-2.8.4.tgz /tmp/claude-code-best-2.8.4.tgz
RUN npm install -g /tmp/claude-code-best-2.8.4.tgz \
    && rm -f /tmp/claude-code-best-2.8.4.tgz

COPY deploy/docker/runner-entrypoint.sh /usr/local/bin/runner-entrypoint.sh
RUN chmod +x /usr/local/bin/runner-entrypoint.sh

USER agent
ENTRYPOINT ["runner-entrypoint.sh"]
