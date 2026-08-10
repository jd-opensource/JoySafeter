# 基于已有沙箱镜像换 runner 二进制, 只替换一层, 零网络/零重建。
# 用法: docker build --build-arg BASE=<现有镜像> -f sandbox-runner-rebin.Dockerfile -t <同名> .
# ENTRYPOINT 从 base 继承 (runner-entrypoint.sh)，最终用户恢复为 agent。
ARG BASE
FROM ${BASE}
USER root
COPY target/x86_64-unknown-linux-gnu/release/joysafeter-runner /usr/local/bin/joysafeter-runner
RUN chmod +x /usr/local/bin/joysafeter-runner
USER agent
