# Rust orchestrator production image

ARG RUST_IMAGE=public.ecr.aws/docker/library/rust:1-bookworm
ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim

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

COPY proto ./proto
COPY backend/app/joysafeter_orchestrator_rs ./backend/app/joysafeter_orchestrator_rs

WORKDIR /src/backend/app/joysafeter_orchestrator_rs
# aws-sdk-s3 is extremely memory-hungry to compile. Limit parallelism and relax
# optimization settings so the build succeeds in memory-constrained Docker VMs.
# At runtime the binary is ~10-15% larger but functionally identical.
ENV CARGO_BUILD_JOBS=1
ENV CARGO_PROFILE_RELEASE_LTO=false
ENV CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
RUN --mount=type=cache,id=joysafeter-orchestrator-rs-cargo-registry,target=/usr/local/cargo/registry \
    --mount=type=cache,id=joysafeter-orchestrator-rs-cargo-git,target=/usr/local/cargo/git \
    --mount=type=cache,id=joysafeter-orchestrator-rs-target,target=/src/backend/app/joysafeter_orchestrator_rs/target \
    cargo build --release \
    && mkdir -p /out \
    && cp target/release/joysafeter-orchestrator /out/joysafeter-orchestrator

FROM ${RUNTIME_IMAGE} AS runner

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /out/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator

ENV RUST_LOG=info
ENV JOYSAFETER_ENABLED=true
ENV JOYSAFETER_GRPC_HOST=0.0.0.0
ENV JOYSAFETER_GRPC_PORT=9090

EXPOSE 9090

CMD ["joysafeter-orchestrator"]
