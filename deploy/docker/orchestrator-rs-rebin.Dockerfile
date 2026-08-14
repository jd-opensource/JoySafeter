# 复用已有运行时镜像 (debian + ca-certificates + curl), 只替换二进制, 零网络。
# 仅用于本地快速迭代: zigbuild 出新二进制后换进现有镜像, 避免重新拉 base / apt。
ARG BASE=aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs:latest
ARG TARGET_TRIPLE=x86_64-unknown-linux-gnu
FROM ${BASE}
ARG TARGET_TRIPLE
USER root
COPY target/${TARGET_TRIPLE}/release/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator
RUN chmod +x /usr/local/bin/joysafeter-orchestrator
CMD ["/usr/local/bin/joysafeter-orchestrator"]
