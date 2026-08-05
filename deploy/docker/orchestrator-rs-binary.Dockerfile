# Rust orchestrator runtime image using a prebuilt Linux binary.

ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim

FROM ${RUNTIME_IMAGE} AS runner

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY target/x86_64-unknown-linux-gnu/release/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator

ENV RUST_LOG=info
ENV JOYSAFETER_ENABLED=true
ENV JOYSAFETER_GRPC_HOST=0.0.0.0
ENV JOYSAFETER_GRPC_PORT=9090

EXPOSE 9090

CMD ["joysafeter-orchestrator"]
