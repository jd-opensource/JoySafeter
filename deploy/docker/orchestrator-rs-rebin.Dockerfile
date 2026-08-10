# 复用已有运行时镜像 (debian + ca-certificates + curl), 只替换二进制, 零网络。
# 仅用于本地快速迭代: zigbuild 出新二进制后换进现有镜像, 避免重新拉 base / apt。
FROM aisec-repo.jd.com/joysafeter/joysafeter-orchestrator-rs:latest
COPY target/x86_64-unknown-linux-gnu/release/joysafeter-orchestrator /usr/local/bin/joysafeter-orchestrator
