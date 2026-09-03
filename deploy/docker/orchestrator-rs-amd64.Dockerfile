# Rust orchestrator runtime image (linux/amd64) using a prebuilt binary.
# The binary is cross-compiled on the host with cargo-zigbuild (see deploy.sh
# ensure_orchestrator_binary), then COPYed in — no in-image compilation.

# Rust orchestrator runtime image using a prebuilt Linux binary.

ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim
# Rust target triple of the prebuilt binary to copy. MUST match the runtime
# image architecture — deploy.sh derives it from the build platform and passes
# it as a build-arg. The default is only for standalone amd64 builds.
ARG TARGET=x86_64-unknown-linux-gnu

FROM ${RUNTIME_IMAGE} AS runner

ARG APT_MIRROR_BASE="http://mirrors.ustc.edu.cn"

RUN for sources in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
        [ -f "$sources" ] || continue; \
        sed -i \
            -e "s|https*://deb.debian.org/debian-security|${APT_MIRROR_BASE}/debian-security|g" \
            -e "s|https*://deb.debian.org/debian|${APT_MIRROR_BASE}/debian|g" \
            "$sources"; \
    done \
    && apt-get update \
    && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG TARGET
COPY target/${TARGET}/release/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator

ENV RUST_LOG=info
ENV JOYSAFETER_GRPC_HOST=0.0.0.0
ENV JOYSAFETER_GRPC_PORT=9090

EXPOSE 9090

CMD ["joysafeter-orchestrator"]
