# 前端生产镜像 Dockerfile
# 支持可配置的基础镜像源

# 可配置的基础镜像（默认使用官方镜像，可通过 ARG 切换到国内镜像）
ARG BASE_IMAGE_REGISTRY="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/"
ARG NODE_VERSION=20-alpine
FROM ${BASE_IMAGE_REGISTRY}node:${NODE_VERSION} AS base
RUN apk add --no-cache libc6-compat

FROM base AS deps
WORKDIR /app
RUN apk add --no-cache curl unzip bash && \
    BUN_VERSION=1.3.7 curl -fsSL https://bun.sh/install | bash
COPY package.json bun.lock* ./
RUN /root/.bun/bin/bun install --frozen-lockfile

FROM base AS builder
WORKDIR /app
RUN apk add --no-cache curl unzip bash && \
    BUN_VERSION=1.3.7 curl -fsSL https://bun.sh/install | bash
COPY --from=deps /app/node_modules ./node_modules
COPY package.json bun.lock* ./
COPY . .
# 使用 ARG 传递 API URL，支持通过环境变量配置（默认值保持向后兼容）
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN /root/.bun/bin/bun run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME="0.0.0.0"
RUN apk add --no-cache curl && \
    addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:3000 || exit 1

CMD ["node", "server.js"]
