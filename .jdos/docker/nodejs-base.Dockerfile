FROM ubuntu:24.04

# 1. 环境变量
ENV NODE_VERSION=24.1.0
ENV YARN_VERSION=1.22.22
ENV DEBIAN_FRONTEND=noninteractive

# 2. 替换为国内源
RUN ls -l /etc/apt/ /etc/apt/sources.list.d/ && \
    sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    sed -i 's|http://security.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    cat /etc/apt/sources.list.d/ubuntu.sources

# 3. 更新并安装构建依赖
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    build-essential \
    python3 \
    make \
    g++ \
    xz-utils \
    ca-certificates \
    git \
    tzdata \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 4. 创建 node 用户（与官方镜像保持一致）
RUN getent group 1000 || groupadd -g 1000 node && \
    id -u 1000 || useradd -u 1000 -g node -s /bin/bash -m node

# 5. 下载并验证 Node.js 源码
RUN GNUPGHOME="$(mktemp -d)" && export GNUPGHOME; \
    curl -fsSLO "https://mirrors.jd.com/nodejs-release/v${NODE_VERSION}/node-v${NODE_VERSION}.tar.xz" && \
    tar -xf "node-v${NODE_VERSION}.tar.xz" && \
    cd "node-v${NODE_VERSION}" && \
    ./configure --prefix=/usr/local && \
    make -j8  && \
    make install && \
    ln -s /usr/local/bin/node /usr/local/bin/nodejs && \
    cd / && \
    rm -rf "node-v${NODE_VERSION}" "node-v${NODE_VERSION}.tar.xz" "$GNUPGHOME" && \
    rm -rf /tmp/* && \
    npm set registry http://mirrors.jd.com/npm && \
    node --version

# 6. 下载并验证 Yarn
ENV YARN_URL="http://storage.jd.local/hiot/jdos/nodejs/yarn-v1.22.22.tar.gz?Expires=1779521856&AccessKey=I1TqSCHievGnzEob&Signature=WYHSBVjRQ0gCFmxARzsYP3gqT5A%3D"
RUN GNUPGHOME="$(mktemp -d)" && export GNUPGHOME; \
    curl -fsSL "$YARN_URL"  -o yarn-v${YARN_VERSION}.tar.gz && \
    mkdir -p /opt && \
    tar -xzf "yarn-v${YARN_VERSION}.tar.gz" -C /opt/ && \
    ln -s "/opt/yarn-v${YARN_VERSION}/bin/yarn" /usr/local/bin/yarn && \
    ln -s "/opt/yarn-v${YARN_VERSION}/bin/yarnpkg" /usr/local/bin/yarnpkg && \
    rm -rf "yarn-v${YARN_VERSION}.tar.gz"  "$GNUPGHOME" && \
    rm -rf /tmp/* && \
    echo 'registry = http://mirrors.jd.com/npm'> ~/.npmrc && \
    yarn --version

# 启用 corepack 并配置 pnpm
RUN npm install -g corepack@latest  && corepack enable
ENV PNPM_HOME="/pnpm"
ENV COREPACK_NPM_REGISTRY="http://mirrors.jd.com/npm"
ENV PATH="$PNPM_HOME:$PATH"
ENV NEXT_PUBLIC_BASE_PATH=


# 7. 默认入口
#COPY docker-entrypoint.sh /usr/local/bin/
# 生成 docker-entrypoint.sh
RUN echo '#!/bin/sh' > /usr/local/bin/docker-entrypoint.sh \
 && echo 'set -e' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '# 如果第一个参数以 “-” 开头，或不是系统命令，则自动在前面加上 node' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '# 最后的 { ... } 是为了绕开 ash/dash 的 bug：' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '# https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=874264' >> /usr/local/bin/docker-entrypoint.sh \
 && echo 'if [ "${1#-}" != "${1}" ] || [ -z "$(command -v "${1}")" ] || { [ -f "${1}" ] && ! [ -x "${1}" ]; }; then' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '  set -- node "$@"' >> /usr/local/bin/docker-entrypoint.sh \
 && echo 'fi' >> /usr/local/bin/docker-entrypoint.sh \
 && echo '' >> /usr/local/bin/docker-entrypoint.sh \
 && echo 'exec "$@"' >> /usr/local/bin/docker-entrypoint.sh \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["node"]
