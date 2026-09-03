# JoySafeter Agent Gateway production image.

ARG RUST_IMAGE=public.ecr.aws/docker/library/rust:1-bookworm
ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim

FROM ${RUST_IMAGE} AS builder

WORKDIR /src
ENV CARGO_HTTP_TIMEOUT=600 \
    CARGO_HTTP_MULTIPLEXING=false \
    CARGO_NET_RETRY=10 \
    CARGO_BUILD_JOBS=2

COPY shared/rust/joysafeter-entity-id ./shared/rust/joysafeter-entity-id
COPY shared/rust/joysafeter-agent-gateway-contract ./shared/rust/joysafeter-agent-gateway-contract
COPY backend/app/joysafeter_agent_gateway ./backend/app/joysafeter_agent_gateway

WORKDIR /src/backend/app/joysafeter_agent_gateway
RUN cargo build --locked --release

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
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin joysafeter

COPY --from=builder /src/backend/app/joysafeter_agent_gateway/target/release/joysafeter-agent-gateway /usr/local/bin/joysafeter-agent-gateway

USER 10001:10001
ENV RUST_LOG=info
EXPOSE 9092 9093
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD curl --fail --silent http://127.0.0.1:9093/health/live || exit 1
ENTRYPOINT ["joysafeter-agent-gateway"]
