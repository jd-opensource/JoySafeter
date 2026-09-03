# Offline Agent Gateway packaging from a prebuilt Linux AMD64 binary.
# RUNTIME_IMAGE must already exist in the local Docker image store.
ARG RUNTIME_IMAGE=joysafeter-agent-gateway-runtime-base:local
FROM ${RUNTIME_IMAGE}

COPY --chown=10001:10001 target/x86_64-unknown-linux-gnu/release/joysafeter-agent-gateway /usr/local/bin/joysafeter-agent-gateway

USER 10001:10001
ENTRYPOINT ["joysafeter-agent-gateway"]
