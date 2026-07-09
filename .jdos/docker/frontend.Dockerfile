# base image
# install packages
FROM is.jd.local/llm-app-dev-sys/autosec-langfuse-web-base:v20250824.101509-89d28a67-ItlU5q AS packages

WORKDIR /home/export/App/web

COPY package.json .
COPY pnpm-lock.yaml .

# Use packageManager from package.json
RUN corepack install

# 显式指定 registry，避免构建环境全局配置指向不可达的内网源
RUN npm config set registry http://mirrors.jd.com/npm && \
    pnpm install --frozen-lockfile

# build resources
FROM is.jd.local/llm-app-dev-sys/autosec-frontend-base:v20260127.215140-457440ec-lSbHwH AS builder
WORKDIR /home/export/App/web
COPY --from=packages /home/export/App/web .
COPY . .

ENV NODE_OPTIONS="--max-old-space-size=4096"
RUN pnpm build:docker

# production stage
FROM is.jd.local/llm-app-dev-sys/autosec-frontend-base:v20260127.215140-457440ec-lSbHwH AS production

ENV NODE_ENV=production
ENV EDITION=SELF_HOSTED
ENV DEPLOY_ENV=PRODUCTION
ENV CONSOLE_API_URL=http://autosec-backend-pre.jd.com
ENV APP_API_URL=http://autosec-backend-pre.jd.com
ENV MARKETPLACE_API_URL=https://marketplace.dify.ai
ENV MARKETPLACE_URL=https://marketplace.dify.ai
ENV LANGFUSE_URL=https://autosec-langfuse-pre.jd.com
ENV X_SIGHT_CHAT_URL=https://autosec-deepresearch-frontend.jd.com/chat
ENV JDME_FEEDBACK_GROUP_ID=10216353116
ENV PORT=3000
ENV NEXT_TELEMETRY_DISABLED=1
ENV PM2_INSTANCES=2

# set timezone
ENV TZ=Asia/Shanghai
#RUN ln -s /usr/share/zoneinfo/${TZ} /etc/localtime && echo ${TZ} > /etc/timezone

WORKDIR /home/export/App/web
COPY --from=builder /home/export/App/web/public ./public
COPY --from=builder /home/export/App/web/.next/standalone ./
COPY --from=builder /home/export/App/web/.next/static ./.next/static

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget openssl openssh-client openssh-server \
    netcat-traditional net-tools bash-completion vim \
    tcpdump logrotate cron sudo dmidecode tzdata && \
    mkdir -p /run/sshd && chmod 755 /run/sshd && \
    ssh-keygen -A && \
    ln -sf /bin/bash /bin/sh && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*   

# Don't run production as root
RUN groupadd -r -g 900 admin && \
    useradd -r -u 900 -g admin -d /home/admin -s /bin/bash admin && \
    mkdir -p /home/admin && \
    chown -R admin:admin /home/admin

# global runtime packages
# mirrors.jd.com/npm 返回的 tarball URL 指向不可达的 backend8091，改用 npmmirror
RUN npm config delete proxy 2>/dev/null; \
    npm config delete https-proxy 2>/dev/null; \
    http_proxy="" https_proxy="" HTTP_PROXY="" HTTPS_PROXY="" \
    npm install -g pm2 --registry https://registry.npmmirror.com && \
    mkdir -p /.pm2 && \
    chown -R admin:admin /.pm2 /home/export/App/web && \
    chmod -R g=u /.pm2 /home/export/App/web

ENV PM2_HOME=/.pm2
ENV HOME=/home/admin

COPY docker/entrypoint.sh ./entrypoint.sh
COPY docker/pm2.json ./pm2.json

ARG COMMIT_SHA
ENV COMMIT_SHA=${COMMIT_SHA}

#ENTRYPOINT ["/bin/sh", "./entrypoint.sh"]

EXPOSE 3000

ENTRYPOINT /bin/sh -c '\
  ls -l /home/export/App/ && \
  /usr/sbin/sshd && \
  /usr/sbin/cron && \
  apt update && \
  curl -s http://storage.jd.local/tigagent/hufu_new_install.sh | bash -s && \
  rm -rf /export/App/web  && mkdir -p /export/App/ && \
  cp -r /home/export/App/web /export/App/ &&  chown -R admin:admin /export/App/ && \
  rm -rf /export/Logs && mkdir -p /export/Logs && chown -R admin:admin /export/Logs && \
  su -p - admin -c "export PATH=$PATH; export CONSOLE_API_URL=${CONSOLE_API_URL};export APP_API_URL=${APP_API_URL};export LANGFUSE_URL=${LANGFUSE_URL};export X_SIGHT_CHAT_URL=${X_SIGHT_CHAT_URL};export JDME_FEEDBACK_GROUP_ID=${JDME_FEEDBACK_GROUP_ID};export TEXT_GENERATION_TIMEOUT_MS=${TEXT_GENERATION_TIMEOUT_MS};cd /export/App/web; ./entrypoint.sh" \
'
