# 修正 codex 镜像: 换新 runner 二进制 + 修正被污染的 ENTRYPOINT。
# codex 需要 codex-entrypoint.sh (生成 ~/.codex/config.toml), 不能用 runner-entrypoint.sh。
# 历史镜像的 ENTRYPOINT 被错误设成了 runner-entrypoint.sh (codex 镜像里没有该文件 → 起不来)。
ARG BASE
ARG TARGET_TRIPLE=x86_64-unknown-linux-gnu
FROM ${BASE}
ARG TARGET_TRIPLE
USER root
COPY target/${TARGET_TRIPLE}/release/joysafeter-runner /usr/local/bin/joysafeter-runner
RUN chmod +x /usr/local/bin/joysafeter-runner
COPY deploy/docker/codex-entrypoint.sh /usr/local/bin/codex-entrypoint.sh
RUN chmod +x /usr/local/bin/codex-entrypoint.sh
USER agent
ENTRYPOINT ["/usr/local/bin/codex-entrypoint.sh"]
