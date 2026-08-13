# Rust orchestrator — JD internal build with zigbuild cross-compilation
# Includes jd-identity feature for agent identity protocol support

ARG RUST_IMAGE=public.ecr.aws/docker/library/rust:1-bookworm
ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim
ARG TARGET=x86_64-unknown-linux-gnu

FROM ${RUST_IMAGE} AS builder

WORKDIR /src

ENV CARGO_HTTP_TIMEOUT=600 \
    CARGO_HTTP_MULTIPLEXING=false \
    CARGO_NET_RETRY=10

RUN apt-get update && apt-get install -y \
    protobuf-compiler \
    pkg-config \
    libssl-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install cargo-zigbuild for cross-compilation
RUN cargo install cargo-zigbuild \
    && curl -sSf https://ziglang.org/download/0.13.0/zig-linux-x86_64-0.13.0.tar.xz \
    | tar -xJ -C /usr/local \
    && ln -s /usr/local/zig-linux-x86_64-0.13.0/zig /usr/local/bin/zig

ARG TARGET
RUN rustup target add ${TARGET}

COPY proto ./proto
COPY backend/app/joysafeter_orchestrator_rs ./backend/app/joysafeter_orchestrator_rs

WORKDIR /src/backend/app/joysafeter_orchestrator_rs

# Build with jd-identity feature and zigbuild
ENV CARGO_BUILD_JOBS=2
RUN cargo zigbuild --release --features jd-identity --target ${TARGET}

FROM ${RUNTIME_IMAGE} AS runner

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG TARGET
COPY --from=builder /src/backend/app/joysafeter_orchestrator_rs/target/${TARGET}/release/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator

ENV RUST_LOG=info,jd_agent_identity=debug
ENV JOYSAFETER_ENABLED=true
ENV JOYSAFETER_GRPC_HOST=0.0.0.0
ENV JOYSAFETER_GRPC_PORT=9090

EXPOSE 9090

CMD ["joysafeter-orchestrator"]
