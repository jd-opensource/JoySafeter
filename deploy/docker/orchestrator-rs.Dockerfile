# Rust orchestrator production image

ARG RUST_IMAGE=public.ecr.aws/docker/library/rust:1-bookworm
ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim
ARG KUBECTL_VERSION=v1.34.0
ARG CARGO_REGISTRIES_CRATES_IO_INDEX=sparse+https://index.crates.io/
ARG CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse

FROM ${RUST_IMAGE} AS builder

ARG CARGO_REGISTRIES_CRATES_IO_INDEX
ARG CARGO_REGISTRIES_CRATES_IO_PROTOCOL

WORKDIR /src

ENV CARGO_HTTP_TIMEOUT=600 \
    CARGO_HTTP_MULTIPLEXING=false \
    CARGO_NET_RETRY=10 \
    CARGO_REGISTRIES_CRATES_IO_INDEX=${CARGO_REGISTRIES_CRATES_IO_INDEX} \
    CARGO_REGISTRIES_CRATES_IO_PROTOCOL=${CARGO_REGISTRIES_CRATES_IO_PROTOCOL}

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
RUN cargo build --release

FROM ${RUNTIME_IMAGE} AS runner

ARG TARGETARCH
ARG KUBECTL_VERSION

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    case "$arch" in \
      amd64|arm64) ;; \
      *) echo "unsupported kubectl architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl" -o /usr/local/bin/kubectl; \
    chmod +x /usr/local/bin/kubectl; \
    kubectl version --client=true

WORKDIR /app

COPY --from=builder /src/backend/app/joysafeter_orchestrator_rs/target/release/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator
COPY --from=builder /src/backend/app/joysafeter_orchestrator_rs/target/release/joysafeter-egress-gateway /usr/local/bin/joysafeter-egress-gateway

ENV RUST_LOG=info
ENV JOYSAFETER_ENABLED=true
ENV JOYSAFETER_GRPC_HOST=0.0.0.0
ENV JOYSAFETER_GRPC_PORT=9090

EXPOSE 9090 8088

CMD ["joysafeter-orchestrator"]
