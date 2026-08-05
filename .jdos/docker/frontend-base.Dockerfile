# ============================================================================
# JoySafeter Frontend Base — JDOS 基础镜像
#
# 用途:
# - 预置 Node.js、bun、pm2 以及 JDOS 运行期常用工具。
# - 前端应用镜像构建时直接 FROM 该基础镜像，避免每次构建重复 apt install、下载 bun、安装 pm2。
#
# 构建后建议推送为:
#   is.jd.local/llm-app-dev-sys/joysafeter-frontend-base:<immutable-tag>
# 然后在 frontend-build.yam 的 FRONTEND_BASE_IMAGE 中引用该 tag。
# ============================================================================

FROM is.jd.local/llm-app-dev-sys/autosec-langfuse-web-base:v20250824.101509-89d28a67-ItlU5q

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV BUN_VERSION=1.3.14
ENV BUN_INSTALL=/opt/bun
ENV PM2_HOME=/.pm2
ENV NEXT_PUBLIC_BASE_PATH=
ENV PATH="${BUN_INSTALL}/bin:${PATH}"

# 基础构建工具 + 生产运行常用运维工具。
# 这些内容在基础镜像层完成，避免每次应用镜像构建重复安装。
RUN apt-get update && apt-get install -y --no-install-recommends \
        unzip \
        curl \
        wget \
        ca-certificates \
        openssl \
        openssh-client \
        openssh-server \
        netcat-traditional \
        net-tools \
        bash-completion \
        vim \
        tcpdump \
        logrotate \
        cron \
        sudo \
        dmidecode \
        tzdata && \
    ln -sf /usr/share/zoneinfo/${TZ} /etc/localtime && \
    echo ${TZ} > /etc/timezone && \
    mkdir -p /run/sshd && chmod 755 /run/sshd && \
    ssh-keygen -A && \
    ln -sf /bin/bash /bin/sh && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# bun 只在基础镜像构建时安装一次，应用镜像构建无需再访问 bun.sh。
RUN curl -fsSL https://bun.sh/install | bash -s -- bun-v${BUN_VERSION} && \
    ln -sf ${BUN_INSTALL}/bin/bun /usr/local/bin/bun && \
    bun --version

# pm2 只在基础镜像构建时安装一次。
RUN npm config delete proxy 2>/dev/null; \
    npm config delete https-proxy 2>/dev/null; \
    http_proxy="" https_proxy="" HTTP_PROXY="" HTTPS_PROXY="" \
    npm install -g pm2 --registry https://registry.npmmirror.com && \
    mkdir -p ${PM2_HOME} && \
    pm2 --version

# 与官方 node 镜像保持类似入口，便于作为通用 Node/Bun 基础镜像使用。
RUN echo '#!/bin/sh' > /usr/local/bin/docker-entrypoint.sh \
 && echo 'set -e' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '' >> /usr/local/bin/docker-entrypoint.sh \
 && echo 'if [ "${1#-}" != "${1}" ] || [ -z "$(command -v "${1}")" ] || { [ -f "${1}" ] && ! [ -x "${1}" ]; }; then' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '  set -- node "$@"' >> /usr/local/bin/docker-entrypoint.sh \
 && echo 'fi' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '' >> /usr/local/bin/docker-entrypoint.sh \
 && echo 'exec "$@"' >> /usr/local/bin/docker-entrypoint.sh \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["node"]
