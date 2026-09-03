# Offline Orchestrator packaging from a prebuilt Linux AMD64 binary.
# RUNTIME_IMAGE must already exist in the local Docker image store.
ARG RUNTIME_IMAGE=joysafeter-orchestrator-runtime-base:local
FROM ${RUNTIME_IMAGE}

COPY target/x86_64-unknown-linux-gnu/release/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator

ENTRYPOINT ["joysafeter-orchestrator"]
