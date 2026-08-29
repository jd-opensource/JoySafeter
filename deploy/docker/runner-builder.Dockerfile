ARG RUST_IMAGE="public.ecr.aws/docker/library/rust:1-bookworm"
FROM ${RUST_IMAGE} AS builder

RUN apt-get update \
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
RUN cargo build --release -p joysafeter-runner

FROM scratch AS export
COPY --from=builder /src/sandbox-runner/target/release/joysafeter-runner /joysafeter-runner
