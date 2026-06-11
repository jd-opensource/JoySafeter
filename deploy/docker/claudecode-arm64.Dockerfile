FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/ubuntu:22.04-linuxarm64 AS base

ARG DEBIAN_FRONTEND=noninteractive

RUN sed -i 's|http://ports.ubuntu.com/ubuntu-ports|http://mirrors.ustc.edu.cn/ubuntu-ports|g' /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gnupg lsb-release software-properties-common \
    git curl wget jq \
    tar zip unzip \
    openssh-client tmux screen \
    make cmake \
    ripgrep tree htop \
    vim nano \
    socat \
    sqlite3 postgresql-client redis-tools \
    && rm -rf /var/lib/apt/lists/*

RUN add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3.12-dev \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 100 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 100 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 \
    && pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir uv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm config set registry https://registry.npmmirror.com \
    && npm install -g yarn pnpm \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash agent \
    && mkdir -p /workspace /mnt/memory \
    && chown -R agent:agent /workspace /mnt/memory

WORKDIR /workspace

FROM base AS claudecode

RUN npm install -g @anthropic-ai/claude-code@latest

COPY target/aarch64-unknown-linux-musl/release/joysafeter-runner /usr/local/bin/joysafeter-runner
RUN chmod +x /usr/local/bin/joysafeter-runner

USER agent
ENTRYPOINT ["joysafeter-runner"]
