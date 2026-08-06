# Rust orchestrator runtime image using a prebuilt Linux binary.

ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim

FROM ${RUNTIME_IMAGE} AS runner

# Rust target triple of the prebuilt binary. deploy.sh derives this from the
# requested --arch (x86_64-unknown-linux-gnu for amd64, aarch64-unknown-linux-gnu
# for arm64) so a single Dockerfile serves both architectures.
ARG RUST_TARGET=x86_64-unknown-linux-gnu

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY target/${RUST_TARGET}/release/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator

ENV RUST_LOG=info
ENV JOYSAFETER_ENABLED=true
ENV JOYSAFETER_GRPC_HOST=0.0.0.0
ENV JOYSAFETER_GRPC_PORT=9090

EXPOSE 9090

CMD ["joysafeter-orchestrator"]
