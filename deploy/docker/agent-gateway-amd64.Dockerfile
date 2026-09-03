# Agent Gateway runtime image using a prebuilt Linux AMD64 binary.
# Build the binary first with:
# cargo zigbuild --locked --release --target x86_64-unknown-linux-gnu

ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim

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

COPY target/x86_64-unknown-linux-gnu/release/joysafeter-agent-gateway /usr/local/bin/joysafeter-agent-gateway

USER 10001:10001
ENV RUST_LOG=info
EXPOSE 9092 9093
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD curl --fail --silent http://127.0.0.1:9093/health/live || exit 1
ENTRYPOINT ["joysafeter-agent-gateway"]
