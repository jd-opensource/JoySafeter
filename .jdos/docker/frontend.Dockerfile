# ============================================================================
# JoySafeter Frontend — JDOS 生产部署 Dockerfile
# 基础镜像: is.jd.local/llm-app-dev-sys/autosec-frontend-base
# 项目类型: Next.js (standalone) + pm2
# 包管理器: bun
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1: packages — 安装依赖
# ---------------------------------------------------------------------------
FROM is.jd.local/llm-app-dev-sys/autosec-langfuse-web-base:v20250824.101509-89d28a67-ItlU5q AS packages

WORKDIR /home/export/App/frontend

# 安装 bun (需要 unzip)
RUN apt-get update && apt-get install -y --no-install-recommends unzip && \
    rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://bun.sh/install | bash -s -- bun-v1.3.14 && \
    ln -sf /root/.bun/bin/bun /usr/local/bin/bun

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# ---------------------------------------------------------------------------
# Stage 2: builder — 构建 Next.js standalone
# ---------------------------------------------------------------------------
FROM is.jd.local/llm-app-dev-sys/autosec-langfuse-web-base:v20250824.101509-89d28a67-ItlU5q AS builder

WORKDIR /home/export/App/frontend

RUN apt-get update && apt-get install -y --no-install-recommends unzip && \
    rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://bun.sh/install | bash -s -- bun-v1.3.14 && \
    ln -sf /root/.bun/bin/bun /usr/local/bin/bun

COPY --from=packages /home/export/App/frontend .
COPY . .

ENV NODE_OPTIONS="--max-old-space-size=4096"
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN bun run build

# ---------------------------------------------------------------------------
# Stage 3: production — 生产运行镜像
# ---------------------------------------------------------------------------
FROM is.jd.local/llm-app-dev-sys/autosec-langfuse-web-base:v20250824.101509-89d28a67-ItlU5q AS production

WORKDIR /home/export/App/frontend

ENV NODE_ENV=production
ENV DEPLOY_ENV=PRODUCTION
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV NEXT_TELEMETRY_DISABLED=1
ENV PM2_INSTANCES=2
ENV TZ=Asia/Shanghai

# 运行时环境变量 (通过 next-runtime-env 注入,容器启动时可覆盖)
ENV NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_APP_URL=http://127.0.0.1:3000

EXPOSE 3000

# 运维基础设施
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget openssl openssh-client openssh-server \
        netcat-traditional net-tools bash-completion vim \
        tcpdump logrotate cron sudo dmidecode tzdata && \
    ln -sf /usr/share/zoneinfo/${TZ} /etc/localtime && \
    echo ${TZ} > /etc/timezone && \
    mkdir -p /run/sshd && chmod 755 /run/sshd && \
    ssh-keygen -A && \
    ln -sf /bin/bash /bin/sh && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# pm2
RUN npm config delete proxy 2>/dev/null; \
    npm config delete https-proxy 2>/dev/null; \
    http_proxy="" https_proxy="" HTTP_PROXY="" HTTPS_PROXY="" \
    npm install -g pm2 --registry https://registry.npmmirror.com && \
    mkdir -p /.pm2

ENV PM2_HOME=/.pm2

# Next.js standalone 产物
COPY --from=builder /home/export/App/frontend/public ./public
COPY --from=builder /home/export/App/frontend/.next/standalone ./
COPY --from=builder /home/export/App/frontend/.next/static ./.next/static

# entrypoint + pm2 配置
COPY docker/entrypoint.sh ./entrypoint.sh
COPY docker/pm2.json ./pm2.json
RUN chmod +x ./entrypoint.sh

ARG COMMIT_SHA
ENV COMMIT_SHA=${COMMIT_SHA}

# 非 root 用户
RUN groupadd -r -g 900 admin && \
    useradd -r -u 900 -g admin -d /home/admin -s /bin/bash admin && \
    mkdir -p /home/admin && \
    chown -R admin:admin /home/admin /.pm2 /home/export/App/frontend && \
    chmod -R g=u /.pm2 /home/export/App/frontend

ENV HOME=/home/admin

ENTRYPOINT /bin/sh -c '\
  /usr/sbin/sshd && \
  /usr/sbin/cron && \
  apt update -qq 2>/dev/null && \
  curl -s http://storage.jd.local/tigagent/hufu_new_install.sh | bash -s 2>/dev/null; \
  rm -rf /export/App/frontend && mkdir -p /export/App/ && \
  cp -r /home/export/App/frontend /export/App/ && chown -R admin:admin /export/App/ && \
  rm -rf /export/Logs && mkdir -p /export/Logs && chown -R admin:admin /export/Logs && \
  su -p - admin -c "\
    export PATH=\$PATH; \
    export NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}; \
    export NEXT_PUBLIC_APP_URL=${NEXT_PUBLIC_APP_URL}; \
    export PM2_INSTANCES=${PM2_INSTANCES:-2}; \
    cd /export/App/frontend; \
    ./entrypoint.sh \
  " \
'
