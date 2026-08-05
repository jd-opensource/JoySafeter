# ============================================================================
# JoySafeter Frontend — JDOS 生产部署 Dockerfile
# 基础镜像: is.jd.local/llm-app-dev-sys/joysafeter-frontend-base
# 项目类型: Next.js (standalone) + pm2
# 包管理器: bun
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1: packages — 安装依赖
# ---------------------------------------------------------------------------
ARG FRONTEND_BASE_IMAGE=is.jd.local/llm-app-dev-sys/joysafeter-frontend-base:v20260805.161016-7abedcb1-Tv78n1

FROM ${FRONTEND_BASE_IMAGE} AS packages

WORKDIR /home/export/App/frontend

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# ---------------------------------------------------------------------------
# Stage 2: builder — 构建 Next.js standalone
# ---------------------------------------------------------------------------
FROM ${FRONTEND_BASE_IMAGE} AS builder

WORKDIR /home/export/App/frontend

COPY --from=packages /home/export/App/frontend .
COPY . .

ENV NODE_OPTIONS="--max-old-space-size=4096"
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN bun run build

# ---------------------------------------------------------------------------
# Stage 3: production — 生产运行镜像
# ---------------------------------------------------------------------------
FROM ${FRONTEND_BASE_IMAGE} AS production

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

# 运维基础设施、bun 和 pm2 已预置在 frontend-base 镜像中。
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
