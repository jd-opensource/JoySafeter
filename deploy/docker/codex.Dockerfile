ARG BASE_IMAGE_REGISTRY="public.ecr.aws/docker/library/"
ARG RUST_VERSION="1.97.1-bookworm"
ARG NODE_VERSION="22.23.1-bookworm-slim"
ARG PYTHON_VERSION="3.12-slim-bookworm"

FROM ${BASE_IMAGE_REGISTRY}rust:${RUST_VERSION} AS runner-build

ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/sandbox-runner
COPY sandbox-runner/Cargo.toml sandbox-runner/Cargo.lock ./
COPY sandbox-runner/crates ./crates
COPY proto /build/proto
RUN --mount=type=cache,id=joysafeter-cargo-registry,sharing=locked,target=/usr/local/cargo/registry \
    --mount=type=cache,id=joysafeter-runner-target-${TARGETARCH},sharing=locked,target=/build/sandbox-runner/target \
    cargo build --locked --release -p joysafeter-runner \
    && cp target/release/joysafeter-runner /tmp/joysafeter-runner

FROM ${BASE_IMAGE_REGISTRY}node:${NODE_VERSION} AS node-runtime

FROM ${BASE_IMAGE_REGISTRY}python:${PYTHON_VERSION} AS runtime

ARG DEBIAN_FRONTEND=noninteractive
ARG PIP_INDEX_URL="https://pypi.org/simple"
ARG NPM_REGISTRY="https://registry.npmjs.org"
ARG UV_VERSION="0.11.29"
ARG YARN_VERSION="1.22.22"
ARG PNPM_VERSION="10.15.0"

COPY --from=node-runtime /usr/local/ /usr/local/

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git curl wget jq \
    tar zip unzip \
    openssh-client tmux screen \
    make cmake \
    ripgrep tree htop \
    vim nano \
    socat \
    sqlite3 postgresql-client redis-tools \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --root-user-action=ignore --no-cache-dir --index-url "${PIP_INDEX_URL}" "uv==${UV_VERSION}"

ARG CODEX_VERSION="0.146.0"
RUN rm -f /usr/local/bin/yarn /usr/local/bin/yarnpkg /usr/local/bin/pnpm /usr/local/bin/pnpx \
    && npm install -g \
        "yarn@${YARN_VERSION}" \
        "pnpm@${PNPM_VERSION}" \
        "@openai/codex@${CODEX_VERSION}" \
        --registry="${NPM_REGISTRY}" --no-audit --no-fund

RUN useradd -m -s /bin/bash agent \
    && mkdir -p /workspace /mnt/memory \
    && chown -R agent:agent /workspace /mnt/memory

ARG GIT_COMMIT_SHA="unknown"
LABEL org.opencontainers.image.revision="${GIT_COMMIT_SHA}"
ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

COPY --from=runner-build /tmp/joysafeter-runner /usr/local/bin/joysafeter-runner
COPY deploy/docker/codex-entrypoint.sh /usr/local/bin/codex-entrypoint.sh
RUN chmod +x /usr/local/bin/joysafeter-runner /usr/local/bin/codex-entrypoint.sh

WORKDIR /workspace
USER agent
ENTRYPOINT ["codex-entrypoint.sh"]
