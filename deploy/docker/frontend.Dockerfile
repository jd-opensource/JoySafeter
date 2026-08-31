# 前端生产镜像 Dockerfile
# 支持可配置的基础镜像源

# 可配置的基础镜像（默认使用官方镜像，可通过 ARG 切换到国内镜像）
ARG BASE_IMAGE_REGISTRY="public.ecr.aws/docker/library/"
ARG NODE_VERSION=20-alpine
FROM ${BASE_IMAGE_REGISTRY}node:${NODE_VERSION} AS base

ARG ALPINE_MIRROR_BASE="https://mirrors.ustc.edu.cn/alpine"
RUN sed -i "s|https*://dl-cdn.alpinelinux.org/alpine|${ALPINE_MIRROR_BASE}|g" /etc/apk/repositories \
    && apk add --no-cache libc6-compat

FROM base AS deps
WORKDIR /app
RUN apk add --no-cache curl unzip bash && \
    curl -fsSL https://bun.sh/install | bash -s -- bun-v1.3.14
COPY package.json bun.lock* ./
RUN /root/.bun/bin/bun install --frozen-lockfile

FROM base AS builder
WORKDIR /app
RUN apk add --no-cache curl unzip bash && \
    curl -fsSL https://bun.sh/install | bash -s -- bun-v1.3.14
COPY --from=deps /app/node_modules ./node_modules
COPY package.json bun.lock* ./
COPY . .
# Public runtime envs are injected by next-runtime-env when the container starts.
# Do not bake deployment domains into the static bundle at image build time.
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    NODE_OPTIONS="--max-old-space-size=4096"
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
