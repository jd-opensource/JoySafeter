# 前端生产镜像 Dockerfile
# 支持可配置的基础镜像源

# 可配置的基础镜像（默认使用官方镜像，可通过 ARG 切换到国内镜像）
ARG BASE_IMAGE_REGISTRY="public.ecr.aws/docker/library/"
ARG NODE_VERSION=20-alpine
ARG BUN_IMAGE=oven/bun:1.3.14-alpine
FROM ${BUN_IMAGE} AS bun_runtime

FROM ${BASE_IMAGE_REGISTRY}node:${NODE_VERSION} AS base
RUN apk add --no-cache libc6-compat

FROM base AS deps
WORKDIR /app
COPY --from=bun_runtime /usr/local/bin/bun /usr/local/bin/bun
COPY package.json bun.lock* ./
RUN bun install --frozen-lockfile

FROM base AS builder
WORKDIR /app
COPY --from=bun_runtime /usr/local/bin/bun /usr/local/bin/bun
COPY --from=deps /app/node_modules ./node_modules
COPY package.json bun.lock* ./
COPY . .
# Public runtime envs are injected by next-runtime-env when the container starts.
# Do not bake deployment domains into the static bundle at image build time.
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    NODE_OPTIONS="--max-old-space-size=4096"
RUN bun run build

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
